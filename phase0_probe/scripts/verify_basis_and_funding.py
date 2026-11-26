"""PR #1.5 item 1 — raw oracle / mark / mid / funding check for BTC, ETH, SOL on Arcus and Hyperliquid (READ-ONLY).

Usage: uv run python scripts/verify_basis_and_funding.py [--samples 5] [--every-s 3] [--out reports]

Prints the RAW JSON of every source (first sample) and writes reports/basis_funding_check.{json,md}:
a) basis decomposition (bps of the Arcus oracle):
     oracle_diff      = HL_oracle − Arcus_oracle
     book_premium_diff = (HL_mid − HL_oracle) − (Arcus_mid − Arcus_oracle)
     mid_diff          = HL_mid − Arcus_mid  (= the sum of the two, exactly)
b) funding conversion step by step (raw value, interval, fraction vs percent, sign, annualisation) and a numeric
   proof that HL ``fundingHistory.fundingRate`` = (P + clamp(0.0001 − P, ±0.0005)) / 8, i.e. an HOURLY fraction.
Sources: Arcus GET /v1/markets, /v1/l2OrderBook/{market}, /v1/fundingRates; HL POST /info metaAndAssetCtxs,
l2Book, predictedFundings, fundingHistory. Mids come from the L2 books (best bid/ask); the last trade price is unused.
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

from phase0_probe.dec import D, HOURS_PER_YEAR, dumps, fmt, now_ms  # noqa: E402
from phase0_probe.funding import decompose_basis, hl_hourly_from_premium  # noqa: E402
from phase0_probe.venues import ARCUS_REST, get_json, hl_info  # noqa: E402

SYMS = ["BTC", "ETH", "SOL"]
DOCS = {
    "arcus_markets": "https://docs.arcus.xyz/api-reference/public/get-markets.md",
    "arcus_funding_rates": "https://docs.arcus.xyz/api-reference/public/get-market-funding-rates.md",
    "arcus_funding_concept": "https://docs.arcus.xyz/concepts/perpetuals/funding.md",
    "arcus_prices": "https://docs.arcus.xyz/concepts/perpetuals/prices.md",
    "hl_funding": "https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding.md",
    "hl_perp_info": "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals.md",
    "hl_contract_specs": "https://hyperliquid.gitbook.io/hyperliquid-docs/trading/contract-specifications.md",
    "hl_oracle": "https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/oracle.md",
    "usdt_usd_cross_check (third-party, NOT a venue doc)": "https://api.kraken.com/0/public/Ticker?pair=USDTZUSD",
}
KRAKEN_USDT = "https://api.kraken.com/0/public/Ticker"


async def usdt_usd(sess: aiohttp.ClientSession) -> dict[str, Any] | None:
    """Third-party USDT/USD mid (Kraken public ticker) -> implied bps of a USDT-quoted price over a USD-quoted one:
    (1/mid − 1) × 10_000. HL oracles are USDT-denominated (contract-specifications.md); Arcus quotes USD (Pyth)."""
    try:
        body = await get_json(sess, KRAKEN_USDT, params={"pair": "USDTZUSD"})
        t = body["result"]["USDTZUSD"]
        mid = (D(t["a"][0]) + D(t["b"][0])) / 2
        return {"raw": {"a": t["a"][0], "b": t["b"][0]}, "mid": mid, "implied_usdt_premium_bps": (1 / mid - 1) * 10_000}
    except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, ValueError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def mid_of(bids: list[Any], asks: list[Any]) -> Decimal:
    return (bids[0] + asks[0]) / 2


async def sample(sess: aiohttp.ClientSession) -> dict[str, Any]:
    t0 = now_ms()
    calls = [get_json(sess, f"{ARCUS_REST}/v1/markets"), hl_info(sess, {"type": "metaAndAssetCtxs"})]
    calls += [get_json(sess, f"{ARCUS_REST}/v1/l2OrderBook/{s}-USD", params={"nLevels": "5"}) for s in SYMS]
    calls += [hl_info(sess, {"type": "l2Book", "coin": s}) for s in SYMS]
    res = await asyncio.gather(*calls)
    t1 = now_ms()
    markets, meta = res[0], res[1]
    a_books, h_books = res[2:5], res[5:8]
    names = [u["name"] for u in meta[0]["universe"]]
    out: dict[str, Any] = {"t_start_ms": t0, "t_end_ms": t1, "symbols": {}, "usdt_usd": await usdt_usd(sess)}
    for i, s in enumerate(SYMS):
        am = next(m for m in markets["markets"] if m["marketDisplayName"] == f"{s}-USD")
        j = names.index(s)
        ctx, uni = meta[1][j], meta[0]["universe"][j]
        ab, hb = a_books[i], h_books[i]
        a_mid = mid_of([D(ab["bids"][0][0])], [D(ab["asks"][0][0])])
        h_mid = mid_of([D(hb["levels"][0][0]["px"])], [D(hb["levels"][1][0]["px"])])
        raw_a = {k: am.get(k) for k in ("marketDisplayName", "oraclePrice", "markPrice", "fundingRate",
                                         "nextFundingRate", "nextFundingAt", "category", "isOutsideRth",
                                         "regularTradingHours", "currentSettlementPrice")}
        out["symbols"][s] = {
            "raw": {"arcus_market": raw_a, "arcus_l2_top": {"bids": ab["bids"][:1], "asks": ab["asks"][:1],
                                                            "timestamp_us": ab.get("timestamp"),
                                                            "lastSequenceId": ab.get("lastSequenceId")},
                    "hl_universe": uni, "hl_ctx": ctx,
                    "hl_l2_top": {"bid": hb["levels"][0][0], "ask": hb["levels"][1][0], "time": hb.get("time")}},
            "arcus": {"oracle": D(am["oraclePrice"]), "mark": D(am["markPrice"]), "mid": a_mid},
            "hl": {"oracle": D(ctx["oraclePx"]), "mark": D(ctx["markPx"]), "mid": h_mid,
                   "ctx_midPx": D(ctx["midPx"]) if ctx.get("midPx") else None},
        }
        d = decompose_basis(D(am["oraclePrice"]), a_mid, D(ctx["oraclePx"]), h_mid)
        out["symbols"][s]["decomposition"] = d.__dict__
    return out


async def funding_inputs(sess: aiohttp.ClientSession) -> dict[str, Any]:
    end = now_ms()
    pred = await hl_info(sess, {"type": "predictedFundings"})
    out: dict[str, Any] = {"predictedFundings_raw": [c for c in pred if c[0] in SYMS], "symbols": {}}
    for s in SYMS:
        hist = await hl_info(sess, {"type": "fundingHistory", "coin": s, "startTime": end - 6 * 3_600_000})
        ar = await get_json(sess, f"{ARCUS_REST}/v1/fundingRates", params={"market": f"{s}-USD", "limit": "6"})
        out["symbols"][s] = {"hl_fundingHistory_raw": hist, "arcus_fundingRates_raw": ar}
    return out


def funding_steps(s: str, first: dict[str, Any], fin: dict[str, Any]) -> dict[str, Any]:
    am, ctx = first["raw"]["arcus_market"], first["raw"]["hl_ctx"]
    hlp = next((v for c, vs in fin["predictedFundings_raw"] if c == s for n, v in vs if n == "HlPerp"), None)
    a_next, a_cur = D(am["nextFundingRate"]), D(am["fundingRate"])
    h_ctx = D(ctx["funding"])
    h_pred = D(hlp["fundingRate"]) / D(hlp["fundingIntervalHours"]) if hlp else None
    hist = fin["symbols"][s]["hl_fundingHistory_raw"]
    checks = []
    for h in hist:
        calc = hl_hourly_from_premium(D(h["premium"]))
        checks.append({"time": h["time"], "premium": h["premium"], "fundingRate": h["fundingRate"],
                       "recomputed_hourly": format(calc, "f"),
                       "abs_err": format(abs(calc - D(h["fundingRate"])), "f")})
    a_hist = fin["symbols"][s]["arcus_fundingRates_raw"]["fundingRates"]
    h_last = {int(h["time"]) // 3_600_000: D(h["fundingRate"]) for h in hist}
    realized = []
    for a in a_hist:
        hr = int(a["time"]) // 3_600_000_000
        if hr in h_last:
            realized.append({"hour_ms": hr * 3_600_000, "arcus": a["fundingRate"], "hl": format(h_last[hr], "f"),
                             "hl_minus_arcus_annual": format((h_last[hr] - D(a["fundingRate"])) * HOURS_PER_YEAR, "f")})
    use_h = h_pred if h_pred is not None else h_ctx
    return {
        "arcus": {"raw_fundingRate": am["fundingRate"], "raw_nextFundingRate": am["nextFundingRate"],
                  "nextFundingAt_s": am["nextFundingAt"], "interval": "1 h (charged once an hour)",
                  "unit": "decimal fraction per hour (schema: 'Hourly funding rate (decimal string)')",
                  "percent_per_hour": a_next * 100, "annualized_fraction": a_next * HOURS_PER_YEAR,
                  "annualized_current_fraction": a_cur * HOURS_PER_YEAR, "sign": "positive => longs pay shorts"},
        "hl": {"raw_ctx_funding": ctx["funding"], "raw_ctx_premium": ctx.get("premium"),
               "raw_predicted_HlPerp": hlp, "predicted_hourly": h_pred, "interval": "1 h (8 h formula / 8)",
               "unit": "decimal fraction per hour", "percent_per_hour": use_h * 100,
               "annualized_fraction": use_h * HOURS_PER_YEAR, "annualized_ctx_fraction": h_ctx * HOURS_PER_YEAR,
               "sign": "positive => longs pay shorts", "formula_check_last_hours": checks},
        "hl_minus_arcus_annual_forecast": (use_h - a_next) * HOURS_PER_YEAR,
        "carry_short_arcus_long_hl_annual_forecast": (a_next - use_h) * HOURS_PER_YEAR,
        "realized_last_hours": realized,
    }


def md(rep: dict[str, Any]) -> str:
    L = ["# Basis & funding verification (PR #1.5, read-only)", "",
         f"Samples: {len(rep['samples'])}, local epoch ms {rep['samples'][0]['t_start_ms']} → "
         f"{rep['samples'][-1]['t_end_ms']}. All bps are relative to the Arcus oracle.", "",
         "## a) Where does the HL − Arcus mid premium come from?", "",
         "| Symbol | Arcus oracle | Arcus mid | HL oracle | HL mid | oracle diff bps (median) | book-premium diff bps "
         "(median) | mid diff bps (median) | HL mid−oracle bps | Arcus mid−oracle bps |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for s in SYMS:
        f = rep["samples"][-1]["symbols"][s]
        agg = rep["aggregate"][s]
        L.append(f"| {s} | {f['arcus']['oracle']} | {fmt(f['arcus']['mid'], 2)} | {f['hl']['oracle']} | "
                 f"{fmt(f['hl']['mid'], 2)} | {fmt(agg['oracle_diff_bps'], 3)} | {fmt(agg['book_premium_diff_bps'], 3)} | "
                 f"{fmt(agg['mid_diff_bps'], 3)} | {fmt(agg['hl_premium_bps'], 3)} | {fmt(agg['arcus_premium_bps'], 3)} |")
    u = [x["usdt_usd"] for x in rep["samples"] if x.get("usdt_usd") and "mid" in x["usdt_usd"]]
    if u:
        L += ["", f"USDT/USD cross-check (Kraken public ticker, third-party): mid {u[-1]['mid']} → a USDT-quoted price "
                  f"sits **{fmt(u[-1]['implied_usdt_premium_bps'], 3)} bps** above a USD-quoted one. HL oracles are "
                  "USDT-denominated (contract-specifications.md); Arcus oracles are Pyth USD (prices.md)."]
    L += ["", "## b) Funding conversion (step by step)", ""]
    for s in SYMS:
        f = rep["funding"][s]
        a, h = f["arcus"], f["hl"]
        L += [f"### {s}", "",
              f"* Arcus raw `nextFundingRate` = `{a['raw_nextFundingRate']}` (`fundingRate` last applied = "
              f"`{a['raw_fundingRate']}`), {a['unit']}; {a['interval']} → {fmt(a['percent_per_hour'], 6)} %/h → "
              f"×8760 = **{fmt(a['annualized_fraction'] * 100, 3)} %/yr**. Sign: {a['sign']}.",
              f"* HL raw ctx `funding` = `{h['raw_ctx_funding']}`, predictedFundings HlPerp = `{h['raw_predicted_HlPerp']}`"
              f" → hourly {fmt(h['predicted_hourly'], 10)}; {h['unit']}; {h['interval']} → "
              f"{fmt(h['percent_per_hour'], 6)} %/h → ×8760 = **{fmt(h['annualized_fraction'] * 100, 3)} %/yr**. "
              f"Sign: {h['sign']}.",
              f"* HL − Arcus (forecast) = **{fmt(f['hl_minus_arcus_annual_forecast'] * 100, 3)} %/yr** ⇒ short Arcus + "
              f"long HL carry = **{fmt(f['carry_short_arcus_long_hl_annual_forecast'] * 100, 3)} %/yr**.",
              "* HL formula check (fundingHistory, last hours): " + ", ".join(
                  f"P={c['premium']} → {c['recomputed_hourly']} vs {c['fundingRate']} (err {c['abs_err']})"
                  for c in h["formula_check_last_hours"][-3:]),
              "* Realized (both venues, same hour): " + ", ".join(
                  f"{r['hour_ms']}: A {r['arcus']} / HL {r['hl']} → Δann {fmt(D(r['hl_minus_arcus_annual']) * 100, 2)} %"
                  for r in f["realized_last_hours"][:4]), ""]
    L += ["## Docs", ""] + [f"* {k}: {v}" for k, v in DOCS.items()]
    return "\n".join(L) + "\n"


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--every-s", type=int, default=3)
    ap.add_argument("--out", default="reports")
    args = ap.parse_args(argv)
    samples = []
    async with aiohttp.ClientSession() as sess:
        for i in range(args.samples):
            samples.append(await sample(sess))
            if i == 0:
                print("=== RAW (first sample) ===")
                for s in SYMS:
                    print(f"--- {s} ---")
                    print(dumps(samples[0]["symbols"][s]["raw"]))
            if i + 1 < args.samples:
                await asyncio.sleep(args.every_s)
        fin = await funding_inputs(sess)
    print("=== RAW predictedFundings (HL) ===")
    print(dumps(fin["predictedFundings_raw"]))
    for s in SYMS:
        print(f"=== RAW funding history {s} (HL fundingHistory last 6 h, Arcus /v1/fundingRates limit 6) ===")
        print(dumps(fin["symbols"][s]))
    agg: dict[str, Any] = {}
    for s in SYMS:
        agg[s] = {}
        for k in ("oracle_diff_bps", "book_premium_diff_bps", "mid_diff_bps", "hl_premium_bps", "arcus_premium_bps"):
            vals = sorted(x["symbols"][s]["decomposition"][k] for x in samples)
            n = len(vals)
            agg[s][k] = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
            agg[s][k + "_min"], agg[s][k + "_max"] = vals[0], vals[-1]
    rep = {"docs": DOCS, "samples": samples, "aggregate": agg,
           "funding": {s: funding_steps(s, samples[0]["symbols"][s], fin) for s in SYMS}, "raw_funding": fin}
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "basis_funding_check.json").write_text(dumps(rep))
    text = md(rep)
    (out / "basis_funding_check.md").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
