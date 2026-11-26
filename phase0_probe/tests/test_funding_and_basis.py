"""PR #1.5: funding conversion, basis decomposition, funding-history statistics, HL feed health fields."""
from __future__ import annotations

from decimal import Decimal

from phase0_probe.discovery import parse_predicted
from phase0_probe.feeds import HlBookFeed
from phase0_probe.funding import (align_hourly, decompose_basis, direction_stats, hl_hourly_from_premium,
                                  hours_to_breakeven, runs_positive, sign_flips)

D = Decimal


# ----------------------------------------------------------------------------------------------- conversions
def test_hl_hourly_formula_matches_live_fundinghistory_rows() -> None:
    """Rows captured live 2026-11-27 from POST /info fundingHistory (BTC): the documented 8 h formula / 8 reproduces
    ``fundingRate`` to its 10 printed decimals -> the field is an HOURLY decimal fraction (not %, not 8 h)."""
    rows = [("-0.0005522544", "-0.0000065318"), ("-0.0005795452", "-0.0000099432"), ("-0.0011136916", "-0.0000767115"),
            ("-0.0004723063", "0.0000034617"), ("-0.0004491142", "0.0000063607")]
    for prem, rate in rows:
        assert abs(hl_hourly_from_premium(D(prem)) - D(rate)) <= D("1e-10")      # API prints 10 decimals


def test_hl_base_rate_when_premium_zero_is_arcus_crypto_base() -> None:
    assert hl_hourly_from_premium(D(0)) == D("0.0000125") == D("0.0001") / 8


def test_predicted_fundings_normalised_by_interval() -> None:
    body = [["BTC", [["BinPerp", {"fundingRate": "0.0001", "fundingIntervalHours": 8}],
                     ["HlPerp", {"fundingRate": "-0.0000012329", "fundingIntervalHours": 1}]]],
            ["X", [["HlPerp", {"fundingRate": "0.00008", "fundingIntervalHours": 8}]]]]
    p = parse_predicted(body)
    assert p["BTC"] == D("-0.0000012329") and p["X"] == D("0.00001")


def test_sign_convention_short_arcus_long_hl() -> None:
    """Both venues: positive rate => longs pay shorts. Short Arcus receives +A, long HL pays +H: carry = A − H."""
    a, h = D("0.0000125"), D("-0.0000020")
    carry_short_a_long_h = a - h
    assert carry_short_a_long_h > 0 and (h - a) * 8760 == -carry_short_a_long_h * 8760


# ----------------------------------------------------------------------------------------------- basis
def test_basis_decomposition_is_exact_and_attributes_oracle_vs_book() -> None:
    d = decompose_basis(D("60546.1"), D("60551.95"), D("60620.0"), D("60588.50"))
    assert abs(d.oracle_diff_bps + d.book_premium_diff_bps - d.mid_diff_bps) < D("1e-30")   # 40-digit context
    assert d.oracle_diff_bps > D(12) and d.book_premium_diff_bps < 0          # static oracle gap, HL book below it
    z = decompose_basis(D(100), D(100), D(100), D("100.1"))
    assert z.oracle_diff_bps == 0 and z.book_premium_diff_bps == z.mid_diff_bps == D(10)
    assert d.hl_premium_bps < 0


# ----------------------------------------------------------------------------------------------- history stats
def test_align_hourly_buckets_and_intersects() -> None:
    h = 3_600_000
    a = [(10 * h, D(1)), (11 * h, D(2)), (12 * h, D(3))]
    b = [(10 * h + 76, D(5)), (12 * h + 30, D(7)), (13 * h + 1, D(9))]
    assert align_hourly(a, b) == [(10 * h, D(1), D(5)), (12 * h, D(3), D(7))]


def test_runs_flips_and_breakeven() -> None:
    xs = [D(1), D(1), D(0), D(-1), D(2), D(2), D(2), D(0), D(1)]
    assert runs_positive(xs) == [2, 3, 1]
    assert sign_flips(xs) == 2                                              # + -> - -> + (zeros keep the sign)
    assert hours_to_breakeven([D(1), D(1), D(1)], D(2)) == 2
    assert hours_to_breakeven([D(1), D(-1)], D(2)) is None


def test_direction_stats_numbers() -> None:
    carry = [D("0.0001"), D("0.0001"), D("-0.00005"), D("0.0001")]
    st = direction_stats(carry, {"DUAL_TAKER": D("0.0018"), "MAKER": D("0.0002")})
    assert st["hours"] == 4 and st["mean_hourly"] == D("0.0000625")
    assert st["annualized"] == D("0.0000625") * 8760 and st["daily_mean"] == D("0.0000625") * 24
    assert st["longest_positive_run_h"] == 2 and st["sign_flips"] == 2
    dt, mk = st["by_fee_mode"]["DUAL_TAKER"], st["by_fee_mode"]["MAKER"]
    assert dt["breakeven_h_entering_at_window_start"] is None and dt["rolling_entries_breaking_even"] == 0
    assert dt["net_pnl_hold_whole_window_bps"] == (D("0.00025") - D("0.0018")) * 10_000
    assert mk["breakeven_h_entering_at_window_start"] == 2 and mk["expected_breakeven_h"] == D("0.0002") / D("0.0000625")
    neg = direction_stats([-c for c in carry], {"DUAL_TAKER": D("0.0018")})
    assert neg["by_fee_mode"]["DUAL_TAKER"]["expected_breakeven_h"] is None


# ----------------------------------------------------------------------------------------------- HL feed health
def test_hl_feed_latency_idle_and_pong_liveness() -> None:
    f = HlBookFeed("BTC", "BTC", lambda *a: None)
    snap = {"coin": "BTC", "time": 1_000, "levels": [[{"px": "100", "sz": "1", "n": 1}],
                                                     [{"px": "101", "sz": "1", "n": 1}]]}
    f.handle({"channel": "l2", "data": {"s": snap}}, 1_300)
    assert f.book.latency_ms == 300 and f.book.last_change_ms == 1_300 and f.book.ready
    f.handle({"channel": "l2", "data": {"u": {"c": "BTC", "t": 2_000, "l": [[], []], "r": [[], []]}}}, 2_250)
    assert f.book.latency_ms == 250 and f.book.last_change_ms == 1_300        # empty diff: no book change
    f.handle({"channel": "pong"}, 9_000)
    assert f.book.last_msg_ms == 9_000 and f.book.idle_ms(9_000) == 7_700 and f.book.silence_ms(9_000) == 0
    f.handle({"channel": "l2Book", "data": {"coin": "BTC", "time": 8_000, "levels": snap["levels"]}}, 8_400)
    assert f.book.latency_ms == 400                                          # l2Book frames measure latency too
