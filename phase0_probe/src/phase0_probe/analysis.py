"""Opportunity statistics from the SQLite snapshots (Decimal arithmetic throughout).

Per (symbol, Q, mode), each second takes the BETTER of the two directions. A second is:
* ``not_ready`` / ``stale`` if any row of that second has that status (gated: never an opportunity);
* an opportunity if the best ``ok`` row has ``net_resid_bps > 0`` (exit at the rolling-median basis, PR #1.5);
  the Phase 0 zero-convergence share (``net_bps > 0``) is reported alongside for comparison.
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
    cur = db.execute("SELECT ts_ms, symbol, q_usd, mode, direction, status, net_bps, open_spread_bps, basis_bps, "
                     "net_resid_bps, residual_bps FROM opportunities WHERE ts_ms BETWEEN ? AND ? ORDER BY ts_ms",
                     (lo, hi))
    sec: dict[tuple[str, str, str], dict[int, dict[str, Any]]] = {}
    for ts, sym, q, mode, direction, status, net, spread, basis, net_r, resid in cur:
        d = sec.setdefault((sym, q, mode), {}).setdefault(ts, {"best": None, "best0": None, "status": set(),
                                                               "spread": None, "basis": None, "resid": None})
        d["status"].add(status)
        if status != "ok":
            continue
        if net is not None:
            n0 = Decimal(net)
            if d["best0"] is None or n0 > d["best0"]:
                d["best0"] = n0
        if net_r is not None:
            n = Decimal(net_r)
            if d["best"] is None or n > d["best"]:
                d["best"], d["spread"], d["dir"] = n, Decimal(spread), direction
        d["basis"] = Decimal(basis)
        d["resid"] = None if resid is None else Decimal(resid)
    rows = []
    for (sym, q, mode), per in sorted(sec.items(), key=lambda kv: (kv[0][0], Decimal(kv[0][1]), kv[0][2])):
        stamps = sorted(per)
        gated = {t for t in stamps if per[t]["status"] & {"stale", "not_ready"}}
        live = [t for t in stamps if t not in gated]
        opp = [t for t in live if per[t]["best"] is not None and per[t]["best"] > ZERO]
        runs: list[int] = []
        prev = None
        for t in opp:
            if prev is not None and t - prev == 1000:
                runs[-1] += 1
            else:
                runs.append(1)
            prev = t
        nets = [per[t]["best"] for t in live if per[t]["best"] is not None]
        nets0 = [per[t]["best0"] for t in live if per[t]["best0"] is not None]
        spreads = [per[t]["spread"] for t in live if per[t]["spread"] is not None]
        bases = [per[t]["basis"] for t in live if per[t]["basis"] is not None]
        resids = [abs(per[t]["resid"]) for t in live if per[t]["resid"] is not None]
        dirs: dict[str, int] = {}
        for t in opp:
            dirs[per[t]["dir"]] = dirs.get(per[t]["dir"], 0) + 1
        n = len(stamps)
        n_stale = sum(1 for t in stamps if "stale" in per[t]["status"])
        n_nr = sum(1 for t in stamps if "not_ready" in per[t]["status"])
        pct = (lambda k: Decimal(k) / Decimal(n) * HUNDRED if n else None)
        rows.append({
            "symbol": sym, "q_usd": q, "mode": mode, "seconds": n, "opp_seconds": len(opp),
            "stale_seconds": n_stale, "not_ready_seconds": n_nr,
            "warmup_seconds": sum(1 for t in live if per[t]["best"] is None and per[t]["best0"] is not None),
            "insufficient_depth_seconds": sum(1 for t in stamps if "insufficient_depth" in per[t]["status"]),
            "pct_net_pos": pct(len(opp)), "pct_stale": pct(n_stale), "pct_not_ready": pct(n_nr),
            "pct_net_pos_zero_convergence": pct(sum(1 for t in live if per[t]["best0"] is not None
                                                    and per[t]["best0"] > ZERO)),
            "runs": len(runs), "avg_duration_s": _mean([Decimal(r) for r in runs]),
            "max_run_s": max(runs) if runs else 0,
            "max_net_bps": max(nets) if nets else None, "median_net_bps": _median(nets),
            "max_net_bps_zero_convergence": max(nets0) if nets0 else None,
            "median_open_spread_bps": _median(spreads), "median_basis_bps": _median(bases),
            "median_abs_residual_bps": _median(resids), "max_abs_residual_bps": max(resids) if resids else None,
            "opp_by_direction": dirs,
        })
    return {"window": {"from_ms": lo, "to_ms": hi, "seconds": (hi - lo) // 1000 + 1 if hi >= lo else 0},
            "rows": rows, "funding": funding_summary(db, lo, hi), "health": health_summary(db, lo, hi)}


def _pct_int(xs: list[int], p: int) -> int | None:
    if not xs:
        return None
    ys = sorted(xs)
    return ys[min(len(ys) - 1, len(ys) * p // 100)]


def health_summary(db: sqlite3.Connection, lo: int, hi: int, max_latency_ms: int = 500) -> dict[str, Any]:
    out: dict[str, Any] = {}
    pairs = db.execute("SELECT DISTINCT symbol, venue FROM book_health WHERE ts_ms BETWEEN ? AND ? ORDER BY 1, 2",
                       (lo, hi)).fetchall()
    for sym, venue in pairs:
        rows = db.execute("SELECT ready, network_latency_ms, book_idle_ms, conn_silence_ms FROM book_health "
                          "WHERE symbol=? AND venue=? AND ts_ms BETWEEN ? AND ?", (sym, venue, lo, hi)).fetchall()
        lat = [r[1] for r in rows if r[1] is not None]
        idle = [r[2] for r in rows if r[2] is not None]
        sil = [r[3] for r in rows if r[3] is not None]
        n = len(rows)
        out[f"{sym}/{venue}"] = {
            "samples": n, "pct_not_ready": Decimal(sum(1 for r in rows if not r[0])) / Decimal(n) * HUNDRED if n else None,
            "latency_ms_p50": _pct_int(lat, 50), "latency_ms_p90": _pct_int(lat, 90), "latency_ms_max": max(lat, default=None),
            "pct_latency_over_threshold": (Decimal(sum(1 for x in lat if x > max_latency_ms)) / Decimal(len(lat))
                                           * HUNDRED) if lat else None,
            "book_idle_ms_p50": _pct_int(idle, 50), "book_idle_ms_p90": _pct_int(idle, 90),
            "book_idle_ms_max": max(idle, default=None),
            "conn_silence_ms_p50": _pct_int(sil, 50), "conn_silence_ms_max": max(sil, default=None),
        }
    return out


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
