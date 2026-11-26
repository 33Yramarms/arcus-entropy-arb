"""PR #1.7 — dynamic funding back-test: no look-ahead, entry/exit rules, 2 h reversal, off-hours window (weekend /
DST / half day / holiday), cost accounting, ROE math, Decimal-only."""
from __future__ import annotations

import ast
import datetime as dt
import pathlib
from decimal import Decimal

import pytest

from phase0_probe.backtest import (COST_TIERS, HOUR_MS, Params, always, decide, grid, in_arcus_off_hours,
                                   margin_per_notional, metrics, portfolio, rolling_apr, run_grid, simulate)
from phase0_probe.dec import BPS, HOURS_PER_YEAR

ROOT = pathlib.Path(__file__).resolve().parents[1]
T0 = 1_793_131_200_000            # an exact hour


def apr(x: str) -> Decimal:
    """hourly rate whose annualization is x (e.g. '0.50' = 50 %/yr)."""
    return Decimal(x) / HOURS_PER_YEAR


def rows_from_diffs(diffs: list[Decimal], start: int = T0, arcus: Decimal = Decimal(0)) -> list[tuple[int, Decimal, Decimal]]:
    return [(start + i * HOUR_MS, arcus, arcus + d) for i, d in enumerate(diffs)]


def utc_ms(y: int, mo: int, d: int, h: int, mi: int = 0) -> int:
    return int(dt.datetime(y, mo, d, h, mi, tzinfo=dt.timezone.utc).timestamp()) * 1000


A1 = Params("A", 1, Decimal("0.12"), Decimal("0"))
ZERO_COST = Decimal(0)


# ------------------------------------------------------------------------------------------------ no look-ahead
def test_rolling_uses_only_prefix() -> None:
    hours = [T0 + i * HOUR_MS for i in range(5)]
    d = [apr("0.1"), apr("0.2"), apr("0.3"), apr("0.4"), apr("0.5")]
    assert rolling_apr(d[:3], hours, 3, 3) == (apr("0.1") + apr("0.2") + apr("0.3")) / 3 * HOURS_PER_YEAR
    assert rolling_apr(d[:3], hours, 3, 1) == Decimal("0.3")
    assert rolling_apr(d[:1], hours, 1, 3) is None          # not enough history


def test_decide_refuses_any_future_data() -> None:
    hours = [T0 + i * HOUR_MS for i in range(5)]
    d = [apr("0.5")] * 5
    with pytest.raises(AssertionError):
        decide(2, hours, d, 0, A1, always)                  # full series instead of prefix


@pytest.mark.parametrize("p", grid())
def test_perturbing_future_rates_cannot_change_past_decisions(p: Params) -> None:
    base = [apr(x) for x in ("0.5", "0.4", "0.6", "-0.2", "0.3", "0.45", "0.1", "-0.5", "-0.6", "0.2",
                             "0.7", "0.8", "-0.1", "-0.3", "0.05", "0.9", "0.4", "-0.4", "-0.7", "0.3")] * 3
    rows = rows_from_diffs(base, start=utc_ms(2026, 11, 20, 0))       # Fri 19:00 ET → crosses a weekend
    ref = simulate(rows, p, COST_TIERS["conservative_8.3bps"])
    for j in (5, 17, 33, 50):
        pert = list(base)
        for k in range(j, len(pert)):
            pert[k] = -pert[k] * 7 + apr("1.3")             # wildly different future
        alt = simulate(rows_from_diffs(pert, start=rows[0][0]), p, COST_TIERS["conservative_8.3bps"])
        assert [e for e in ref.events if e[0] <= j] == [e for e in alt.events if e[0] <= j]


def test_position_earns_from_decision_hour_and_forfeits_closing_hour() -> None:
    # diffs: hour0 = 50 % -> decision 1 opens; hour1..3 earn; hour3 negative, hour4 negative -> rolling(K=1) at
    # decision 4 = diff[3] < 0 -> close at 4 (payment 4 not earned).
    d = [apr("0.5"), apr("0.2"), apr("0.3"), apr("-0.1"), apr("-9")]
    r = simulate(rows_from_diffs(d), A1, ZERO_COST)
    assert r.events[0] == (1, "open", 1, "entry")
    assert r.events[1] == (4, "close", 1, "reverted")
    t = r.trades[0]
    assert t.hours == 3 and t.gross == apr("0.2") + apr("0.3") + apr("-0.1")


# ------------------------------------------------------------------------------------------------ entry / exit
def test_entry_threshold_strict_and_direction() -> None:
    d = [apr("0.12"), apr("0.1"), apr("-0.13"), apr("-0.2"), apr("-0.2")]
    r = simulate(rows_from_diffs(d), A1, ZERO_COST)
    assert r.events[0] == (3, "open", -1, "entry")          # 12 % is not > 12 %; −13 % opens SHORT Arcus / LONG HL
    assert r.trades[0].gross == apr("0.2") + apr("0.2")       # short-Arcus receives −diff


def test_exit_apr_4pct_is_direction_aware() -> None:
    p = Params("A", 1, Decimal("0.12"), Decimal("0.04"))
    d = [apr("0.3"), apr("0.05"), apr("0.04"), apr("0.5")]
    r = simulate(rows_from_diffs(d), p, ZERO_COST)
    # decision 1 open (30 %); decision 2: rolling 5 % > 4 % hold; decision 3: rolling 4 % ≤ 4 % -> close
    assert r.events[:2] == [(1, "open", 1, "entry"), (3, "close", 1, "reverted")]


def test_exit_apr_0_means_rolling_crossed_zero() -> None:
    p = Params("A", 3, Decimal("0.12"), Decimal("0"))
    d = [apr("0.5"), apr("0.5"), apr("0.5"), apr("-0.4"), apr("-0.4"), apr("-0.4"), apr("0")]
    r = simulate(rows_from_diffs(d), p, ZERO_COST)
    assert r.events[0] == (3, "open", 1, "entry")
    # decision 4: rolling (0.5+0.5−0.4)/3 > 0 -> hold; decision 5: rolling (0.5−0.4−0.4)/3 < 0 -> crossed zero
    # ('reverted' is checked before 'reversal_2h', which would also fire here)
    assert r.events[1] == (5, "close", 1, "reverted")


def test_reversal_2h_rule_needs_two_consecutive_opposite_hours() -> None:
    p = Params("A", 3, Decimal("0.12"), Decimal("-1"))       # disable 'reverted' to isolate the 2 h rule
    d = [apr("0.9"), apr("0.9"), apr("0.9"), apr("-0.1"), apr("0.2"), apr("-0.1"), apr("0"), apr("-0.1"),
         apr("-0.1"), apr("0.9")]
    r = simulate(rows_from_diffs(d), p, ZERO_COST)
    # -0.1 / +0.2 / -0.1 / 0 (zero is not opposite) / -0.1 / -0.1 -> close at decision 9
    assert [e for e in r.events if e[1] == "close"][0] == (9, "close", 1, "reversal_2h")


def test_no_same_hour_reentry_and_end_of_data_close() -> None:
    d = [apr("0.5"), apr("-0.5"), apr("-0.5"), apr("-0.5")]
    r = simulate(rows_from_diffs(d), A1, ZERO_COST)
    assert r.events == [(1, "open", 1, "entry"), (2, "close", 1, "reverted"), (3, "open", -1, "entry"),
                        (4, "close", -1, "end_of_data")]


def test_data_gap_forces_close_and_blocks_rolling() -> None:
    rows = rows_from_diffs([apr("0.5")] * 3) + [(T0 + 5 * HOUR_MS, Decimal(0), apr("0.5"))]
    r = simulate(rows, A1, ZERO_COST)
    assert (3, "close", 1, "data_gap") in r.events
    assert r.trades[0].hours == 2                            # the payment after the gap is not credited
    assert rolling_apr([apr("0.5")] * 3, [x[0] for x in rows], 3, 1) is None


# ------------------------------------------------------------------------------------------------ window (strategy B)
def test_off_hours_window_regular_weekday_est() -> None:
    # Tue 2026-11-24 (EST, UTC−5): payment stamped 20:00 ET accrues 19–20 (Arcus window) -> not off-hours;
    # 21:00 ET (20–21) -> off-hours; 04:00 ET (03–04) -> off-hours; 05:00 ET (04–05) -> not.
    assert not in_arcus_off_hours(utc_ms(2026, 11, 25, 1))     # 20:00 ET
    assert in_arcus_off_hours(utc_ms(2026, 11, 25, 2))         # 21:00 ET
    assert in_arcus_off_hours(utc_ms(2026, 11, 25, 9))         # 04:00 ET Wed
    assert not in_arcus_off_hours(utc_ms(2026, 11, 25, 10))    # 05:00 ET Wed


def test_off_hours_window_weekend_holiday_half_day_dst() -> None:
    assert in_arcus_off_hours(utc_ms(2026, 11, 21, 17))        # Sat 12:00 ET
    assert in_arcus_off_hours(utc_ms(2026, 11, 26, 17))        # Thanksgiving Thu 12:00 ET (NYSE holiday)
    assert not in_arcus_off_hours(utc_ms(2026, 11, 27, 19))    # Fri half day 14:00 ET: Arcus window stays 04–20
    assert not in_arcus_off_hours(utc_ms(2026, 10, 28, 0))     # Tue 2026-10-27 20:00 EDT (UTC−4) -> in window
    assert in_arcus_off_hours(utc_ms(2026, 10, 28, 1))         # 21:00 EDT -> off-hours
    assert not in_arcus_off_hours(utc_ms(2026, 11, 3, 1))      # Mon 2026-11-02 20:00 EST (UTC−5) after DST end
    assert in_arcus_off_hours(utc_ms(2026, 11, 3, 2))


def test_strategy_b_only_inside_window_and_closes_at_boundary() -> None:
    start = utc_ms(2026, 11, 25, 0)                          # Tue 19:00 ET
    d = [apr("0.5")] * 12                                     # payments 19:00 … 06:00 ET
    p = Params("B", 1, Decimal("0.12"), Decimal("0"))
    r = simulate(rows_from_diffs(d, start=start), p, ZERO_COST)
    # first off-hours payment is 21:00 ET (idx 2) -> open there; first non-window payment is 05:00 ET (idx 10)
    assert r.events[0] == (2, "open", 1, "entry")
    assert r.events[1] == (10, "close", 1, "window_end")
    assert r.trades[0].hours == 8


# ------------------------------------------------------------------------------------------------ costs / ROE
def test_cost_accounting_half_at_open_half_at_close() -> None:
    d = [apr("0.5"), apr("0.5"), apr("-0.5"), apr("0.5"), apr("0.5")]
    rt = COST_TIERS["conservative_8.3bps"]
    r = simulate(rows_from_diffs(d), A1, rt)
    m = metrics(r, Decimal("0.2"))
    assert [t.cost for t in r.trades] == [rt, rt]             # every trade pays a full round trip (incl. forced end)
    assert m["total_cost_bps"] == Decimal("16.6")
    assert m["net_notional_bps"] == m["gross_funding_bps"] - m["total_cost_bps"]
    assert COST_TIERS["optimistic_2.8bps"] * BPS == Decimal("2.8")


def test_margin_and_roe_math() -> None:
    c = margin_per_notional(Decimal("0.075"), Decimal(25))
    assert c["arcus"] == Decimal("0.1125") and c["io"] == Decimal("0.06") and c["total"] == Decimal("0.1725")
    assert margin_per_notional(Decimal("0.30"), Decimal(15))["total"] == Decimal("0.55")
    d = [apr("0.5")] * 11
    r = simulate(rows_from_diffs(d), A1, Decimal("0.0001"))
    m = metrics(r, Decimal("0.2"))
    net = apr("0.5") * 10 - Decimal("0.0001")
    tol = Decimal("1e-30")
    assert abs(m["roe_annualized_pct"] - net / Decimal("0.2") * HOURS_PER_YEAR / 11 * 100) < tol
    assert abs(m["roe_annualized_while_deployed_pct"] - net / Decimal("0.2") * HOURS_PER_YEAR / 10 * 100) < tol
    assert m["max_single_trade_loss_bps"] == 0


def test_portfolio_equal_capital_always_allocated() -> None:
    flat = metrics(simulate(rows_from_diffs([Decimal(0)] * 10), A1, Decimal("0.0001")), Decimal("0.2"))
    act = metrics(simulate(rows_from_diffs([apr("0.5")] * 10), A1, Decimal("0.0001")), Decimal("0.2"))
    pf = portfolio({"X": flat, "Y": act})
    assert flat["opens"] == 0 and flat["roe_annualized_pct"] == 0
    assert pf["roe_annualized_pct_capital_always_allocated"] == act["roe_annualized_pct"] / 2


def test_run_grid_shape() -> None:
    data = {"X": rows_from_diffs([apr("0.5")] * 30)}
    res = run_grid(data, {"X": Decimal("0.2")})
    assert len(res) == 2 * 2 * 4 * 2 * 2


# ------------------------------------------------------------------------------------------------ Decimal only
def test_floats_rejected() -> None:
    with pytest.raises(TypeError):
        simulate([(T0, 0.0, 0.1), (T0 + HOUR_MS, 0.0, 0.1)], A1, ZERO_COST)  # type: ignore[list-item]


@pytest.mark.parametrize("path", ["src/phase0_probe/backtest.py", "scripts/backtest_dynamic_funding.py"])
def test_no_float_literals_or_calls(path: str) -> None:
    tree = ast.parse((ROOT / path).read_text())
    for node in ast.walk(tree):
        assert not (isinstance(node, ast.Constant) and isinstance(node.value, float)), f"float literal in {path}"
        assert not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float")


@pytest.mark.parametrize("path", ["src/phase0_probe/backtest.py", "scripts/backtest_dynamic_funding.py"])
def test_no_order_or_signing_code(path: str) -> None:
    text = (ROOT / path).read_text().lower()
    for bad in ("private_key", "sign_l1", "eth_account", "/exchange", "secret", "place_order", "api_key"):
        assert bad not in text
