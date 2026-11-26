"""Summarise recorded snapshots: frequency of net>0 opportunities, average duration, annualised funding differential.

Usage: uv run python scripts/analyze_opportunity.py [--db reports/spreads.sqlite] [--window-h 24] [--out reports]
The window is the last ``--window-h`` hours of data (works for shorter recordings: it then covers all of it).
PR #1.6 Maker-Taker realism (``phase0_probe.realism``): ``--fill-window-s 5`` (signal window for the fill-through
filter), ``--fill-through`` (require a trade / opposite-side quote strictly THROUGH the maker price instead of
touching it). Adverse selection of the hedge leg at +1 / +3 / +5 s. Uses the ``trades`` table when the DB was
recorded with ``record_spreads.py --record-trades``; otherwise only the book-advance criterion is available.
"""
from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from phase0_probe.analysis import summarize  # noqa: E402
from phase0_probe.realism import maker_realism, side_consistency  # noqa: E402
from phase0_probe.dec import D, dumps, fmt  # noqa: E402


def markdown(rep: dict[str, Any], db: sqlite3.Connection, title: str = "") -> str:
    w = rep["window"]
    L = [f"# Opportunity summary (read-only){' — ' + title if title else ''}", "",
         f"Window: {w['from_ms']} → {w['to_ms']} epoch ms ({w['seconds']} s). Per second the better direction is "
         "taken. **net_resid** = open VWAP spread − close slippage − open+close fees − 2 bps buffer − the rolling "
         "median basis (exit assumed at the rolling median of HL−Arcus mid basis, not at 0). Gating: `not_ready` "
         "(either book unproven / resyncing) and `stale` (network latency > threshold or silent connection); book "
         "idleness never gates.", "",
         "| Symbol | Q $ | Mode | % s net_resid>0 | runs | avg dur s | max run s | max net_resid bps | "
         "median net_resid bps | % s net>0 (zero-conv., Phase 0) | median open spread bps | median basis bps | "
         "median abs residual bps | stale % | not_ready % | warm-up s | insuff. depth s |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        L.append("| " + " | ".join([r["symbol"], r["q_usd"], r["mode"], fmt(r["pct_net_pos"], 2), str(r["runs"]),
                                     fmt(r["avg_duration_s"], 2), str(r["max_run_s"]), fmt(r["max_net_bps"], 3),
                                     fmt(r["median_net_bps"], 3), fmt(r["pct_net_pos_zero_convergence"], 2),
                                     fmt(r["median_open_spread_bps"], 3), fmt(r["median_basis_bps"], 3),
                                     fmt(r["median_abs_residual_bps"], 3), fmt(r["pct_stale"], 2),
                                     fmt(r["pct_not_ready"], 2), str(r["warmup_seconds"]),
                                     str(r["insufficient_depth_seconds"])]) + " |")
    L += ["", "## Funding (hourly rates, window means; predicted if available else current)", "",
          "| Symbol | Arcus 1h | HL 1h | Arcus ann. | HL ann. | Δ ann. (HL−Arcus) | samples |", "|---|---|---|---|---|---|---|"]
    for sym, f in rep["funding"].items():
        L.append(f"| {sym} | {fmt(f['arcus_hourly_mean'], 8)} | {fmt(f['hl_hourly_mean'], 8)} | "
                 f"{fmt(f['arcus_annual_mean'], 4)} | {fmt(f['hl_annual_mean'], 4)} | "
                 f"{fmt(f['diff_annual_hl_minus_arcus'], 4)} | {f['samples']} |")
    L += ["", "Δ = HL − Arcus. Positive: long Arcus / short HL receives carry; negative: short Arcus / long HL receives.",
          "", "## Book / connection health (per 1 s sample)", "",
          "| book | samples | not_ready % | latency p50 / p90 / max ms | % latency > 500 ms | book_idle p50 / p90 / max ms "
          "| conn silence p50 / max ms |", "|---|---|---|---|---|---|---|"]
    for k, h in rep["health"].items():
        L.append(f"| {k} | {h['samples']} | {fmt(h['pct_not_ready'], 2)} | {h['latency_ms_p50']} / "
                 f"{h['latency_ms_p90']} / {h['latency_ms_max']} | {fmt(h['pct_latency_over_threshold'], 2)} | "
                 f"{h['book_idle_ms_p50']} / {h['book_idle_ms_p90']} / {h['book_idle_ms_max']} | "
                 f"{h['conn_silence_ms_p50']} / {h['conn_silence_ms_max']} |")
    L += realism_md(rep)
    L += ["", "## Meta / feed stats", ""]
    for k, v in db.execute("SELECT k, v FROM meta ORDER BY k"):
        L.append(f"* `{k}`: {v}")
    L += ["", "| venue | symbol | event | count |", "|---|---|---|---|"]
    for venue, sym, kind, n in db.execute("SELECT venue, symbol, kind, COUNT(*) FROM events GROUP BY 1,2,3"):
        L.append(f"| {venue} | {sym} | {kind} | {n} |")
    return "\n".join(L) + "\n"


def realism_md(rep: dict[str, Any]) -> list[str]:
    r = rep.get("maker_realism")
    if not r:
        return []
    L = ["", f"## Maker-Taker realism (PR #1.6) — fill-through window {r['window_ms'] // 1000} s, "
             f"{'strictly through' if r['through'] else 'touch or through'}", "",
         ("Trades table present: " + ", ".join(f"{k} {v}" for k, v in sorted(r["trades_loaded"].items())) + " trades."
          if r["trades_table"] else "**No `trades` table in this DB** (recorded without `--record-trades`): only the "
          "book-advance criterion (opposite side of the maker venue's 1 Hz top of book reaching the maker price) "
          "can apply."), "",
         "| Symbol | Q $ | Mode | opp s raw | runs raw | max run raw | opp s filtered | runs filtered | max run filt. | "
         "suppressed % | evidence trade / book | adverse +1s / +3s / +5s bps (triggers, n) | "
         "adverse +1s / +3s / +5s bps (unfiltered triggers, n) |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for x in r["rows"]:
        def adv(label: str) -> str:
            a = x["adverse_selection"][label]
            return (" / ".join(fmt(a[k]["mean_adverse_bps"], 2) for k in ("+1s", "+3s", "+5s"))
                    + f" (n={a['+1s']['n']})")
        L.append(f"| {x['symbol']} | {x['q_usd']} | {x['mode']} | {x['opp_seconds_raw']} | {x['runs_raw']} | "
                 f"{x['max_run_s_raw']} | {x['opp_seconds_filtered']} | {x['runs_filtered']} | {x['max_run_s_filtered']} | "
                 f"{fmt(x['suppressed_pct'], 1)} | {x['evidence_trade']} / {x['evidence_book']} | {adv('triggers')} | "
                 f"{adv('unfiltered_triggers')} |")
    L += ["", "Adverse = move of the hedge (taker) leg's executable price against us after the signal (positive = "
              "worse). Triggers = first second of each run of valid seconds."]
    sc = rep.get("trade_side_consistency") or {}
    if sc:
        L += ["", "### Trade side consistency (TODO: VERIFY_FROM_DOCS side semantics)", "",
              "| venue/raw side | trades | with 1 Hz mid | % at/above mid |", "|---|---|---|---|"]
        for k, d in sorted(sc.items()):
            L.append(f"| {k} | {d['trades']} | {d['with_mid']} | {fmt(d['pct_at_or_above_mid'], 1)} |")
    return L


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="reports/spreads.sqlite")
    ap.add_argument("--window-h", default="24")
    ap.add_argument("--out", default="reports")
    ap.add_argument("--name", default="opportunity_summary", help="output file stem")
    ap.add_argument("--title", default="")
    ap.add_argument("--fill-window-s", type=int, default=5)
    ap.add_argument("--fill-through", action="store_true")
    args = ap.parse_args(argv)
    db = sqlite3.connect(args.db)
    window_ms = int(D(args.window_h) * 3_600_000)
    rep = summarize(db, window_ms=window_ms)
    lo, hi = rep["window"]["from_ms"], rep["window"]["to_ms"]
    rep["maker_realism"] = maker_realism(db, lo, hi, window_ms=args.fill_window_s * 1000, through=args.fill_through)
    rep["trade_side_consistency"] = side_consistency(db, lo, hi)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.name}.json").write_text(dumps(rep))
    md = markdown(rep, db, args.title)
    (out / f"{args.name}.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
