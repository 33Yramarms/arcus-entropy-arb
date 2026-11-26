"""Opportunity statistics from the SQLite snapshots (Decimal arithmetic throughout).

Per (symbol, Q, mode), each second takes the BETTER of the two directions. A second is:
* ``stale`` if any row of that second is stale (either book older than the threshold or invalid);
* an opportunity if the best ``ok`` row has ``net_bps > 0``.
Durations are runs of consecutive opportunity seconds (1 s grid). Funding differential = mean over the window of
(HL − Arcus) hourly rate × 8760, using predicted rates when present, else current.
"""
from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Any

from phase0_probe.dec import HOURS_PER_YEAR, ZERO

HUNDRED = Decimal(100)


def _median(xs: list[Decimal]) -> Decimal | None:
    if not xs:
        return None
    ys = sorted(xs)
    n = len(ys)
    return ys[n // 2] if n % 2 else (ys[n // 2 - 1] + ys[n // 2]) / 2


def _mean(xs: list[Decimal]) -> Decimal | None:
    return sum(xs, ZERO) / len(xs) if xs else None


def _bounds(db: sqlite3.Connection, window_ms: int | None) -> tuple[int, int]:
    lo, hi = db.execute("SELECT MIN(ts_ms), MAX(ts_ms) FROM opportunities").fetchone()
    if lo is None:
        return 0, -1
    if window_ms is not None:
        lo = max(lo, hi - window_ms)
    return lo, hi


def summarize(db: sqlite3.Connection, window_ms: int | None = 24 * 3600 * 1000) -> dict[str, Any]:
    lo, hi = _bounds(db, window_ms)
    cur = db.execute("SELECT ts_ms, symbol, q_usd, mode, direction, status, net_bps, open_spread_bps, basis_bps "
                     "FROM opportunities WHERE ts_ms BETWEEN ? AND ? ORDER BY ts_ms", (lo, hi))
    sec: dict[tuple[str, str, str], dict[int, dict[str, Any]]] = {}
    for ts, sym, q, mode, direction, status, net, spread, basis in cur:
        d = sec.setdefault((sym, q, mode), {}).setdefault(ts, {"stale": False, "best": None, "status": set(),
                                                               "spread": None, "basis": None})
        d["status"].add(status)
        if status == "stale":
            d["stale"] = True
        if status == "ok" and net is not None:
            n = Decimal(net)
            if d["best"] is None or n > d["best"]:
                d["best"], d["spread"], d["dir"] = n, Decimal(spread), direction
            d["basis"] = Decimal(basis)
    rows = []
    for (sym, q, mode), per in sorted(sec.items(), key=lambda kv: (kv[0][0], Decimal(kv[0][1]), kv[0][2])):
        stamps = sorted(per)
        opp = [t for t in stamps if not per[t]["stale"] and per[t]["best"] is not None and per[t]["best"] > ZERO]
        runs: list[int] = []
        prev = None
        for t in opp:
            if prev is not None and t - prev == 1000:
                runs[-1] += 1
            else:
                runs.append(1)
            prev = t
        nets = [per[t]["best"] for t in stamps if per[t]["best"] is not None and not per[t]["stale"]]
        spreads = [per[t]["spread"] for t in stamps if per[t]["spread"] is not None and not per[t]["stale"]]
        bases = [per[t]["basis"] for t in stamps if per[t]["basis"] is not None and not per[t]["stale"]]
        dirs: dict[str, int] = {}
        for t in opp:
            dirs[per[t]["dir"]] = dirs.get(per[t]["dir"], 0) + 1
        n = len(stamps)
        rows.append({
            "symbol": sym, "q_usd": q, "mode": mode, "seconds": n, "opp_seconds": len(opp),
            "stale_seconds": sum(1 for t in stamps if per[t]["stale"]),
            "insufficient_depth_seconds": sum(1 for t in stamps if "insufficient_depth" in per[t]["status"]),
            "pct_net_pos": Decimal(len(opp)) / Decimal(n) * HUNDRED if n else None,
            "pct_stale": Decimal(sum(1 for t in stamps if per[t]["stale"])) / Decimal(n) * HUNDRED if n else None,
            "runs": len(runs), "avg_duration_s": _mean([Decimal(r) for r in runs]),
            "max_run_s": max(runs) if runs else 0,
            "max_net_bps": max(nets) if nets else None, "median_net_bps": _median(nets),
            "median_open_spread_bps": _median(spreads), "median_basis_bps": _median(bases),
            "opp_by_direction": dirs,
        })
    return {"window": {"from_ms": lo, "to_ms": hi, "seconds": (hi - lo) // 1000 + 1 if hi >= lo else 0},
            "rows": rows, "funding": funding_summary(db, lo, hi)}


def funding_summary(db: sqlite3.Connection, lo: int, hi: int) -> dict[str, Any]:
    rates: dict[tuple[str, int], dict[str, Decimal | None]] = {}
    for ts, sym, venue, cur_r, pred in db.execute(
            "SELECT ts_ms, symbol, venue, current_hourly, predicted_hourly FROM funding WHERE ts_ms BETWEEN ? AND ?",
            (lo, hi)):
        r = Decimal(pred) if pred is not None else (Decimal(cur_r) if cur_r is not None else None)
        rates.setdefault((sym, ts), {})[venue] = r
    out: dict[str, Any] = {}
    by_sym: dict[str, dict[str, list[Decimal]]] = {}
    for (sym, _ts), v in rates.items():
        b = by_sym.setdefault(sym, {"arcus": [], "hl": [], "diff": []})
        a, h = v.get("arcus"), v.get("hyperliquid")
        if a is not None:
            b["arcus"].append(a)
        if h is not None:
            b["hl"].append(h)
        if a is not None and h is not None:
            b["diff"].append((h - a) * HOURS_PER_YEAR)
    for sym, b in sorted(by_sym.items()):
        out[sym] = {"samples": len(b["diff"]), "arcus_hourly_mean": _mean(b["arcus"]),
                    "hl_hourly_mean": _mean(b["hl"]),
                    "arcus_annual_mean": None if not b["arcus"] else _mean(b["arcus"]) * HOURS_PER_YEAR,
                    "hl_annual_mean": None if not b["hl"] else _mean(b["hl"]) * HOURS_PER_YEAR,
                    "diff_annual_hl_minus_arcus": _mean(b["diff"])}
    return out
