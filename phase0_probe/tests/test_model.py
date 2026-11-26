"""VWAP + net-profit model (Decimal only), incl. insufficient depth, network-latency staleness (> 500 ms),
NOT_READY gating, book idleness (never gates) and the rolling-median residual spread (PR #1.5)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from phase0_probe.book import OrderBook
from phase0_probe.model import (Direction, Mode, RollingMedian, VenueSpec, annualized_funding_diff, evaluate,
                                 mid_basis_bps, vwap)

D = Decimal
NOW = 1_800_000_000_000
SPEC_A = VenueSpec("arcus", "BTC", D("0.00000001"), D(5), D("0.00015"), D("0.00045"))
SPEC_B = VenueSpec("hyperliquid", "BTC", D("0.00001"), D(10), D("0.00015"), D("0.00045"))


def book(venue: str, bids: list[tuple[str, str]], asks: list[tuple[str, str]], latency_ms: int | None = 100,
         idle_ms: int = 100, silence_ms: int = 100) -> OrderBook:
    b = OrderBook(venue, "BTC")
    b.replace([(D(p), D(s)) for p, s in bids], [(D(p), D(s)) for p, s in asks])
    b.valid, b.confirmed_ms, b.latency_ms = True, NOW - idle_ms, latency_ms
    b.last_change_ms, b.last_msg_ms = NOW - idle_ms, NOW - silence_ms
    return b


# ----------------------------------------------------------------------------------------------- VWAP
def test_vwap_single_level() -> None:
    v = vwap([(D(100), D(5))], D(2))
    assert v is not None and v.price == D(100) and v.levels_used == 1 and v.worst_price == D(100)


def test_vwap_walks_levels_exactly() -> None:
    v = vwap([(D(100), D(1)), (D(101), D(1)), (D(103), D(10))], D(3))
    assert v is not None and v.price == (D(100) + D(101) + D(103)) / D(3) and v.levels_used == 3
    assert v.worst_price == D(103)


def test_vwap_exact_depth_is_enough() -> None:
    v = vwap([(D("10.5"), D("0.4")), (D("10.6"), D("0.6"))], D(1))
    assert v is not None and v.price == D("10.56")


def test_vwap_insufficient_depth_returns_none() -> None:
    assert vwap([(D(100), D(1)), (D(101), D(1))], D("2.00000001")) is None
    assert vwap([], D(1)) is None


def test_vwap_skips_zero_levels_and_rejects_non_positive_qty() -> None:
    v = vwap([(D(100), D(0)), (D(101), D(2))], D(1))
    assert v is not None and v.price == D(101)
    with pytest.raises(ValueError):
        vwap([(D(100), D(1))], D(0))


def test_vwap_returns_decimal_only() -> None:
    v = vwap([(D("60000.1"), D("0.3")), (D("60000.7"), D("0.2"))], D("0.4"))
    assert v is not None and isinstance(v.price, Decimal)


# ----------------------------------------------------------------------------------------------- net model
def _ab(spread_b: str = "60030") -> tuple[OrderBook, OrderBook]:
    a = book("arcus", [("59999", "5")], [("60001", "5")])                   # mid 60000
    hb = D(spread_b)
    b = book("hyperliquid", [(str(hb - 1), "5")], [(str(hb + 1), "5")])      # mid = spread_b
    return a, b


def _eval(a: OrderBook, b: OrderBook, **kw: object) -> object:
    args = dict(book_a=a, book_b=b, spec_a=SPEC_A, spec_b=SPEC_B, q_usd=D(500), direction=Direction.BUY_A_SELL_B,
                mode=Mode.DUAL_TAKER, now_ms=NOW, basis_median_bps=D(0))
    args.update(kw)
    return evaluate(**args)  # type: ignore[arg-type]


def test_dual_taker_net_formula_exact() -> None:
    a, b = _ab("60030")
    o = _eval(a, b)
    ref = D(60015)
    base = (D(500) / ref).quantize(D("0.00001"), rounding="ROUND_DOWN")
    assert o.status == "ok" and o.base_qty == base
    assert o.open_buy_px == D(60001) and o.open_sell_px == D(60029)
    assert o.open_spread_bps == (D(60029) - D(60001)) / ref * 10000
    close = ((D(60000) - D(59999)) / D(60000) + (D(60031) - D(60030)) / D(60030)) * 10000
    assert o.close_slip_bps == close
    assert o.fees_bps == D(2) * (D("0.00045") + D("0.00045")) * 10000 == D(18)
    assert o.net_bps == o.open_spread_bps - close - D(18) - D(2)
    assert o.net_usd == o.net_bps / 10000 * (base * ref)
    assert o.basis_bps == D(30) / ref * 10000


def test_no_basis_means_negative_net_dual_taker() -> None:
    a, b = _ab("60000")
    o = _eval(a, b)
    assert o.status == "ok" and o.net_bps < 0 and not o.is_opportunity


def test_large_basis_is_an_opportunity_and_reverse_direction_is_not() -> None:
    a, b = _ab("60300")                                                     # ~50 bps HL premium
    o = _eval(a, b)
    r = _eval(a, b, direction=Direction.BUY_B_SELL_A)
    assert o.is_opportunity and o.net_bps > D(25)
    assert r.status == "ok" and not r.is_opportunity and r.open_spread_bps < 0


def test_buffer_bps_is_subtracted() -> None:
    a, b = _ab("60300")
    o2 = _eval(a, b)
    o0 = _eval(a, b, buffer_bps=D(0))
    assert o0.net_bps - o2.net_bps == D(2)


def test_maker_taker_uses_touch_and_maker_fee() -> None:
    a, b = _ab("60030")
    o = _eval(a, b, mode=Mode.MAKER_A)
    assert o.open_buy_px == D(59999)                                       # Arcus maker leg joins the bid
    assert o.open_sell_px == D(60029)                                      # HL taker hits the bid
    assert o.fees_bps == D(2) * (D("0.00015") + D("0.00045")) * 10000 == D(12)
    dt = _eval(a, b)
    assert o.net_bps > dt.net_bps                                          # cheaper than dual taker here


def test_maker_b_mode_puts_hl_on_the_touch() -> None:
    a, b = _ab("60030")
    o = _eval(a, b, mode=Mode.MAKER_B)
    assert o.open_buy_px == D(60001) and o.open_sell_px == D(60031)        # HL maker sells at its ask


def test_negative_maker_fee_is_a_rebate() -> None:
    a, b = _ab("60030")
    spec = VenueSpec("arcus", "BTC", D("0.00000001"), D(5), D("-0.00002"), D("0.00045"))
    o = _eval(a, b, spec_a=spec, mode=Mode.MAKER_A)
    assert o.fees_bps == D(2) * (D("-0.00002") + D("0.00045")) * 10000


def test_insufficient_depth_is_never_an_opportunity() -> None:
    a = book("arcus", [("59999", "0.001")], [("60001", "0.001")])          # $60 of depth
    b = book("hyperliquid", [("60500", "5")], [("60502", "5")])           # huge basis
    o = _eval(a, b, q_usd=D(2000))
    assert o.status == "insufficient_depth" and o.net_bps is None and not o.is_opportunity
    small = _eval(a, b, q_usd=D(50))
    assert small.status == "ok" and small.is_opportunity


def test_insufficient_depth_on_close_leg_counts_too() -> None:
    a = book("arcus", [("59999", "0.0001")], [("60001", "5")])            # thin bid = thin close for a long
    b = book("hyperliquid", [("60500", "5")], [("60502", "5")])
    assert _eval(a, b, q_usd=D(500)).status == "insufficient_depth"


@pytest.mark.parametrize("lat_a,lat_b,status", [(500, 0, "ok"), (501, 0, "stale"), (0, 501, "stale"),
                                                 (0, 500, "ok"), (10_000, 10_000, "stale"), (None, 0, "stale")])
def test_network_latency_boundary_500ms(lat_a: int | None, lat_b: int, status: str) -> None:
    a = book("arcus", [("59999", "5")], [("60001", "5")], latency_ms=lat_a)
    b = book("hyperliquid", [("60299", "5")], [("60301", "5")], latency_ms=lat_b)
    o = _eval(a, b)
    assert o.status == status and (o.is_opportunity is (status == "ok"))
    assert o.lat_a_ms == lat_a and o.lat_b_ms == lat_b
    if status == "stale":
        assert o.net_bps is None and o.net_resid_bps is None


def test_idle_book_on_healthy_connection_is_not_stale() -> None:
    """A book that has not changed for 60 s is current if the link is healthy (latency OK, frames arriving)."""
    a = book("arcus", [("59999", "5")], [("60001", "5")], idle_ms=60_000, silence_ms=200)
    b = book("hyperliquid", [("60299", "5")], [("60301", "5")], idle_ms=45_000, silence_ms=900)
    o = _eval(a, b)
    assert o.status == "ok" and o.is_opportunity
    assert o.idle_a_ms == 60_000 and o.idle_b_ms == 45_000             # recorded as a diagnostic only


@pytest.mark.parametrize("sil_a,sil_b,status", [(5000, 0, "ok"), (5001, 0, "stale"), (0, 5001, "stale")])
def test_silent_connection_is_stale(sil_a: int, sil_b: int, status: str) -> None:
    a = book("arcus", [("59999", "5")], [("60001", "5")], silence_ms=sil_a)
    b = book("hyperliquid", [("60299", "5")], [("60301", "5")], silence_ms=sil_b)
    assert _eval(a, b, conn_timeout_ms=5000).status == status


def test_not_ready_books_skip_the_arbitrage_calculation() -> None:
    for mutate in (lambda x: setattr(x, "valid", False), lambda x: setattr(x, "provisional", True)):
        a, b = _ab("60300")
        mutate(a)
        o = _eval(a, b)
        assert o.status == "not_ready" and not o.is_opportunity
        assert o.base_qty is None and o.mid_a is None and o.net_bps is None and o.net_resid_bps is None
        assert mid_basis_bps(a, b) is None
    a, b = _ab("60300")
    b.valid = False
    assert _eval(a, b).status == "not_ready"


def test_not_ready_wins_over_stale() -> None:
    a, b = _ab("60300")
    a.provisional, b.latency_ms = True, 99_999
    assert _eval(a, b).status == "not_ready"


# ----------------------------------------------------------------------------------------------- residual spread
def test_residual_net_subtracts_rolling_median_by_direction() -> None:
    a, b = _ab("60300")
    m = D(40)
    o = _eval(a, b, basis_median_bps=m)
    r = _eval(a, b, basis_median_bps=m, direction=Direction.BUY_B_SELL_A)
    assert o.net_resid_bps == o.net_bps - m and r.net_resid_bps == r.net_bps + m
    assert o.residual_bps == o.basis_bps - m == r.residual_bps


def test_persistent_basis_is_not_an_opportunity_any_more() -> None:
    """Phase 0 flagged a stable 50 bps basis as profit; with exit at the rolling median (= the same 50 bps) it is not."""
    a, b = _ab("60300")
    zero_conv = _eval(a, b)
    o = _eval(a, b, basis_median_bps=zero_conv.basis_bps)
    assert zero_conv.is_zero_convergence_opportunity
    assert o.is_zero_convergence_opportunity and not o.is_opportunity and o.net_resid_bps < 0
    assert o.residual_bps == 0


def test_warmup_without_median_is_never_an_opportunity() -> None:
    a, b = _ab("60300")
    o = _eval(a, b, basis_median_bps=None)
    assert o.status == "ok" and o.net_resid_bps is None and o.residual_bps is None and not o.is_opportunity


def test_rolling_median_window_min_samples_and_no_lookahead() -> None:
    rm = RollingMedian(window_ms=5_000, min_samples=3)
    rm.push(1_000, D(1))
    rm.push(2_000, D(5))
    assert rm.median(3_000) is None                                     # 2 < min_samples
    rm.push(3_000, D(3))
    assert rm.median(3_000) is None                                     # the current second is excluded
    assert rm.median(3_001) == D(3)
    rm.push(4_000, D(4))
    assert rm.median(4_001) == (D(3) + D(4)) / 2
    assert rm.median(7_500) is None                                     # 1 s, 2 s fell out: 2 samples < 3
    rm2 = RollingMedian(window_ms=2_000, min_samples=1)
    rm2.push(0, D(100))
    rm2.push(1_000, D(7))
    assert rm2.median(2_500) == D(7)


def test_crossed_or_empty_book_has_no_mid() -> None:
    a = book("arcus", [("60002", "5")], [("60001", "5")])
    b = book("hyperliquid", [("60299", "5")], [("60301", "5")])
    assert _eval(a, b).status == "no_mid"
    e = book("arcus", [], [("60001", "5")])
    assert _eval(e, b).status == "no_mid"


def test_below_min_notional() -> None:
    a, b = _ab("60030")
    assert _eval(a, b, q_usd=D(9)).status == "below_min_notional"           # HL min 10


def test_lot_step_floors_base_to_coarser_step() -> None:
    a, b = _ab("60030")
    o = _eval(a, b, q_usd=D(100))
    assert o.base_qty == D("0.00166") and o.base_qty % D("0.00001") == 0


def test_funding_differential_annualised() -> None:
    assert annualized_funding_diff(D("0.0000125"), D("0.0000025")) == D("0.00001") * 8760 == D("0.0876")
    assert annualized_funding_diff(None, D(0)) is None
