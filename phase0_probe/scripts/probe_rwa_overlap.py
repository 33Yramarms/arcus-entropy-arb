"""PR #1.5 item 4 — Arcus ∩ Entropy (HL dex "io") equity/ETF perps: pick the top N and probe them (READ-ONLY).

Usage: uv run python scripts/probe_rwa_overlap.py [--top 5] [--rank volume|depth] [--out reports]

Ranking (default ``volume``): min(Arcus ``volume24hNotional``, HL ``dayNtlVlm``) — the binding (thinner) side, since an
arbitrage needs both legs. ``depth``: min of the two venues' notional within ±10 bps of mid (live L2 books).
Per pick: io live maker/taker (HIP-3 scale from ``deployerFeeScale`` + ``growthMode``; hyperliquid-docs/trading/fees.md),
margin mode (``marginMode`` / ``onlyIsolated``), max leverage, min notional, both venues' hourly funding, L2 spread
(bps of mid), RTH flags (Arcus ``isOutsideRth`` / ``regularTradingHours``). Writes reports/rwa_overlap_probe.{json,md}
and prints the record_spreads.py command for an RTH session.
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

from phase0_probe.dec import BPS, HOURS_PER_YEAR, D, dumps, fmt, now_ms  # noqa: E402
from phase0_probe.discovery import parse_arcus, parse_hl  # noqa: E402
from phase0_probe.venues import ARCUS_REST, ENTROPY_DEX, get_json, hl_info  # noqa: E402

BAND_BPS = Decimal(10)


def depth_within(levels: list[tuple[Decimal, Decimal]], mid: Decimal, bid: bool) -> Decimal:
    lim = mid * (1 - BAND_BPS / BPS) if bid else mid * (1 + BAND_BPS / BPS)
    return sum((p * s for p, s in levels if (p >= lim if bid else p <= lim)), Decimal(0))


def book_stats(bids: list[tuple[Decimal, Decimal]], asks: list[tuple[Decimal, Decimal]]) -> dict[str, Any]:
    if not bids or not asks:
        return {"best_bid": None, "best_ask": None, "spread_bps": None, "depth10_bid_usd": None, "depth10_ask_usd": None}
    bb, ba = bids[0][0], asks[0][0]
    mid = (bb + ba) / 2
    return {"best_bid": bb, "best_ask": ba, "mid": mid, "spread_bps": (ba - bb) / mid * BPS,
            "depth10_bid_usd": depth_within(bids, mid, True), "depth10_ask_usd": depth_within(asks, mid, False)}


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--rank", choices=["volume", "depth"], default="volume")
    ap.add_argument("--out", default="reports")
    args = ap.parse_args(argv)
    t0 = now_ms()
    async with aiohttp.ClientSession() as s:
        markets = await get_json(s, f"{ARCUS_REST}/v1/markets")
        fees = await get_json(s, f"{ARCUS_REST}/v1/markets/feeSchedules")
        io_raw = await hl_info(s, {"type": "metaAndAssetCtxs", "dex": ENTROPY_DEX})
        dexs = await hl_info(s, {"type": "perpDexs"})
        arcus = {a.base: a for a in parse_arcus(markets, fees)}
        a_raw = {m["baseAsset"].upper(): m for m in markets["markets"]}
        io = [h for h in parse_hl(io_raw, dex=ENTROPY_DEX) if h.base in arcus]
        io_uni = {u["name"]: (u, c) for u, c in zip(io_raw[0]["universe"], io_raw[1])}
        cands = []
        for h in io:
            if h.is_delisted:
                continue
            am = a_raw[h.base]
            a_vol = D(str(am.get("volume24hNotional") or "0"))
            cands.append({"symbol": h.base, "coin": h.coin, "arcus_vol24h_usd": a_vol,
                          "hl_vol24h_usd": h.day_ntl_vlm or Decimal(0),
                          "min_vol24h_usd": min(a_vol, h.day_ntl_vlm or Decimal(0))})
        books: dict[str, Any] = {}
        need = cands if args.rank == "depth" else sorted(cands, key=lambda c: c["min_vol24h_usd"], reverse=True)[:args.top]
        for c in need:
            ab = await get_json(s, f"{ARCUS_REST}/v1/l2OrderBook/{c['symbol']}-USD", params={"nLevels": "50"})
            hb = await hl_info(s, {"type": "l2Book", "coin": c["coin"]})
            books[c["symbol"]] = {
                "arcus": book_stats([(D(p), D(q)) for p, q in ab["bids"]], [(D(p), D(q)) for p, q in ab["asks"]]),
                "hl": book_stats([(D(x["px"]), D(x["sz"])) for x in hb["levels"][0]],
                                 [(D(x["px"]), D(x["sz"])) for x in hb["levels"][1]])}
    for c in cands:
        b = books.get(c["symbol"])
        if b and b["arcus"]["depth10_bid_usd"] is not None and b["hl"]["depth10_bid_usd"] is not None:
            c["min_depth10_usd"] = min(b["arcus"]["depth10_bid_usd"], b["arcus"]["depth10_ask_usd"],
                                       b["hl"]["depth10_bid_usd"], b["hl"]["depth10_ask_usd"])
    key = (lambda c: c.get("min_depth10_usd") or Decimal(0)) if args.rank == "depth" else (lambda c: c["min_vol24h_usd"])
    ranked = sorted(cands, key=key, reverse=True)
    picks = []
    hl_by = {h.coin: h for h in io}
    for c in ranked[:args.top]:
        h, a, am = hl_by[c["coin"]], arcus[c["symbol"]], a_raw[c["symbol"]]
        u, ctx = io_uni[c["coin"]]
        fa = a.next_funding_hourly if a.next_funding_hourly is not None else a.funding_hourly
        fh = h.funding_hourly
        picks.append(c | {
            "io": {"maker_fee": h.maker_fee, "taker_fee": h.taker_fee, "maker_bps": h.maker_fee * BPS,
                   "taker_bps": h.taker_fee * BPS, "growth_mode": h.growth_mode, "deployerFeeScale": h.deployer_fee_scale,
                   "marginMode_raw": u.get("marginMode"), "onlyIsolated_raw": u.get("onlyIsolated"),
                   "margin_mode": h.margin_mode, "strictIsolated": h.margin_mode == "strictIsolated",
                   "max_leverage": h.max_leverage, "min_notional_usd": h.min_notional,
                   "min_notional_note": "TODO: VERIFY_FROM_DOCS ($10 commonly observed; not on the docs pages)",
                   "step": h.step, "funding_hourly": fh, "oraclePx": ctx.get("oraclePx"), "markPx": ctx.get("markPx"),
                   "premium": ctx.get("premium")},
            "arcus": {"maker_bps": a.maker_fee * BPS, "taker_bps": a.taker_fee * BPS, "max_leverage": a.max_leverage,
                      "off_hours_max_leverage": (1 / D(str(am["offHoursInitialMarginFraction"])))
                      if am.get("offHoursInitialMarginFraction") else None,
                      "min_notional_usd": a.min_notional, "step": a.step, "funding_hourly_next": a.next_funding_hourly,
                      "funding_hourly_last": a.funding_hourly, "isOutsideRth": am.get("isOutsideRth"),
                      "regularTradingHours": am.get("regularTradingHours"), "oraclePrice": am.get("oraclePrice"),
                      "markPrice": am.get("markPrice"), "category": am.get("category")},
            "funding_diff_annual_hl_minus_arcus": (fh - fa) * HOURS_PER_YEAR if fh is not None and fa is not None else None,
            "books": books.get(c["symbol"]),
        })
    io_dex = next((d for d in dexs if isinstance(d, dict) and d.get("name") == ENTROPY_DEX), None)
    rep = {"probed_at_ms": t0, "rank_by": args.rank, "candidates": len(cands),
           "io_dex": {k: io_dex.get(k) for k in ("name", "fullName", "deployer")} if io_dex else None,
           "io_collateralToken": io_raw[0].get("collateralToken"), "ranked": ranked, "top": picks}
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "rwa_overlap_probe.json").write_text(dumps(rep))
    L = [f"# Arcus ∩ Entropy io — top {args.top} by {args.rank} (probed at epoch ms {t0})", "",
         f"Non-delisted overlaps: {len(cands)}. io collateralToken index: {rep['io_collateralToken']}.", "",
         "| # | Symbol | io coin | min 24h vol $ (Arcus / HL) | io maker/taker bps | growth mode | io margin mode "
         "(strictIsolated?) | io max lev | io min notional $ | Arcus maker/taker bps | Arcus max lev (RTH / off-hours) | "
         "Arcus min notional $ | Arcus funding 1h (next) | HL funding 1h | Δ ann. HL−Arcus | Arcus spread bps | "
         "HL spread bps | ±10 bps depth $ min(A,HL) | Arcus outside RTH |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, p in enumerate(picks, 1):
        b = p["books"] or {"arcus": {}, "hl": {}}
        L.append(f"| {i} | {p['symbol']} | {p['coin']} | {fmt(p['arcus_vol24h_usd'], 0)} / {fmt(p['hl_vol24h_usd'], 0)} | "
                 f"{fmt(p['io']['maker_bps'], 2)} / {fmt(p['io']['taker_bps'], 2)} | {p['io']['growth_mode']} | "
                 f"{p['io']['margin_mode']} ({p['io']['strictIsolated']}) | {p['io']['max_leverage']} | "
                 f"{p['io']['min_notional_usd']}* | {fmt(p['arcus']['maker_bps'], 2)} / {fmt(p['arcus']['taker_bps'], 2)} | "
                 f"{fmt(p['arcus']['max_leverage'], 1)} / {fmt(p['arcus']['off_hours_max_leverage'], 1)} | "
                 f"{p['arcus']['min_notional_usd']} | {fmt(p['arcus']['funding_hourly_next'], 10)} | "
                 f"{fmt(p['io']['funding_hourly'], 10)} | {fmt(p['funding_diff_annual_hl_minus_arcus'], 4)} | "
                 f"{fmt(b['arcus'].get('spread_bps'), 2)} | {fmt(b['hl'].get('spread_bps'), 2)} | "
                 f"{fmt(p.get('min_depth10_usd'), 0)} | {p['arcus']['isOutsideRth']} |")
    L += ["", "\\* HL min notional: TODO: VERIFY_FROM_DOCS.", "",
          "Ranking (all non-delisted overlaps, min 24h notional $): " +
          ", ".join(f"{c['symbol']} {fmt(c['min_vol24h_usd'], 0)}" for c in ranked)]
    text = "\n".join(L) + "\n"
    (out / "rwa_overlap_probe.md").write_text(text)
    print(text)
    print("PAIRS: " + " ".join(f"--pair {p['symbol']}={p['coin']}" for p in picks))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
