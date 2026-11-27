"""PR #1.6 — Maker-Taker realism checks on recorded snapshots (Decimal only, read-only analysis).

The Phase 0 model prices a MAKER leg at its own-side touch (buy at best bid / sell at best ask) and assumes it fills.
Two checks remove that optimism:

(a) Fill-through filter. A Maker-Taker opportunity second ``t`` counts only if, inside the signal window
    (t, t + W], the MAKER venue shows evidence that a resting order at the maker price P would have been executed:
    * ``trade``: a recorded public trade at or through P (maker BUY: trade px ≤ P; maker SELL: px ≥ P), or strictly
      through P with ``through=True`` (touch-only fills are ambiguous: queue position is unknown); or
    * ``book``: the OPPOSITE side of the maker venue's top of book (1 Hz ``book_health`` samples) advanced to / through
      P (maker BUY: best ask ≤ P; maker SELL: best bid ≥ P; strict with ``through=True``).
    Seconds without such evidence are maker "artifacts" (a quote nobody traded against).
(b) Adverse selection. For every valid (filtered) signal, the HEDGE (taker) leg's executable price — the VWAP for the
    same Q from the opportunity row of the same direction/mode at t + k (status ``ok``) — is compared with its value at
    t; adverse move in bps (positive = worse for us): hedge SELL (p_t − p_{t+k}) / p_t, hedge BUY (p_{t+k} − p_t) / p_t,
    k ∈ {1, 3, 5} s. Reported for every valid second and for run starts (triggers).
    Sprint 2: when the t + k row is missing / not ``ok`` (insufficient depth, stale, not ready) the sample is counted
    in ``missing_hedge_vwap`` and EXCLUDED from the statistics. The former fallback to the 1 Hz top of book mixed a
    BBO price into a VWAP series and biased adverse selection low; ``top_of_book_fallback`` is kept (always 0) for
    report compatibility.
"""
from __future__ import annotations

import bisect
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from phase0_probe.dec import BPS, ZERO

MAKER_MODES = ("MAKER_ARCUS_TAKER_HL", "MAKER_HL_TAKER_ARCUS")


@dataclass(frozen=True)
class Legs:
    maker_venue: str
    maker_side: str            # BUY | SELL
    maker_px_field: str        # open_buy_px | open_sell_px
    hedge_venue: str
    hedge_side: str
    hedge_px_field: str


def legs(direction: str, mode: str) -> Legs:
    """Which leg rests (maker) and which hedges (taker) for a direction/mode pair."""
    buy_venue, sell_venue = (("arcus", "hyperliquid") if direction == "BUY_ARCUS_SELL_HL" else ("hyperliquid", "arcus"))
    maker_venue = "arcus" if mode == "MAKER_ARCUS_TAKER_HL" else "hyperliquid"
    if mode not in MAKER_MODES:
        raise ValueError(f"not a maker mode: {mode}")
    if maker_venue == buy_venue:
        return Legs(maker_venue, "BUY", "open_buy_px", sell_venue, "SELL", "open_sell_px")
    return Legs(maker_venue, "SELL", "open_sell_px", buy_venue, "BUY", "open_buy_px")


def crosses(maker_side: str, maker_px: Decimal, px: Decimal, through: bool) -> bool:
    if maker_side == "BUY":
        return px < maker_px if through else px <= maker_px
    return px > maker_px if through else px >= maker_px


def fill_evidence(maker_side: str, maker_px: Decimal, t_ms: int, window_ms: int,
                  trades: list[tuple[int, Decimal]], tops: list[tuple[int, Decimal | None, Decimal | None]],
                  through: bool = False, trade_keys: list[int] | None = None,
                  top_keys: list[int] | None = None) -> str | None:
    """'trade' | 'book' | None. ``trades`` = [(exch_ts_ms, px)] and ``tops`` = [(ts_ms, best_bid, best_ask)] of the
    MAKER venue, both ascending by time (``*_keys`` = their precomputed timestamps). Window = (t, t + window]."""
    lo = bisect.bisect_right(trade_keys if trade_keys is not None else [x[0] for x in trades], t_ms)
    for ts, px in trades[lo:]:
        if ts > t_ms + window_ms:
            break
        if crosses(maker_side, maker_px, px, through):
            return "trade"
    i = bisect.bisect_right(top_keys if top_keys is not None else [x[0] for x in tops], t_ms)
    for ts, bid, ask in tops[i:]:
        if ts > t_ms + window_ms:
            break
        opp = ask if maker_side == "BUY" else bid
        if opp is not None and crosses(maker_side, maker_px, opp, through):
            return "book"
    return None


def adverse_bps(hedge_side: str, p0: Decimal, p1: Decimal) -> Decimal:
    return ((p0 - p1) if hedge_side == "SELL" else (p1 - p0)) / p0 * BPS


def _mean(xs: list[Decimal]) -> Decimal | None:
    return sum(xs, ZERO) / Decimal(len(xs)) if xs else None


def _median(xs: list[Decimal]) -> Decimal | None:
    if not xs:
        return None
    ys = sorted(xs)
    n = len(ys)
    return ys[n // 2] if n % 2 else (ys[n // 2 - 1] + ys[n // 2]) / 2


def _runs(stamps: list[int]) -> list[list[int]]:
    out: list[list[int]] = []
    for t in stamps:
        if out and t - out[-1][-1] == 1000:
            out[-1].append(t)
        else:
            out.append([t])
    return out


def has_trades_table(db: sqlite3.Connection) -> bool:
    """Whether this DB actually RECORDED the public trade tape (Sprint 2). ``store.SCHEMA`` always creates the
    ``trades`` table, so its existence alone proves nothing. Rule: the ``meta.record_trades`` flag written by
    ``record_spreads.py`` (PR #1.6+) decides when present ('1' = recorded); DBs without that flag (older or
    hand-built) count as recorded only if the table exists AND holds at least one row."""
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='trades'").fetchone() is None:
        return False
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'").fetchone() is not None:
        flag = db.execute("SELECT v FROM meta WHERE k = 'record_trades'").fetchone()
        if flag is not None:
            return str(flag[0]).strip() == "1"
    return db.execute("SELECT 1 FROM trades LIMIT 1").fetchone() is not None


def load_trades(db: sqlite3.Connection, lo: int, hi: int) -> dict[tuple[str, str], list[tuple[int, Decimal]]]:
    out: dict[tuple[str, str], list[tuple[int, Decimal]]] = {}
    if not has_trades_table(db):
        return out
    for venue, sym, ts_us, px in db.execute("SELECT venue, symbol, exch_ts_us, price FROM trades WHERE exch_ts_us "
                                            "BETWEEN ? AND ? ORDER BY exch_ts_us", (lo * 1000, hi * 1000)):
        out.setdefault((venue, sym), []).append((ts_us // 1000, Decimal(px)))
    return out


def load_tops(db: sqlite3.Connection, lo: int, hi: int) -> dict[tuple[str, str], list[tuple[int, Decimal | None, Decimal | None]]]:
    out: dict[tuple[str, str], list[tuple[int, Decimal | None, Decimal | None]]] = {}
    for ts, sym, venue, ready, bb, ba in db.execute("SELECT ts_ms, symbol, venue, ready, best_bid, best_ask FROM "
                                                    "book_health WHERE ts_ms BETWEEN ? AND ? ORDER BY ts_ms", (lo, hi)):
        if not ready:
            continue                                  # an unproven book is not evidence
        out.setdefault((venue, sym), []).append((ts, None if bb is None else Decimal(bb),
                                                 None if ba is None else Decimal(ba)))
    return out


def maker_realism(db: sqlite3.Connection, lo: int, hi: int, *, window_ms: int = 5000, through: bool = False,
                  horizons_s: tuple[int, ...] = (1, 3, 5)) -> dict[str, Any]:
    """Apply (a) and (b) to every (symbol, Q, maker mode) in [lo, hi]. Per second the best positive ``ok`` direction
    (max ``net_resid_bps``) is the signal, exactly as :func:`phase0_probe.analysis.summarize` counts it."""
    trades = load_trades(db, lo, hi + window_ms)
    tops = load_tops(db, lo, hi + max(window_ms, max(horizons_s) * 1000))
    trade_keys = {k: [x[0] for x in v] for k, v in trades.items()}
    top_keys = {k: [x[0] for x in v] for k, v in tops.items()}
    rows: dict[tuple[str, str, str, str], dict[int, tuple[Decimal | None, Decimal | None]]] = {}
    sig: dict[tuple[str, str, str], dict[int, tuple[Decimal, str]]] = {}
    for ts, sym, q, mode, direction, status, nr, pb, ps in db.execute(
            "SELECT ts_ms, symbol, q_usd, mode, direction, status, net_resid_bps, open_buy_px, open_sell_px FROM "
            "opportunities WHERE mode IN (?, ?) AND ts_ms BETWEEN ? AND ? ORDER BY ts_ms",
            (*MAKER_MODES, lo, hi + max(horizons_s) * 1000)):
        if status == "ok":
            rows.setdefault((sym, q, mode, direction), {})[ts] = (None if pb is None else Decimal(pb),
                                                                 None if ps is None else Decimal(ps))
        if ts > hi or status != "ok" or nr is None or Decimal(nr) <= ZERO:
            continue
        cur = sig.setdefault((sym, q, mode), {}).get(ts)
        if cur is None or Decimal(nr) > cur[0]:
            sig[(sym, q, mode)][ts] = (Decimal(nr), direction)
    gated = set(db.execute("SELECT DISTINCT symbol, ts_ms FROM opportunities WHERE status IN ('stale','not_ready') "
                           "AND ts_ms BETWEEN ? AND ?", (lo, hi)).fetchall())
    out_rows = []
    for (sym, q, mode), per in sorted(sig.items(), key=lambda kv: (kv[0][0], Decimal(kv[0][1]), kv[0][2])):
        per = {t: v for t, v in per.items() if (sym, t) not in gated}
        kept: list[int] = []
        ev_count = {"trade": 0, "book": 0}
        for t in sorted(per):
            direction = per[t][1]
            lg = legs(direction, mode)
            px = rows[(sym, q, mode, direction)][t][0 if lg.maker_px_field == "open_buy_px" else 1]
            if px is None:
                continue
            mk = (lg.maker_venue, sym)
            ev = fill_evidence(lg.maker_side, px, t, window_ms, trades.get(mk, []), tops.get(mk, []), through,
                               trade_keys.get(mk, []), top_keys.get(mk, []))
            if ev:
                ev_count[ev] += 1
                kept.append(t)
        runs_raw, runs_kept = _runs(sorted(per)), _runs(kept)
        adverse: dict[str, Any] = {}
        for label, stamps in (("valid_seconds", kept), ("triggers", [r[0] for r in runs_kept]),
                              ("unfiltered_triggers", [r[0] for r in runs_raw])):
            adverse[label] = {}
            for k in horizons_s:
                moves: list[Decimal] = []
                missing = missing_hedge = 0
                for t in stamps:
                    direction = per[t][1]
                    lg = legs(direction, mode)
                    idx = 0 if lg.hedge_px_field == "open_buy_px" else 1
                    series = rows[(sym, q, mode, direction)]
                    p0 = series[t][idx]
                    p1 = series.get(t + k * 1000, (None, None))[idx]
                    if p1 is None:                     # no ``ok`` VWAP at t + k: missing, never a BBO substitute
                        missing_hedge += 1
                    if p0 is None or p1 is None:
                        missing += 1
                        continue
                    moves.append(adverse_bps(lg.hedge_side, p0, p1))
                adverse[label][f"+{k}s"] = {"n": len(moves), "mean_adverse_bps": _mean(moves),
                                            "median_adverse_bps": _median(moves),
                                            "pct_adverse": (Decimal(sum(1 for m in moves if m > ZERO)) /
                                                            Decimal(len(moves)) * 100) if moves else None,
                                            "top_of_book_fallback": 0, "missing_hedge_vwap": missing_hedge,
                                            "missing": missing}
        n_trades = sum(len(v) for (_venue, s_), v in trades.items() if s_ == sym)
        out_rows.append({
            "symbol": sym, "q_usd": q, "mode": mode, "opp_seconds_raw": len(per), "runs_raw": len(runs_raw),
            "opp_seconds_filtered": len(kept), "runs_filtered": len(runs_kept),
            "suppressed_pct": (Decimal(len(per) - len(kept)) / Decimal(len(per)) * 100) if per else None,
            "evidence_trade": ev_count["trade"], "evidence_book": ev_count["book"],
            "max_run_s_raw": max((len(r) for r in runs_raw), default=0),
            "max_run_s_filtered": max((len(r) for r in runs_kept), default=0),
            "trades_in_window_for_symbol": n_trades, "adverse_selection": adverse,
        })
    return {"window_ms": window_ms, "through": through, "trades_table": has_trades_table(db),
            "trades_loaded": {f"{v}/{s_}": len(x) for (v, s_), x in trades.items()}, "rows": out_rows}


def side_consistency(db: sqlite3.Connection, lo: int, hi: int) -> dict[str, Any]:
    """Live check of the side TODOs: share of trades priced at/above the venue's mid of the same 1 Hz sample, per
    venue and raw side. If ``side`` is the aggressor, BUY/"B" trades should mostly print ≥ mid, SELL/"A" ≤ mid."""
    if not has_trades_table(db):
        return {}
    mids: dict[tuple[str, str], dict[int, Decimal]] = {}
    for (venue, sym), xs in load_tops(db, lo - 2000, hi + 2000).items():
        mids[(venue, sym)] = {t: (b + a) / 2 for t, b, a in xs if b is not None and a is not None}
    out: dict[str, Any] = {}
    for venue, sym, ts_us, px, raw in db.execute("SELECT venue, symbol, exch_ts_us, price, raw_side FROM trades "
                                                 "WHERE exch_ts_us BETWEEN ? AND ?", (lo * 1000, hi * 1000)):
        m = mids.get((venue, sym), {}).get(ts_us // 1000 // 1000 * 1000)
        k = f"{venue}/{raw}"
        d = out.setdefault(k, {"trades": 0, "with_mid": 0, "at_or_above_mid": 0, "below_mid": 0})
        d["trades"] += 1
        if m is None:
            continue
        d["with_mid"] += 1
        if Decimal(px) >= m:
            d["at_or_above_mid"] += 1
        else:
            d["below_mid"] += 1
    for d in out.values():
        d["pct_at_or_above_mid"] = (Decimal(d["at_or_above_mid"]) / Decimal(d["with_mid"]) * 100) if d["with_mid"] else None
    return out
