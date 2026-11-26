"""VWAP + net-profit model (Decimal only), incl. insufficient depth and stale (> 500 ms) edge cases."""
from __future__ import annotations

from decimal import Decimal

import pytest

from phase0_probe.book import OrderBook
from phase0_probe.model import Direction, Mode, VenueSpec, annualized_funding_diff, evaluate, vwap

D = Decimal
NOW = 1_800_000_000_000
SPEC_A = VenueSpec("arcus", "BTC", D("0.00000001"), D(5), D("0.00015"), D("0.00045"))
SPEC_B = VenueSpec("hyperliquid", "BTC", D("0.00001"), D(10), D("0.00015"), D("0.00045"))


def book(venue: str, bids: list[tuple[str, str]], asks: list[tuple[str, str]], age_ms: int = 100) -> OrderBook:
    b = OrderBook(venue, "BTC")
    b.replace([(D(p), D(s)) for p, s in bids], [(D(p), D(s)) for p, s in asks])
    b.valid, b.confirmed_ms = True, NOW - age_ms
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
                mode=Mode.DUAL_TAKER, now_ms=NOW)
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


@pytest.mark.parametrize("age_a,age_b,status", [(500, 0, "ok"), (501, 0, "stale"), (0, 501, "stale"),
                                                 (0, 500, "ok"), (10_000, 10_000, "stale")])
def test_stale_boundary_500ms(age_a: int, age_b: int, status: str) -> None:
    a = book("arcus", [("59999", "5")], [("60001", "5")], age_ms=age_a)
    b = book("hyperliquid", [("60299", "5")], [("60301", "5")], age_ms=age_b)
    o = _eval(a, b)
    assert o.status == status and (o.is_opportunity is (status == "ok"))
    assert o.age_a_ms == age_a and o.age_b_ms == age_b


def test_invalid_or_never_confirmed_book_is_stale() -> None:
    a, b = _ab("60300")
    b.valid = False
    assert _eval(a, b).status == "stale"
    a2, b2 = _ab("60300")
    a2.confirmed_ms = None
    assert _eval(a2, b2).status == "stale"


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
