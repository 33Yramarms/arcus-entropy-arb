"""Summarise recorded snapshots: frequency of net>0 opportunities, average duration, annualised funding differential.

Usage: uv run python scripts/analyze_opportunity.py [--db reports/spreads.sqlite] [--window-h 24] [--out reports]
The window is the last ``--window-h`` hours of data (works for shorter recordings: it then covers all of it).
"""
from __future__ import annotations

import argparse
import pathlib
import sqlite3
import sys
from decimal import Decimal
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from phase0_probe.analysis import summarize  # noqa: E402
from phase0_probe.dec import D, dumps, fmt  # noqa: E402


def markdown(rep: dict[str, Any], db: sqlite3.Connection) -> str:
    w = rep["window"]
    L = ["# Opportunity summary (Phase 0, read-only)", "",
         f"Window: {w['from_ms']} → {w['to_ms']} epoch ms ({w['seconds']} s). Per second the better direction is "
         "taken. net = open VWAP spread − close slippage (current books) − open+close fees − 2 bps buffer. "
         "Stale = either book older than the stale threshold (500 ms) or invalid.", "",
         "| Symbol | Q $ | Mode | % s net>0 | runs | avg dur s | max run s | max net bps | median net bps | "
         "median open spread bps | median basis bps (HL−Arcus) | stale % | insuff. depth s |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rep["rows"]:
        L.append("| " + " | ".join([r["symbol"], r["q_usd"], r["mode"], fmt(r["pct_net_pos"], 2), str(r["runs"]),
                                     fmt(r["avg_duration_s"], 2), str(r["max_run_s"]), fmt(r["max_net_bps"], 3),
                                     fmt(r["median_net_bps"], 3), fmt(r["median_open_spread_bps"], 3),
                                     fmt(r["median_basis_bps"], 3), fmt(r["pct_stale"], 2),
                                     str(r["insufficient_depth_seconds"])]) + " |")
    L += ["", "## Funding (hourly rates, window means; predicted if available else current)", "",
          "| Symbol | Arcus 1h | HL 1h | Arcus ann. | HL ann. | Δ ann. (HL−Arcus) | samples |", "|---|---|---|---|---|---|---|"]
    for sym, f in rep["funding"].items():
        L.append(f"| {sym} | {fmt(f['arcus_hourly_mean'], 8)} | {fmt(f['hl_hourly_mean'], 8)} | "
                 f"{fmt(f['arcus_annual_mean'], 4)} | {fmt(f['hl_annual_mean'], 4)} | "
                 f"{fmt(f['diff_annual_hl_minus_arcus'], 4)} | {f['samples']} |")
    L += ["", "Positive Δ: long Arcus / short HL receives carry.", "", "## Feed health", ""]
    for k, v in db.execute("SELECT k, v FROM meta ORDER BY k"):
        L.append(f"* `{k}`: {v}")
    L += ["", "| venue | symbol | event | count |", "|---|---|---|---|"]
    for venue, sym, kind, n in db.execute("SELECT venue, symbol, kind, COUNT(*) FROM events GROUP BY 1,2,3"):
        L.append(f"| {venue} | {sym} | {kind} | {n} |")
    L += ["", "| symbol | venue | mean age ms | p50 age ms | max age ms | % samples age>500ms |", "|---|---|---|---|---|---|"]
    for sym, venue in db.execute("SELECT DISTINCT symbol, venue FROM book_health ORDER BY 1, 2").fetchall():
        ages = sorted(int(a) for (a,) in db.execute(
            "SELECT age_ms FROM book_health WHERE symbol=? AND venue=? AND age_ms IS NOT NULL", (sym, venue)))
        if ages:
            mean = Decimal(sum(ages)) / Decimal(len(ages))
            over = Decimal(sum(1 for a in ages if a > 500)) / Decimal(len(ages)) * 100
            L.append(f"| {sym} | {venue} | {fmt(mean, 1)} | {ages[len(ages) // 2]} | {ages[-1]} | {fmt(over, 2)} |")
    return "\n".join(L) + "\n"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="reports/spreads.sqlite")
    ap.add_argument("--window-h", default="24")
    ap.add_argument("--out", default="reports")
    args = ap.parse_args(argv)
    db = sqlite3.connect(args.db)
    window_ms = int(D(args.window_h) * 3_600_000)
    rep = summarize(db, window_ms=window_ms)
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "opportunity_summary.json").write_text(dumps(rep))
    md = markdown(rep, db)
    (out / "opportunity_summary.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
