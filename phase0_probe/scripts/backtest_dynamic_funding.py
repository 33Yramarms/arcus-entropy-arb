"""PR #1.7 — offline back-test of dynamic funding-differential strategies on the 10 Arcus ∩ Entropy (HL dex "io")
US-equity perps (READ-ONLY, zero keys, Decimal only; no order or key-handling code). Logic: src/phase0_probe/backtest.py.

Usage:
  uv run python scripts/backtest_dynamic_funding.py                  # fetch 30 d hourly history live, write cache, run
  uv run python scripts/backtest_dynamic_funding.py --from-cache     # fully offline, reproducible (reports/*.json)
  uv run python scripts/backtest_dynamic_funding.py --from-pr16-report reports/rwa_funding_basis.json   # PR #1.6 data

Data sources (public, documented; fetchers reused from scripts/analyze_rwa_funding_and_basis.py):
* Arcus GET /v1/fundingRates?market=XXX-USD (µs timestamps, hourly decimal ``fundingRate``), GET /v1/markets
  (``offHoursInitialMarginFraction``, ``initialMarginFraction``), GET /v1/markets/feeSchedules.
* HL POST /info {"type":"fundingHistory","coin":"io:XXX"} (hourly ``fundingRate``), metaAndAssetCtxs {"dex":"io"}
  (``maxLeverage``).
Only hours present on BOTH venues are used (``align_hourly``).
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import pathlib
import sys
from decimal import Decimal
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from phase0_probe.backtest import (COST_TIERS, EXIT_GRID, ENTRY_GRID, K_GRID, MARGIN_BUFFER,  # noqa: E402
                                   arcus_pin_diagnostic, best, grid, margin_per_notional, run_grid, split_halves)
from phase0_probe.dec import BPS, D, dumps, fmt, loads, now_ms  # noqa: E402
from phase0_probe.funding import align_hourly  # noqa: E402
from phase0_probe.sessions import to_et  # noqa: E402

SYMBOLS = ("NVDA", "SNDK", "MU", "DRAM", "NBIS", "AAPL", "CRCL", "GOOGL", "META", "INTC")
DEFAULT_CACHE = ROOT / "reports" / "backtest_funding_cache.json"
HOUR_MS = 3_600_000
CONS, OPT = "conservative_8.3bps", "optimistic_2.8bps"


def _load_rwa_module() -> Any:
    spec = importlib.util.spec_from_file_location("analyze_rwa_funding_and_basis",
                                                  ROOT / "scripts" / "analyze_rwa_funding_and_basis.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


async def fetch_cache(days: int) -> dict[str, Any]:
    import aiohttp
    rwa = _load_rwa_module()
    t0 = now_ms()
    end = t0 // HOUR_MS * HOUR_MS + 60_000
    start = end - days * 24 * HOUR_MS
    out: dict[str, Any] = {"generated_ms": t0, "generated_et": to_et(t0).isoformat(), "days": days,
                           "start_ms": start, "end_ms": end, "source": "live", "symbols": {}}
    async with aiohttp.ClientSession() as sess:
        disc = await rwa.discover(sess)
        for s in SYMBOLS:
            if s not in disc["io"] or s not in disc["a_raw"]:
                out["symbols"][s] = {"error": "not in Arcus ∩ io overlap at fetch time"}
                continue
            am, h = disc["a_raw"][s], disc["io"][s]
            a_rows = await rwa.arcus_history(sess, f"{s}-USD", start, end)
            h_rows = await rwa.hl_history(sess, h.coin, start, end)
            out["symbols"][s] = {
                "arcus_market": f"{s}-USD", "io_coin": h.coin,
                "arcus_initialMarginFraction": D(str(am["initialMarginFraction"])),
                "arcus_offHoursInitialMarginFraction": D(str(am["offHoursInitialMarginFraction"])),
                "io_maxLeverage": D(h.max_leverage),
                "arcus_raw": [[t, r] for t, r in a_rows], "hl_raw": [[t, r] for t, r in h_rows]}
            await asyncio.sleep(1)
    return out


def cache_from_pr16(path: pathlib.Path) -> dict[str, Any]:
    rep = loads(path.read_text())
    out: dict[str, Any] = {"generated_ms": rep["generated_ms"], "generated_et": rep["generated_et"], "days": 30,
                           "source": f"pr16_report:{path.name}", "symbols": {}}
    for s in SYMBOLS:
        fm, rows = rep["fees_margin"][s], rep["hourly_30d"][s]
        out["symbols"][s] = {
            "arcus_market": fm["arcus"]["market"], "io_coin": fm["io"]["coin"],
            "arcus_initialMarginFraction": D(fm["arcus"]["initialMarginFraction"]),
            "arcus_offHoursInitialMarginFraction": D(fm["arcus"]["offHoursInitialMarginFraction"]),
            "io_maxLeverage": D(fm["io"]["maxLeverage"]),
            "arcus_raw": [[r["hour_ms"], D(r["arcus"])] for r in rows],
            "hl_raw": [[r["hour_ms"], D(r["hl"])] for r in rows]}
    return out


def prepare(cache: dict[str, Any]) -> tuple[dict[str, list[tuple[int, Decimal, Decimal]]], dict[str, Any]]:
    data, cap = {}, {}
    for s, v in cache["symbols"].items():
        if "error" in v:
            continue
        a = [(int(t), D(r)) for t, r in v["arcus_raw"]]
        h = [(int(t), D(r)) for t, r in v["hl_raw"]]
        rows = align_hourly(a, h)
        if "start_ms" in cache:
            rows = [x for x in rows if x[0] >= cache["start_ms"]]
        data[s] = rows
        cap[s] = margin_per_notional(D(v["arcus_offHoursInitialMarginFraction"]), D(v["io_maxLeverage"]))
    return data, cap


def gaps(rows: list[tuple[int, Decimal, Decimal]]) -> list[dict[str, Any]]:
    return [{"after_et": to_et(a[0]).isoformat(), "missing_h": (b[0] - a[0]) // HOUR_MS - 1}
            for a, b in zip(rows, rows[1:]) if b[0] - a[0] != HOUR_MS]


def P(x: Decimal | None, n: int = 2) -> str:
    return fmt(x, n)


def md(rep: dict[str, Any]) -> str:
    L: list[str] = []
    a = L.append
    a("# PR #1.7 — dynamic funding-differential back-test (Arcus × io, 10 US-equity perps)\n")
    a(f"Data: {rep['data_source']} · generated {rep['data_generated_et']} · aligned hourly payments only. "
      "Read-only, zero keys, Decimal only.\n")
    a("**Timing (no look-ahead):** decision for payment *i* uses realized diffs up to *i−1* only; a position opened at "
      "decision *i* earns payment *i* onward; closing at *i* forfeits payment *i*. Costs: half the round trip at open, "
      "half at close; open positions force-closed (with cost) at data end. Re-entry earliest one hour after a close.\n")
    a("**Exit_apr semantics:** direction-aware — close when `dir × rolling_apr ≤ exit_apr` (0 % = rolling crossed "
      "zero / turned against us), or when the last 2 hourly diffs are both against the position, or (B) at the "
      "window boundary, or on a data gap.\n")
    a("**Capital per $1 notional per leg** = Arcus off-hours IMF × 1.5 + (1 / io maxLeverage) × 1.5. "
      "ROE (annualized) = net / capital × 8760 / own-sample hours; portfolio = equal capital, always allocated "
      "(mean of symbol ROEs).\n")
    a("## Sample & capital\n")
    a("| Sym | aligned h | first (ET) | gaps | Arcus off IMF | io maxLev | capital / $1 notional | lev on capital |")
    a("|---|---|---|---|---|---|---|---|")
    for s, v in rep["symbols"].items():
        c = v["capital"]
        a(f"| {s} | {v['hours']} | {v['first_et'][:16]} | {sum(g['missing_h'] for g in v['gaps'])}h | "
          f"{P(v['arcus_off_imf'], 3)} | {P(v['io_max_leverage'], 0)} | {P(c['total'], 4)} | "
          f"{P(c['effective_leverage_on_capital'], 2)}× |")
    a("\nShort history (annualized over own sample, high variance): "
      + ", ".join(f"{s} {v['hours']}h" for s, v in rep["symbols"].items() if v["hours"] < 300) + "\n")
    a("## Arcus pin check (is Arcus funding really pinned in the off-hours window?)\n")
    a("| Sym | off-window h | Arcus mean / min / max APR % | distinct | io mean APR % (off) | Arcus mean APR % (in RTH window) |")
    a("|---|---|---|---|---|---|")
    for s, v in rep["symbols"].items():
        o, r = v["arcus_pin"]["off_hours_window"], v["arcus_pin"]["arcus_rth_window"]
        if not o.get("hours"):
            continue
        a(f"| {s} | {o['hours']} | {P(o['arcus_mean_apr_pct'])} / {P(o['arcus_min_apr_pct'])} / "
          f"{P(o['arcus_max_apr_pct'])} | {o['arcus_distinct_values']} | {P(o['hl_mean_apr_pct'])} | "
          f"{P(r.get('arcus_mean_apr_pct'))} |")
    for strat in ("A", "B"):
        for tier in (OPT, CONS):
            a(f"\n## Portfolio grid — strategy {strat}, {tier}\n")
            a("| K | entry | exit | opens | avg hold h | gross bps | cost bps | net bps | ROE ann % | +syms | worst trade bps |")
            a("|---|---|---|---|---|---|---|---|---|---|---|")
            for r in rep["results"]:
                if r["params"]["strategy"] != strat or r["cost_tier"] != tier:
                    continue
                p, q = r["params"], r["portfolio"]
                a(f"| {p['k']} | {P(p['entry_apr'] * 100, 0)}% | {P(p['exit_apr'] * 100, 0)}% | {q['opens']} | "
                  f"{P(q['avg_holding_h'], 1)} | {P(q['mean_gross_funding_bps'])} | {P(q['mean_total_cost_bps'])} | "
                  f"{P(q['mean_net_notional_bps'])} | {P(q['roe_annualized_pct_capital_always_allocated'])} | "
                  f"{q['symbols_net_positive']}/10 | {P(q['max_single_trade_loss_bps'])} |")
    a("\n## Best params (in-sample, by portfolio ROE)\n")
    for k, b in rep["best"].items():
        a(f"* {k}: {b['label']} → ROE {P(b['roe'])} %/yr, net {P(b['net_bps'])} bps (mean per symbol)")
    for strat in ("A", "B"):
        b = rep["best_results"][f"{strat}|{CONS}"]
        a(f"\n## Per symbol — best {strat} at conservative cost ({b['params']['label']})\n")
        a("| Sym | h | opens | avg hold h | gross bps | cost bps | net bps | ROE ann % | ROE while deployed % | max loss bps | closes by reason |")
        a("|---|---|---|---|---|---|---|---|---|---|---|")
        for s, m in b["per_symbol"].items():
            a(f"| {s} | {m['sample_hours']} | {m['opens']} | {P(m['avg_holding_h'], 1)} | {P(m['gross_funding_bps'])} | "
              f"{P(m['total_cost_bps'])} | {P(m['net_notional_bps'])} | {P(m['roe_annualized_pct'])} | "
              f"{P(m['roe_annualized_while_deployed_pct'])} | {P(m['max_single_trade_loss_bps'])} | "
              f"{', '.join(f'{k}:{v}' for k, v in sorted(m['close_reasons'].items()))} |")
    a("\n## Crude out-of-sample check (choose on first half, evaluate on second half, per symbol chronological 50/50)\n")
    a("| strategy / tier | chosen on 1st half | ROE 1st half % | same params ROE 2nd half % | best-in-hindsight 2nd half % |")
    a("|---|---|---|---|---|")
    for k, v in rep["oos"].items():
        a(f"| {k} | {v['label']} | {P(v['is_roe'])} | {P(v['oos_roe'])} | {P(v['oos_best_roe'])} ({v['oos_best_label']}) |")
    a("\n## Caveats\n")
    for c in rep["caveats"]:
        a(f"* {c}")
    return "\n".join(L) + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--from-cache", nargs="?", const=str(DEFAULT_CACHE), default=None)
    ap.add_argument("--from-pr16-report", default=None)
    ap.add_argument("--cache-out", default=str(DEFAULT_CACHE))
    ap.add_argument("--out", default="reports")
    ap.add_argument("--name", default="backtest_dynamic_funding")
    args = ap.parse_args(argv)
    if args.from_cache:
        cache = loads(pathlib.Path(args.from_cache).read_text())
    elif args.from_pr16_report:
        cache = cache_from_pr16(pathlib.Path(args.from_pr16_report))
    else:
        cache = asyncio.run(fetch_cache(args.days))
        pathlib.Path(args.cache_out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(args.cache_out).write_text(dumps(cache))
    data, cap = prepare(cache)
    results = run_grid(data, {s: c["total"] for s, c in cap.items()})
    best_res = {f"{s}|{t}": best(results, s, t) for s in ("A", "B") for t in COST_TIERS}
    first, second = split_halves(data)
    capt = {s: c["total"] for s, c in cap.items()}
    oos: dict[str, Any] = {}
    for s in ("A", "B"):
        for t, rt in COST_TIERS.items():
            ps = [p for p in grid() if p.strategy == s]
            r1 = run_grid(first, capt, ps, {t: rt})
            r2 = run_grid(second, capt, ps, {t: rt})
            b1, b2 = best(r1, s, t), best(r2, s, t)
            same = next(r for r in r2 if r["params"]["label"] == b1["params"]["label"])
            oos[f"{s} / {t}"] = {"label": b1["params"]["label"],
                                 "is_roe": b1["portfolio"]["roe_annualized_pct_capital_always_allocated"],
                                 "oos_roe": same["portfolio"]["roe_annualized_pct_capital_always_allocated"],
                                 "oos_best_label": b2["params"]["label"],
                                 "oos_best_roe": b2["portfolio"]["roe_annualized_pct_capital_always_allocated"]}
    syms = {}
    for s, rows in data.items():
        v = cache["symbols"][s]
        syms[s] = {"hours": len(rows), "first_et": to_et(rows[0][0]).isoformat(), "last_et": to_et(rows[-1][0]).isoformat(),
                   "gaps": gaps(rows), "arcus_off_imf": D(v["arcus_offHoursInitialMarginFraction"]),
                   "arcus_rth_imf": D(v["arcus_initialMarginFraction"]), "io_max_leverage": D(v["io_maxLeverage"]),
                   "capital": cap[s], "arcus_pin": arcus_pin_diagnostic(rows)}
    rep: dict[str, Any] = {
        "generated_ms": now_ms(), "data_source": cache.get("source"), "data_generated_et": cache.get("generated_et"),
        "grid": {"k": list(K_GRID), "entry_apr": list(ENTRY_GRID), "exit_apr": list(EXIT_GRID),
                 "cost_round_trip_bps": {k: v * BPS for k, v in COST_TIERS.items()}, "margin_buffer": MARGIN_BUFFER},
        "symbols": syms,
        "best": {k: {"label": b["params"]["label"], "roe": b["portfolio"]["roe_annualized_pct_capital_always_allocated"],
                     "net_bps": b["portfolio"]["mean_net_notional_bps"]} for k, b in best_res.items()},
        "best_results": best_res, "oos": oos, "results": results,
        "caveats": [
            "Best parameters are selected IN-SAMPLE on the same ≤30 days (16 combos × 2 strategies): expect the "
            "reported best ROE to be optimistic; see the 50/50 out-of-sample table.",
            "Short histories (GOOGL/MU/META/INTC) are annualized over their own few days — a handful of trades "
            "drives the number.",
            "Funding only: no price-basis P&L between the two legs (entry/exit basis, the ~10-17 bps oracle gap "
            "can move against you), no liquidation / ADL / margin-call risk, no funding of idle collateral.",
            "Costs are flat per-round-trip tiers (2.8 / 8.3 bps incl. slippage) — real slippage on io (thin "
            "books, $10 min notional TODO: VERIFY_FROM_DOCS) may exceed this at size.",
            "Arcus off-hours window = 20:00–04:00 ET + weekends + NYSE holidays (PR #1.6 calendar); whether Arcus "
            "shortens its window on early-close days is [待实测确认].",
            "HL hourly rate becomes known only at settlement; the strategy never uses the in-progress premium "
            "(conservative). Arcus' pinned off-hours rate is also NOT assumed known in advance.",
            "Break-even holding time at a constant differential = round trip / (APR / 8760): at 35 %/yr "
            f"{fmt(COST_TIERS[CONS] / (ENTRY_GRID[-1] / Decimal(8760)), 1)} h (8.3 bps) / "
            f"{fmt(COST_TIERS[OPT] / (ENTRY_GRID[-1] / Decimal(8760)), 1)} h (2.8 bps); at 12 %/yr "
            f"{fmt(COST_TIERS[CONS] / (ENTRY_GRID[0] / Decimal(8760)), 1)} h / "
            f"{fmt(COST_TIERS[OPT] / (ENTRY_GRID[0] / Decimal(8760)), 1)} h.",
            "Arcus pin check: inside the off-hours window Arcus is pinned at ~4.5 %/yr (SOFR + 0.5 %) on weekends, "
            "NYSE holidays and 21:00–03:00 ET stamps, but the weekday 04:00 ET stamp (accrual 03:00–04:00) is "
            "un-pinned in a minority of days (see pin table max/min) [待实测确认: Arcus stamp vs accrual convention].",
            "Data gaps (missing hour on either venue) force-close an open position with cost and are not credited.",
        ],
    }
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.name}.json").write_text(dumps(rep))
    text = md(rep)
    (out / f"{args.name}.md").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
