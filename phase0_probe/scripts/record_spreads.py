"""Record Arcus vs Hyperliquid L2 books + funding and evaluate arbitrage every second (READ-ONLY, public data).

Usage: uv run python scripts/record_spreads.py --duration-s 600 [--db reports/spreads.sqlite]
       [--pair BTC=BTC --pair ETH=ETH --pair SOL=SOL] [--pair NVDA=io:NVDA] [--q 100 --q 500 --q 2000]
       [--stale-ms 500] [--buffer-bps 2]
--pair SYMBOL=HLCOIN maps Arcus ``SYMBOL-USD`` to a Hyperliquid coin (``BTC`` core, ``io:NVDA`` Entropy dex).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import pathlib
import sys
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import aiohttp  # noqa: E402

from phase0_probe.dec import D, now_ms  # noqa: E402
from phase0_probe.discovery import parse_arcus, parse_hl  # noqa: E402
from phase0_probe.feeds import ArcusBookFeed, ArcusMarketsFeed, HlBookFeed  # noqa: E402
from phase0_probe.model import VenueSpec  # noqa: E402
from phase0_probe.recorder import Pair, Recorder  # noqa: E402
from phase0_probe.store import Store  # noqa: E402
from phase0_probe.venues import ARCUS_REST, get_json, hl_info  # noqa: E402


async def load_specs(pairs: list[tuple[str, str]]) -> dict[str, tuple[VenueSpec, VenueSpec]]:
    dexes = sorted({c.split(":", 1)[0] if ":" in c else "" for _, c in pairs})
    async with aiohttp.ClientSession() as s:
        markets = await get_json(s, f"{ARCUS_REST}/v1/markets")
        fees = await get_json(s, f"{ARCUS_REST}/v1/markets/feeSchedules")
        hl = []
        for dex in dexes:
            body = {"type": "metaAndAssetCtxs"} | ({"dex": dex} if dex else {})
            hl += parse_hl(await hl_info(s, body), dex=dex)
    arcus = {a.base: a for a in parse_arcus(markets, fees)}
    hlm = {h.coin: h for h in hl}
    out = {}
    for sym, coin in pairs:
        a, h = arcus[sym], hlm[coin]
        out[sym] = (VenueSpec("arcus", sym, a.step, a.min_notional, a.maker_fee, a.taker_fee),
                    VenueSpec("hyperliquid", sym, h.step, h.min_notional, h.maker_fee, h.taker_fee))
    return out


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration-s", type=int, default=600)
    ap.add_argument("--db", default="reports/spreads.sqlite")
    ap.add_argument("--log", default="reports/record_spreads.log")
    ap.add_argument("--pair", action="append", default=None)
    ap.add_argument("--q", action="append", default=None)
    ap.add_argument("--stale-ms", type=int, default=500)
    ap.add_argument("--buffer-bps", default="2")
    args = ap.parse_args(argv)
    pairs = [tuple(p.split("=", 1)) for p in (args.pair or ["BTC=BTC", "ETH=ETH", "SOL=SOL"])]
    qs = [D(q) for q in (args.q or ["100", "500", "2000"])]
    pathlib.Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        handlers=[logging.FileHandler(args.log), logging.StreamHandler()])
    specs = await load_specs(pairs)          # type: ignore[arg-type]
    store = Store(args.db)
    store.put_meta("started_ms", str(now_ms()))
    store.put_meta("args", " ".join(argv))
    stop = asyncio.Event()
    markets = ArcusMarketsFeed([f"{sym}-USD" for sym, _ in pairs], sink=lambda *a: None)
    rec = Recorder(store, [], markets, qs=qs, stale_ms=args.stale_ms, buffer_bps=Decimal(args.buffer_bps))
    markets.sink = rec.sink
    for sym, coin in pairs:
        sa, sb = specs[sym]
        rec.pairs.append(Pair(sym, ArcusBookFeed(f"{sym}-USD", rec.sink), HlBookFeed(sym, coin, rec.sink), sa, sb))
        store.put_meta(f"spec:{sym}", f"arcus step={sa.step} min={sa.min_notional} maker={sa.maker_fee} "
                                      f"taker={sa.taker_fee} | hl coin={coin} step={sb.step} min={sb.min_notional} "
                                      f"maker={sb.maker_fee} taker={sb.taker_fee}")
    tasks = [asyncio.create_task(markets.run(stop)), asyncio.create_task(rec.poll_predicted(stop)),
             asyncio.create_task(rec.sampler(stop))]
    for p in rec.pairs:
        tasks += [asyncio.create_task(p.arcus.run(stop)), asyncio.create_task(p.hl.run(stop))]
    try:
        await asyncio.sleep(args.duration_s)
    finally:
        stop.set()
        await asyncio.wait(tasks, timeout=10)
        for p in rec.pairs:
            for f in (p.arcus, p.hl):
                st = f.stats
                store.put_meta(f"stats:{f.book.venue}:{p.symbol}",
                               f"frames={st.frames} reconnects={st.reconnects} gaps={st.gaps} "
                               f"integrity_errors={st.integrity_errors} hb_confirmed={st.hb_confirmed} "
                               f"hb_mismatch={st.hb_mismatch} l2Book_checks_ok={st.checks_ok} "
                               f"l2Book_checks_bad={st.checks_bad}")
        store.put_meta("ended_ms", str(now_ms()))
        store.close()
    logging.info("done: %s ticks -> %s", rec.ticks, args.db)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
