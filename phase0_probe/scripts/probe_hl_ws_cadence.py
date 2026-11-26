"""PR #1.5 item 3 — measure Hyperliquid WS push cadence and latency per subscription (READ-ONLY, public).

Usage: uv run python scripts/probe_hl_ws_cadence.py [--secs 30] [--coin BTC]
Opens one connection per subscription and reports message count, inter-message gap p50/max and
latency = local receive − exchange ``time``/``t`` (ms; includes any local-vs-exchange clock offset).
Subscriptions: ``l2Book`` (default), ``l2Book`` nSigFigs=5, ``l2Book`` with the UNDOCUMENTED ``fast: true`` flag that
the subscription ack echoes (``"fast": false`` by default), ``l2`` (documented, item 23 of websocket/subscriptions.md),
``bbo``. Docs: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions.md
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import websockets  # noqa: E402

from phase0_probe.dec import loads, now_ms  # noqa: E402
from phase0_probe.feeds import hl_decode  # noqa: E402
from phase0_probe.venues import HL_WS  # noqa: E402


def pct(xs: list[int], p: int) -> int | None:
    return sorted(xs)[min(len(xs) - 1, len(xs) * p // 100)] if xs else None


async def run(sub: dict[str, Any], secs: int) -> dict[str, Any]:
    times: list[int] = []
    lat: list[int] = []
    ack: Any = None
    async with websockets.connect(HL_WS, max_size=2 ** 24) as ws:
        await ws.send(json.dumps({"method": "subscribe", "subscription": sub}))
        end = now_ms() + secs * 1000
        while now_ms() < end:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2)
            except asyncio.TimeoutError:
                continue
            recv = now_ms()
            m = loads(raw)
            if m.get("channel") == "subscriptionResponse":
                ack = m.get("data")
                continue
            d, t = m.get("data"), None
            if isinstance(d, dict):
                if "s" in d:
                    t = d["s"].get("time")
                elif "u" in d:
                    t = d["u"].get("t")
                elif isinstance(d.get("c"), str) and m.get("channel") == "l2":
                    t = hl_decode(d["c"]).get("t")
                else:
                    t = d.get("time")
            times.append(recv)
            if isinstance(t, int):
                lat.append(recv - t)
    gaps = [b - a for a, b in zip(times, times[1:])]
    return {"sub": sub, "ack": ack, "msgs": len(times), "gap_ms_p50": pct(gaps, 50), "gap_ms_max": max(gaps, default=None),
            "latency_ms_p10": pct(lat, 10), "latency_ms_p50": pct(lat, 50), "latency_ms_p90": pct(lat, 90)}


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=int, default=30)
    ap.add_argument("--coin", default="BTC")
    a = ap.parse_args(argv)
    subs = [{"type": "l2Book", "coin": a.coin}, {"type": "l2Book", "coin": a.coin, "nSigFigs": 5},
            {"type": "l2Book", "coin": a.coin, "fast": True}, {"type": "l2", "c": a.coin}, {"type": "bbo", "coin": a.coin}]
    for r in await asyncio.gather(*[run(s, a.secs) for s in subs]):
        print(json.dumps(r, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
