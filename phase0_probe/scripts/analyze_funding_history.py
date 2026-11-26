"""PR #1.5 item 2 — hourly funding-history back-test, Arcus vs Hyperliquid (READ-ONLY public REST).

Usage: uv run python scripts/analyze_funding_history.py [--days 30] [--sym BTC --sym ETH --sym SOL]
       [--pair NVDA=io:NVDA] [--out reports]

Sources (documented):
* Arcus  GET /v1/fundingRates?market=&from=&to=&limit=  (newest-first, ``from``/``to``/``time`` in epoch µs, limit
  ≤ 1000) — https://docs.arcus.xyz/api-reference/public/get-market-funding-rates.md ; hourly decimal fractions.
* HL     POST /info {"type":"fundingHistory","coin","startTime","endTime"} (ms; ≤ 500 rows per response, paginate
  from the last ``time``) — https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals.md
  and info-endpoint.md (pagination); hourly decimal fractions.
Alignment: both series bucketed by payment hour (epoch ms floored to the hour); only hours present on both are used.
Directions: SHORT_ARCUS_LONG_HL carry/h = arcus − hl; LONG_ARCUS_SHORT_HL = hl − arcus.
Round-trip fees (open + close, both legs, tier 0, from live /v1/markets + metaAndAssetCtxs): DUAL_TAKER,
MAKER_ARCUS_TAKER_HL, MAKER_HL_TAKER_ARCUS. Funding only: price/basis PnL, slippage and the buffer are NOT included.
"""
from __future__ import annotations

import argparse
import asyncio
import pathlib
import sys
from decimal import Decimal
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import aiohttp  # noqa: E402

from phase0_probe.dec import D, dumps, fmt, now_ms  # noqa: E402
from phase0_probe.discovery import parse_arcus, parse_hl  # noqa: E402
from phase0_probe.funding import align_hourly, direction_stats  # noqa: E402
from phase0_probe.venues import ARCUS_REST, get_json, hl_info  # noqa: E402

TWO = Decimal(2)


async def arcus_history(sess: aiohttp.ClientSession, market: str, start_ms: int, end_ms: int) -> list[tuple[int, Decimal]]:
    out: list[tuple[int, Decimal]] = []
    to_us = end_ms * 1000
    while True:
        body = await get_json(sess, f"{ARCUS_REST}/v1/fundingRates",
                              params={"market": market, "from": str(start_ms * 1000), "to": str(to_us), "limit": "1000"})
        rows = body.get("fundingRates") or []
        out += [(int(r["time"]) // 1000, D(r["fundingRate"])) for r in rows]
        if len(rows) < 1000:
            break
        to_us = min(int(r["time"]) for r in rows) - 1          # newest-first: continue below the oldest
        await asyncio.sleep(1)
    return sorted(set(out))


async def hl_history(sess: aiohttp.ClientSession, coin: str, start_ms: int, end_ms: int) -> list[tuple[int, Decimal]]:
    out: list[tuple[int, Decimal]] = []
    t = start_ms
    while t < end_ms:
        rows = await hl_info(sess, {"type": "fundingHistory", "coin": coin, "startTime": t, "endTime": end_ms})
        if not rows:
            break
        out += [(int(r["time"]), D(r["fundingRate"])) for r in rows]
        last = max(int(r["time"]) for r in rows)
        if len(rows) < 500 or last + 1 <= t:
            break
        t = last + 1
        await asyncio.sleep(1)
    return sorted(set(out))


async def fees(sess: aiohttp.ClientSession, pairs: list[tuple[str, str]]) -> dict[str, dict[str, Decimal]]:
    markets = await get_json(sess, f"{ARCUS_REST}/v1/markets")
    fs = await get_json(sess, f"{ARCUS_REST}/v1/markets/feeSchedules")
    arcus = {a.base: a for a in parse_arcus(markets, fs)}
    hl: dict[str, Any] = {}
    for dex in sorted({c.split(":", 1)[0] if ":" in c else "" for _, c in pairs}):
        body = {"type": "metaAndAssetCtxs"} | ({"dex": dex} if dex else {})
        hl.update({h.coin: h for h in parse_hl(await hl_info(sess, body), dex=dex)})
    out = {}
    for sym, coin in pairs:
        a, h = arcus[sym], hl[coin]
        out[sym] = {"DUAL_TAKER": TWO * (a.taker_fee + h.taker_fee),
                    "MAKER_ARCUS_TAKER_HL": TWO * (a.maker_fee + h.taker_fee),
                    "MAKER_HL_TAKER_ARCUS": TWO * (a.taker_fee + h.maker_fee)}
    return out


def md(rep: dict[str, Any]) -> str:
    L = [f"# Funding history back-test (PR #1.5, read-only) — {rep['days']} days", "",
         f"Window requested: epoch ms {rep['start_ms']} → {rep['end_ms']}. Hourly, aligned by payment hour. "
         "Carry = funding received per hour as a fraction of notional (positive = you receive). Fees = round trip "
         "(open + close, both legs, tier 0). Funding only — no basis/price PnL, slippage or buffer.", "",
         "| Symbol | Direction | hours | mean bps/h | daily bps | annualized % | % hours > 0 | longest + run h | "
         "avg + run h | sign flips | total carry bps |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for sym, r in rep["symbols"].items():
        for dname, st in r["directions"].items():
            if not st.get("hours"):
                continue
            L.append(f"| {sym} | {dname} | {st['hours']} | {fmt(st['mean_hourly'] * 10_000, 4)} | "
                     f"{fmt(st['daily_mean'] * 10_000, 3)} | {fmt(st['annualized'] * 100, 3)} | "
                     f"{fmt(st['pct_hours_positive'], 1)} | {st['longest_positive_run_h']} | "
                     f"{fmt(st['avg_positive_run_h'], 2)} | {st['sign_flips']} | {fmt(st['total_carry_bps'], 3)} |")
    L += ["", "## Break-even after round-trip fees", "",
          "| Symbol | Direction | Fee mode | RT fee bps | expected BE h (fee/mean) | BE h entering at window start | "
          "rolling entries breaking even | median BE h (those) | net PnL holding whole window bps |",
          "|---|---|---|---|---|---|---|---|---|"]
    for sym, r in rep["symbols"].items():
        for dname, st in r["directions"].items():
            for mode, b in (st.get("by_fee_mode") or {}).items():
                L.append(f"| {sym} | {dname} | {mode} | {fmt(b['round_trip_fee_bps'], 2)} | "
                         f"{fmt(b['expected_breakeven_h'], 1) if b['expected_breakeven_h'] is not None else 'never (mean ≤ 0)'} | "
                         f"{b['breakeven_h_entering_at_window_start'] or 'never'} | "
                         f"{b['rolling_entries_breaking_even']}/{b['rolling_entries']} | "
                         f"{b['rolling_median_breakeven_h'] or 'n/a'} | {fmt(b['net_pnl_hold_whole_window_bps'], 3)} |")
    L += ["", "## Coverage", ""]
    for sym, r in rep["symbols"].items():
        L.append(f"* {sym}: Arcus rows {r['arcus_rows']} (first {r['arcus_first_ms']}), HL rows {r['hl_rows']} "
                 f"(first {r['hl_first_ms']}), aligned hours {r['aligned_hours']}, Arcus distinct rate values "
                 f"{r['arcus_distinct_rates']}, Arcus hours at exactly 0.0000125 (crypto base): "
                 f"{r['arcus_hours_at_base']}")
    return "\n".join(L) + "\n"


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--sym", action="append", default=None)
    ap.add_argument("--pair", action="append", default=None, help="SYM=HLCOIN (e.g. NVDA=io:NVDA)")
    ap.add_argument("--out", default="reports")
    ap.add_argument("--name", default="funding_history")
    args = ap.parse_args(argv)
    pairs = [(s, s) for s in (args.sym or ([] if args.pair else ["BTC", "ETH", "SOL"]))]
    pairs += [tuple(p.split("=", 1)) for p in (args.pair or [])]          # type: ignore[misc]
    end = now_ms() // 3_600_000 * 3_600_000 + 60_000
    start = end - args.days * 24 * 3_600_000
    rep: dict[str, Any] = {"days": args.days, "start_ms": start, "end_ms": end, "symbols": {}}
    async with aiohttp.ClientSession() as sess:
        fee = await fees(sess, pairs)                                  # type: ignore[arg-type]
        for sym, coin in pairs:
            a = await arcus_history(sess, f"{sym}-USD", start, end)
            h = await hl_history(sess, coin, start, end)
            al = align_hourly(a, h)
            short_a = [ar - hr for _, ar, hr in al]
            long_a = [hr - ar for _, ar, hr in al]
            rep["symbols"][sym] = {
                "hl_coin": coin, "arcus_rows": len(a), "hl_rows": len(h), "aligned_hours": len(al),
                "arcus_first_ms": a[0][0] if a else None, "hl_first_ms": h[0][0] if h else None,
                "arcus_distinct_rates": len({r for _, r in a}),
                "arcus_hours_at_base": sum(1 for _, r in a if r == D("0.0000125")),
                "fees": fee[sym],
                "directions": {"SHORT_ARCUS_LONG_HL": direction_stats(short_a, fee[sym]),
                               "LONG_ARCUS_SHORT_HL": direction_stats(long_a, fee[sym])},
                "hourly": [{"hour_ms": t, "arcus": ar, "hl": hr} for t, ar, hr in al],
            }
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.name}.json").write_text(dumps(rep))
    text = md(rep)
    (out / f"{args.name}.md").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
