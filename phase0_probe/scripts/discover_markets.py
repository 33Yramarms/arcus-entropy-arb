"""Phase 0 metadata + fee discovery (PUBLIC, READ-ONLY): Arcus perps vs Hyperliquid core + Entropy HIP-3 dex 'io'.

Writes reports/overlap_markets.json and reports/overlap_markets.md (plus raw responses under reports/raw/).
Usage: uv run python scripts/discover_markets.py [--out reports]
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

from phase0_probe.dec import dumps, fmt, now_ms  # noqa: E402
from phase0_probe.discovery import overlap, parse_arcus, parse_hl, parse_predicted  # noqa: E402
from phase0_probe.venues import ARCUS_REST, ENTROPY_DEX, get_json, hl_info  # noqa: E402

BPS = Decimal(10_000)


async def fetch(out: pathlib.Path) -> dict[str, Any]:
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    async with aiohttp.ClientSession() as s:
        markets, fee_sched, fee_tiers, dexs, core, io, predicted = await asyncio.gather(
            get_json(s, f"{ARCUS_REST}/v1/markets"),
            get_json(s, f"{ARCUS_REST}/v1/markets/feeSchedules"),
            get_json(s, f"{ARCUS_REST}/v1/feetiers"),
            hl_info(s, {"type": "perpDexs"}),
            hl_info(s, {"type": "metaAndAssetCtxs"}),
            hl_info(s, {"type": "metaAndAssetCtxs", "dex": ENTROPY_DEX}),
            hl_info(s, {"type": "predictedFundings"}))
    for name, body in (("arcus_markets", markets), ("arcus_fee_schedules", fee_sched), ("arcus_feetiers", fee_tiers),
                       ("hl_perp_dexs", dexs), ("hl_core_meta_ctxs", core), ("hl_io_meta_ctxs", io),
                       ("hl_predicted_fundings", predicted)):
        (raw / f"{name}.json").write_text(dumps(body))
    return dict(markets=markets, fee_sched=fee_sched, fee_tiers=fee_tiers, dexs=dexs, core=core, io=io,
                predicted=predicted)


def build(src: dict[str, Any]) -> dict[str, Any]:
    arcus = parse_arcus(src["markets"], src["fee_sched"])
    pred = parse_predicted(src["predicted"])
    hl_core = parse_hl(src["core"], dex="", predicted=pred)
    hl_io = parse_hl(src["io"], dex=ENTROPY_DEX)
    io_dex = next((d for d in src["dexs"] if d and d.get("name") == ENTROPY_DEX), None)
    rows = overlap(arcus, hl_core + hl_io)
    io_bases = {h.base for h in hl_io}
    notes = []
    for sym in ("BTC", "ETH", "SOL"):
        if sym not in io_bases:
            notes.append(f"Entropy dex 'io' does NOT list {sym}; {sym} overlap uses Hyperliquid core (dex \"\").")
    return {
        "generated_ms": now_ms(),
        "sources": {
            "arcus_markets": "GET https://api.arcus.xyz/v1/markets",
            "arcus_fee_schedules": "GET https://api.arcus.xyz/v1/markets/feeSchedules",
            "arcus_fee_tiers": "GET https://api.arcus.xyz/v1/feetiers",
            "hl": "POST https://api.hyperliquid.xyz/info {perpDexs | metaAndAssetCtxs [dex] | predictedFundings}",
        },
        "entropy_dex": io_dex and {k: io_dex.get(k) for k in ("name", "fullName", "deployer")},
        "counts": {"arcus_perps": len(arcus), "hl_core": len(hl_core), "hl_io": len(hl_io), "overlaps": len(rows)},
        "notes": notes,
        "overlaps": rows,
    }


def markdown(rep: dict[str, Any]) -> str:
    L = ["# Arcus × Hyperliquid overlap (Phase 0, read-only)", "",
         f"Generated (epoch ms): {rep['generated_ms']}. Fees = tier 0 / base rate (worst case, no discounts). "
         "Funding = hourly rate; annualised = ×8760. HL funding uses `predictedFundings` (HlPerp) when available "
         "else the asset ctx `funding`; Arcus uses `nextFundingRate` (forecast) else `fundingRate`.", ""]
    for n in rep["notes"]:
        L.append(f"* {n}")
    L += ["", "| Symbol | HL venue | HL coin | Arcus step | HL step | Arcus min notional | HL min notional* | "
          "Arcus maker/taker bps | HL maker/taker bps | Arcus funding 1h | HL funding 1h | HL margin | HL max lev | "
          "Arcus max lev | Δfunding ann. (HL−Arcus) |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rep["overlaps"]:
        a, h = r["arcus"], r["hl"]
        fa = a["next_funding_hourly"] if a["next_funding_hourly"] is not None else a["funding_hourly"]
        fh = h["predicted_hourly"] if h["predicted_hourly"] is not None else h["funding_hourly"]
        L.append("| " + " | ".join([
            ("**" + r["symbol"] + "**") if r["priority"] else r["symbol"], r["hl_venue"], h["coin"],
            format(a["step"], "f"), format(h["step"], "f"), format(a["min_notional"], "f"),
            format(h["min_notional"], "f"),
            f"{fmt(a['maker_fee'] * BPS, 2)}/{fmt(a['taker_fee'] * BPS, 2)}",
            f"{fmt(h['maker_fee'] * BPS, 2)}/{fmt(h['taker_fee'] * BPS, 2)}",
            fmt(fa, 8), fmt(fh, 8), h["margin_mode"] + (" (delisted)" if h["is_delisted"] else ""),
            str(h["max_leverage"]), fmt(a["max_leverage"], 1),
            fmt(r["funding_diff_annual_hl_minus_arcus"], 4)]) + " |")
    L += ["", "\\* HL minimum order value: TODO: VERIFY_FROM_DOCS (not on the fee / tick-and-lot-size pages).",
          "Arcus margin mode is chosen per account+market (CROSS/ISOLATED, docs concepts/perpetuals/margin-modes.md); "
          "max leverage = 1 / initialMarginFraction."]
    return "\n".join(L) + "\n"


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports")
    args = ap.parse_args(argv)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rep = build(await fetch(out))
    (out / "overlap_markets.json").write_text(dumps(rep))
    (out / "overlap_markets.md").write_text(markdown(rep))
    print(f"overlaps={rep['counts']['overlaps']} -> {out}/overlap_markets.json, {out}/overlap_markets.md")
    for n in rep["notes"]:
        print(n)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
