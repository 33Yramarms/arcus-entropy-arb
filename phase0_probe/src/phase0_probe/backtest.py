"""PR #1.7 — offline back-test of dynamic funding-differential carry between Arcus and Entropy (HL dex "io").
Pure functions, Decimal only (no float anywhere), READ-ONLY (no order or key-handling code exists in this package).

Data: ``rows = [(hour_ms, arcus_rate, hl_rate)]`` — hourly funding payments present on BOTH venues (ascending, see
:func:`phase0_probe.funding.align_hourly`). Rates are hourly fractions; positive => longs pay shorts (funding.py).

Carry of one pair per $1 notional per leg for one hourly payment:
* direction ``+1`` = LONG Arcus / SHORT HL  -> receives ``hl − arcus`` (= ``diff``)
* direction ``−1`` = SHORT Arcus / LONG HL  -> receives ``arcus − hl`` (= ``−diff``)

Timing (NO LOOK-AHEAD, enforced structurally):
* Payment ``i`` (stamped ``hour_ms[i]``) accrues over [hour_ms[i] − 1 h, hour_ms[i]).
* The decision for payment ``i`` is taken at ``hour_ms[i] − 1 h`` (= right after payment ``i − 1`` settled) and may
  only read ``diff[0 .. i−1]`` — :func:`decide` receives exactly that prefix and nothing else.
* A position opened at decision ``i`` earns payment ``i`` onward; a position closed at decision ``i`` does NOT earn
  payment ``i``. Payment ``i`` is used for P&L accounting only, after the decision.

Signal: ``rolling_apr(i) = mean(diff[i−K .. i−1]) × 24 × 365`` (requires K contiguous hours right before payment i).
Entry: flat and ``|rolling| > entry_apr`` -> open in the profitable direction ``sign(rolling)``.
Exit (checked in this order, first match wins):
1. ``data_gap``   — payment ``i`` is not contiguous with ``i − 1`` (missing hour on either venue): forced close, the
                    funding of the missing hours is unknown so it is NOT credited (conservative).
2. ``window_end`` — strategy B only: payment ``i`` is outside the Arcus off-hours window (close at the boundary).
3. ``reverted``   — direction-aware: ``d × rolling ≤ exit_apr``. With ``exit_apr = 0`` this means "the rolling
                    differential crossed zero / is no longer in our favour" (``|rolling| < 0`` would never trigger, so
                    the signed reading is the only sensible one); with 4 % it exits once our-side carry ≤ 4 %/yr.
4. ``reversal_2h`` — the last two hourly diffs (``i−1``, ``i−2``, contiguous) both have the sign opposite to ``d``
                    (exact zero is not "opposite").
After a close no re-entry on the same decision hour (earliest re-entry: next hour) — avoids same-hour close/open
churn and makes every flip pay a full round trip plus one idle hour.
At the end of the data an open position is force-closed (``end_of_data``) and pays its close cost.

Costs: ``round_trip`` (fraction of per-leg notional, both legs, open + close); half charged at open, half at close.

Strategy B window: Arcus off-hours = payment hours whose accrual MIDPOINT is ``CLOSED`` in
:func:`phase0_probe.sessions.funding_hour_session` — 20:00–04:00 ET on NYSE trading days, all weekend hours and NYSE
holidays (same definition as PR #1.6). Early-close days keep Arcus' 04:00–20:00 window [待实测确认].
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Iterable

from phase0_probe.dec import BPS, HOURS_PER_YEAR, ZERO
from phase0_probe.sessions import funding_hour_session

HOUR_MS = 3_600_000
HUNDRED = Decimal(100)
COST_TIERS = {"optimistic_2.8bps": Decimal("2.8") / BPS, "conservative_8.3bps": Decimal("8.3") / BPS}
K_GRID = (1, 3)
ENTRY_GRID = (Decimal("0.12"), Decimal("0.18"), Decimal("0.25"), Decimal("0.35"))
EXIT_GRID = (Decimal("0"), Decimal("0.04"))
MARGIN_BUFFER = Decimal("1.5")


@dataclass(frozen=True)
class Params:
    strategy: str          # "A" (all hours) | "B" (Arcus off-hours window only)
    k: int
    entry_apr: Decimal
    exit_apr: Decimal

    def label(self) -> str:
        return f"{self.strategy} K={self.k} entry={self.entry_apr * HUNDRED:.0f}% exit={self.exit_apr * HUNDRED:.0f}%"


@dataclass
class Trade:
    direction: int
    open_idx: int
    open_hour_ms: int                 # stamp of the first payment earned
    close_idx: int | None = None      # decision index of the close (payment close_idx NOT earned); n = end of data
    close_reason: str | None = None
    hours: int = 0
    gross: Decimal = ZERO
    cost: Decimal = ZERO

    @property
    def net(self) -> Decimal:
        return self.gross - self.cost


@dataclass
class RunResult:
    params: Params
    round_trip: Decimal
    sample_hours: int
    trades: list[Trade] = field(default_factory=list)
    events: list[tuple[int, str, int, str]] = field(default_factory=list)   # (decision idx, open|close, dir, reason)


# ---------------------------------------------------------------------------------------------------- windows
def in_arcus_off_hours(hour_ms: int) -> bool:
    """True if the hourly payment stamped ``hour_ms`` accrues inside the Arcus off-hours (pinned-funding) window."""
    return funding_hour_session(hour_ms) == "CLOSED"


def always(_hour_ms: int) -> bool:
    return True


# ---------------------------------------------------------------------------------------------------- signal
def _contiguous(hours: list[int], lo: int, hi: int) -> bool:
    """hours[lo..hi] (inclusive) are consecutive hourly stamps."""
    return hours[hi] - hours[lo] == (hi - lo) * HOUR_MS


def rolling_apr(diffs_known: list[Decimal], hours: list[int], i: int, k: int) -> Decimal | None:
    """Annualized mean of diff[i−k .. i−1]; ``diffs_known`` must only contain indices < i. None if not available
    (fewer than k hours, or the k hours + payment i are not contiguous)."""
    if i < k or len(diffs_known) < i:
        return None
    if not _contiguous(hours, i - k, i):
        return None
    return sum(diffs_known[i - k:i], ZERO) / Decimal(k) * HOURS_PER_YEAR


def decide(i: int, hours: list[int], diffs_known: list[Decimal], position: int, p: Params,
           window: Callable[[int], bool]) -> tuple[str, int, str]:
    """Decision for payment i. Reads ONLY ``diffs_known`` (= diff[0..i−1]) and the hour stamps / calendar, which are
    known in advance. Returns (action, direction, reason) with action in {"hold", "close", "open", "flat"}."""
    assert len(diffs_known) == i, "decide() must receive exactly the realized prefix diff[0..i-1]"
    r = rolling_apr(diffs_known, hours, i, p.k)
    if position:
        if i >= 1 and not _contiguous(hours, i - 1, i):
            return "close", position, "data_gap"
        if not window(hours[i]):
            return "close", position, "window_end"
        if r is not None and Decimal(position) * r <= p.exit_apr:
            return "close", position, "reverted"
        if (i >= 2 and _contiguous(hours, i - 2, i)
                and Decimal(position) * diffs_known[i - 1] < ZERO and Decimal(position) * diffs_known[i - 2] < ZERO):
            return "close", position, "reversal_2h"
        return "hold", position, ""
    if window(hours[i]) and r is not None and abs(r) > p.entry_apr:
        return "open", (1 if r > ZERO else -1), "entry"
    return "flat", 0, ""


def simulate(rows: list[tuple[int, Decimal, Decimal]], p: Params, round_trip: Decimal,
             window: Callable[[int], bool] | None = None) -> RunResult:
    if window is None:
        window = in_arcus_off_hours if p.strategy == "B" else always
    hours = [t for t, _, _ in rows]
    diffs = [h - a for _, a, h in rows]
    for x in diffs:
        if not isinstance(x, Decimal):
            raise TypeError("funding rates must be decimal.Decimal")
    half = round_trip / 2
    res = RunResult(p, round_trip, len(rows))
    cur: Trade | None = None
    n = len(rows)
    for i in range(n):
        action, d, reason = decide(i, hours, diffs[:i], cur.direction if cur else 0, p, window)
        if action == "close" and cur is not None:
            cur.cost += half
            cur.close_idx, cur.close_reason = i, reason
            res.trades.append(cur)
            res.events.append((i, "close", d, reason))
            cur = None
        elif action == "open":
            cur = Trade(direction=d, open_idx=i, open_hour_ms=hours[i], cost=half)
            res.events.append((i, "open", d, reason))
        if cur is not None:                       # accounting only: payment i realized after the decision
            cur.gross += Decimal(cur.direction) * diffs[i]
            cur.hours += 1
    if cur is not None:
        cur.cost += half
        cur.close_idx, cur.close_reason = n, "end_of_data"
        res.trades.append(cur)
        res.events.append((n, "close", cur.direction, "end_of_data"))
    return res


# ---------------------------------------------------------------------------------------------------- capital / ROE
def margin_per_notional(arcus_off_hours_imf: Decimal, io_max_leverage: Decimal,
                        buffer: Decimal = MARGIN_BUFFER) -> dict[str, Decimal]:
    """Capital per $1 notional PER LEG (both legs carry $1): Arcus off-hours IMF × buffer + io IMF (1/maxLeverage) ×
    the same buffer ("io 对等保证金"). Off-hours IMF is the binding (higher) Arcus requirement, used for all hours."""
    a = arcus_off_hours_imf * buffer
    h = Decimal(1) / io_max_leverage * buffer
    return {"arcus": a, "io": h, "total": a + h, "effective_leverage_on_capital": Decimal(1) / (a + h)}


def metrics(res: RunResult, capital_per_notional: Decimal) -> dict[str, Any]:
    tr = res.trades
    gross = sum((t.gross for t in tr), ZERO)
    cost = sum((t.cost for t in tr), ZERO)
    net = gross - cost
    held = sum(t.hours for t in tr)
    n = res.sample_hours
    reasons: dict[str, int] = {}
    for t in tr:
        reasons[t.close_reason or "?"] = reasons.get(t.close_reason or "?", 0) + 1
    worst = min((t.net for t in tr), default=None)
    return {
        "opens": len(tr), "closes": len(tr), "close_reasons": reasons,
        "sample_hours": n, "hours_in_position": held,
        "pct_time_in_position": (Decimal(held) / Decimal(n) * HUNDRED) if n else ZERO,
        "avg_holding_h": (Decimal(held) / Decimal(len(tr))) if tr else None,
        "gross_funding_bps": gross * BPS, "total_cost_bps": cost * BPS, "net_notional_bps": net * BPS,
        "winning_round_trips": sum(1 for t in tr if t.net > ZERO),
        "max_single_trade_loss_bps": (worst * BPS) if worst is not None and worst < ZERO else ZERO,
        "worst_trade_net_bps": (worst * BPS) if worst is not None else None,
        "capital_per_notional": capital_per_notional,
        "roe_period_pct": net / capital_per_notional * HUNDRED,
        "roe_annualized_pct": (net / capital_per_notional * HOURS_PER_YEAR / Decimal(n) * HUNDRED) if n else None,
        "roe_annualized_while_deployed_pct": (net / capital_per_notional * HOURS_PER_YEAR / Decimal(held) * HUNDRED)
        if held else None,
    }


def portfolio(per_symbol: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Equal-CAPITAL portfolio, capital always allocated to every symbol (also while flat). Each symbol's ROE is
    annualized over its own sample, the portfolio ROE is their mean. Notional bps figures are equal-weight means."""
    ms = list(per_symbol.values())
    k = Decimal(len(ms))
    opens = sum(m["opens"] for m in ms)
    held = sum(m["hours_in_position"] for m in ms)

    def mean(key: str) -> Decimal:
        return sum((m[key] for m in ms), ZERO) / k

    losses = [m["max_single_trade_loss_bps"] for m in ms]
    return {"symbols": len(ms), "opens": opens, "closes": opens,
            "avg_holding_h": (Decimal(held) / Decimal(opens)) if opens else None,
            "mean_gross_funding_bps": mean("gross_funding_bps"), "mean_total_cost_bps": mean("total_cost_bps"),
            "mean_net_notional_bps": mean("net_notional_bps"),
            "roe_annualized_pct_capital_always_allocated": mean("roe_annualized_pct"),
            "symbols_net_positive": sum(1 for m in ms if m["net_notional_bps"] > ZERO),
            "max_single_trade_loss_bps": min(losses) if losses else ZERO}


def grid(k_grid: Iterable[int] = K_GRID, entry_grid: Iterable[Decimal] = ENTRY_GRID,
         exit_grid: Iterable[Decimal] = EXIT_GRID) -> list[Params]:
    return [Params(s, k, e, x) for s in ("A", "B") for k in k_grid for e in entry_grid for x in exit_grid]


def run_grid(data: dict[str, list[tuple[int, Decimal, Decimal]]], capital: dict[str, Decimal],
             params: list[Params] | None = None, tiers: dict[str, Decimal] | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in params or grid():
        for tier, rt in (tiers or COST_TIERS).items():
            per = {s: metrics(simulate(rows, p, rt), capital[s]) for s, rows in data.items()}
            out.append({"params": {"strategy": p.strategy, "k": p.k, "entry_apr": p.entry_apr, "exit_apr": p.exit_apr,
                                   "label": p.label()},
                        "cost_tier": tier, "round_trip_bps": rt * BPS, "portfolio": portfolio(per), "per_symbol": per})
    return out


def best(results: list[dict[str, Any]], strategy: str, tier: str) -> dict[str, Any] | None:
    cand = [r for r in results if r["params"]["strategy"] == strategy and r["cost_tier"] == tier]
    return max(cand, key=lambda r: r["portfolio"]["roe_annualized_pct_capital_always_allocated"], default=None)


def split_halves(data: dict[str, list[tuple[int, Decimal, Decimal]]]
                 ) -> tuple[dict[str, list[tuple[int, Decimal, Decimal]]], dict[str, list[tuple[int, Decimal, Decimal]]]]:
    """Chronological 50/50 split per symbol (for a crude in-sample → out-of-sample parameter check)."""
    a, b = {}, {}
    for s, rows in data.items():
        m = len(rows) // 2
        a[s], b[s] = rows[:m], rows[m:]
    return a, b


def arcus_pin_diagnostic(rows: list[tuple[int, Decimal, Decimal]]) -> dict[str, Any]:
    """Is the Arcus rate really pinned inside the off-hours window? (annualized mean / min / max / distinct values)."""
    out: dict[str, Any] = {}
    for name, sel in (("off_hours_window", True), ("arcus_rth_window", False)):
        xs = [a for t, a, _ in rows if in_arcus_off_hours(t) == sel]
        hs = [h for t, _, h in rows if in_arcus_off_hours(t) == sel]
        if not xs:
            out[name] = {"hours": 0}
            continue
        out[name] = {"hours": len(xs), "arcus_mean_apr_pct": sum(xs, ZERO) / Decimal(len(xs)) * HOURS_PER_YEAR * HUNDRED,
                     "arcus_min_apr_pct": min(xs) * HOURS_PER_YEAR * HUNDRED,
                     "arcus_max_apr_pct": max(xs) * HOURS_PER_YEAR * HUNDRED, "arcus_distinct_values": len(set(xs)),
                     "hl_mean_apr_pct": sum(hs, ZERO) / Decimal(len(hs)) * HOURS_PER_YEAR * HUNDRED}
    return out
