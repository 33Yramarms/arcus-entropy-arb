"""VWAP + net-profit model (Decimal only).

Per (symbol, Q, direction, mode) and per second:

* ``base`` = Q / ref_mid floored to the coarser lot step of the two venues (both legs trade the same base size).
* Open: buy ``base`` on the BUY venue, sell ``base`` on the SELL venue. A TAKER leg walks the L2 book (VWAP); a MAKER
  leg is priced at its own-side touch (buy at best bid / sell at best ask) — optimistic: queue position and fill
  probability are NOT modelled (Phase 0 upper bound for the maker leg).
* ``open_spread_bps`` = (sell_px − buy_px) / ref_mid.
* Close (the reverse trades) is priced on the CURRENT books the same way, under the convergence assumption: the
  inter-venue mid basis goes to zero by the exit, so the PnL is the open spread minus what crossing back costs
  relative to each venue's mid (``close_slip_bps``).
* ``fees_bps`` = open + close fee on both legs (taker or maker rate per leg; negative maker fee = rebate).
* ``net_bps`` = open_spread_bps − close_slip_bps − fees_bps − buffer_bps (default 2 bps execution-risk buffer).
* PR #1.5 — residual spread: the exit no longer assumes the absolute basis closes to zero. With
  ``m`` = rolling median of the mid basis (HL − Arcus, bps) over the previous window, the expected exit happens at
  basis ``m``: ``net_resid_bps = net_bps − m`` for BUY_ARCUS_SELL_HL and ``net_bps + m`` for BUY_HL_SELL_ARCUS
  (``residual_bps`` = basis − m). Opportunities are judged on ``net_resid_bps``; ``net_bps`` (zero-convergence) is kept
  only for comparison with Phase 0.
* Status (PR #1.5): ``not_ready`` if either book is not ready (no snapshot / gap / Arcus resync or unproven baseline)
  → evaluation skipped; ``stale`` if either venue's ``network_latency_ms`` (local recv − exchange timestamp of the
  latest timestamped frame) > max_latency_ms (default 500) or its connection has been silent > conn_timeout_ms.
  ``book_idle_ms`` (no book change) is recorded but does NOT gate: a quiet book on a healthy connection is current.
  ``insufficient_depth`` if a taker leg cannot be filled from the visible levels; ``below_min_notional`` if a leg is
  under a venue minimum. Only ``ok`` rows can be opportunities. The last trade price is never used anywhere.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from phase0_probe.book import Level, OrderBook
from phase0_probe.dec import BPS, TWO, ZERO, floor_to_step


class Direction(StrEnum):
    BUY_A_SELL_B = "BUY_ARCUS_SELL_HL"
    BUY_B_SELL_A = "BUY_HL_SELL_ARCUS"


class Mode(StrEnum):
    DUAL_TAKER = "DUAL_TAKER"
    MAKER_A = "MAKER_ARCUS_TAKER_HL"      # Maker-Taker: rest on Arcus, hedge as taker on Hyperliquid
    MAKER_B = "MAKER_HL_TAKER_ARCUS"      # Maker-Taker: rest on Hyperliquid, hedge as taker on Arcus


@dataclass(frozen=True)
class VenueSpec:
    venue: str
    symbol: str
    step: Decimal                 # lot size
    min_notional: Decimal         # quote units (0 = unknown / none)
    maker_fee: Decimal            # fraction, e.g. 0.00015 (negative = rebate)
    taker_fee: Decimal


@dataclass(frozen=True)
class Vwap:
    price: Decimal
    worst_price: Decimal
    levels_used: int


def vwap(levels: list[Level], base_qty: Decimal) -> Vwap | None:
    """Volume-weighted average price to fill ``base_qty`` walking ``levels`` (best first). None if too shallow."""
    if base_qty <= ZERO:
        raise ValueError("base_qty must be positive")
    remaining, cost, used, worst = base_qty, ZERO, 0, ZERO
    for px, sz in levels:
        if sz <= ZERO:
            continue
        take = sz if sz < remaining else remaining
        cost += take * px
        remaining -= take
        used += 1
        worst = px
        if remaining == ZERO:
            return Vwap(cost / base_qty, worst, used)
    return None


@dataclass(frozen=True)
class Opportunity:
    symbol: str
    q_usd: Decimal
    direction: Direction
    mode: Mode
    status: str                   # ok | not_ready | stale | insufficient_depth | below_min_notional | no_mid
    base_qty: Decimal | None = None
    mid_a: Decimal | None = None
    mid_b: Decimal | None = None
    ref_mid: Decimal | None = None
    basis_bps: Decimal | None = None          # (mid_HL − mid_Arcus) / ref
    open_buy_px: Decimal | None = None
    open_sell_px: Decimal | None = None
    open_spread_bps: Decimal | None = None
    open_slip_bps: Decimal | None = None      # open cost vs each venue's own mid (negative for maker legs)
    close_slip_bps: Decimal | None = None
    fees_bps: Decimal | None = None
    buffer_bps: Decimal | None = None
    net_bps: Decimal | None = None
    net_usd: Decimal | None = None
    basis_median_bps: Decimal | None = None   # rolling median of basis over the previous window (None = warm-up)
    residual_bps: Decimal | None = None       # basis − rolling median
    net_resid_bps: Decimal | None = None      # net assuming exit at the rolling-median basis (primary metric)
    lat_a_ms: int | None = None               # network_latency_ms per venue
    lat_b_ms: int | None = None
    idle_a_ms: int | None = None              # book_idle_ms per venue (diagnostic only)
    idle_b_ms: int | None = None
    silence_a_ms: int | None = None           # connection silence per venue
    silence_b_ms: int | None = None

    @property
    def is_opportunity(self) -> bool:
        return self.status == "ok" and self.net_resid_bps is not None and self.net_resid_bps > ZERO

    @property
    def is_zero_convergence_opportunity(self) -> bool:
        """Phase 0 definition (assumes the basis closes to 0) — kept for comparison only."""
        return self.status == "ok" and self.net_bps is not None and self.net_bps > ZERO


class RollingMedian:
    """Median of the values seen in the last ``window_ms`` (strictly before the query time). Decimal only."""

    def __init__(self, window_ms: int, min_samples: int = 30) -> None:
        self.window_ms, self.min_samples = window_ms, min_samples
        self.items: deque[tuple[int, Decimal]] = deque()

    def _trim(self, now_ms: int) -> None:
        while self.items and self.items[0][0] <= now_ms - self.window_ms:
            self.items.popleft()

    def median(self, now_ms: int) -> Decimal | None:
        self._trim(now_ms)
        vals = sorted(v for t, v in self.items if t < now_ms)
        if len(vals) < self.min_samples:
            return None
        n = len(vals)
        return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / TWO

    def push(self, ts_ms: int, value: Decimal) -> None:
        self.items.append((ts_ms, value))
        self._trim(ts_ms)


def mid_basis_bps(book_a: OrderBook, book_b: OrderBook) -> Decimal | None:
    """(mid_HL − mid_Arcus) / ref_mid in bps, or None if a book is not ready / has no mid."""
    if not book_a.ready or not book_b.ready:
        return None
    ma, mb = book_a.mid(), book_b.mid()
    if ma is None or mb is None:
        return None
    return (mb - ma) / ((ma + mb) / TWO) * BPS


def _leg_price(book: OrderBook, buy: bool, maker: bool, base: Decimal) -> Decimal | None:
    if maker:
        return book.best_bid() if buy else book.best_ask()
    v = vwap(book.sorted_asks() if buy else book.sorted_bids(), base)
    return None if v is None else v.price


def evaluate(*, book_a: OrderBook, book_b: OrderBook, spec_a: VenueSpec, spec_b: VenueSpec, q_usd: Decimal,
             direction: Direction, mode: Mode, now_ms: int, max_latency_ms: int = 500, conn_timeout_ms: int = 5000,
             buffer_bps: Decimal = Decimal(2), basis_median_bps: Decimal | None = None) -> Opportunity:
    """A = Arcus, B = Hyperliquid. Pure function: same inputs, same output."""
    sym = spec_a.symbol
    sil_a, sil_b = book_a.silence_ms(now_ms), book_b.silence_ms(now_ms)
    base_kw = dict(symbol=sym, q_usd=q_usd, direction=direction, mode=mode, buffer_bps=buffer_bps,
                   lat_a_ms=book_a.latency_ms, lat_b_ms=book_b.latency_ms, idle_a_ms=book_a.idle_ms(now_ms),
                   idle_b_ms=book_b.idle_ms(now_ms), silence_a_ms=sil_a, silence_b_ms=sil_b,
                   basis_median_bps=basis_median_bps)
    if not book_a.ready or not book_b.ready:
        return Opportunity(status="not_ready", **base_kw)            # skip: no arbitrage maths on an unproven book
    lat_bad = any(x is None or x > max_latency_ms for x in (book_a.latency_ms, book_b.latency_ms))
    conn_bad = any(x is None or x > conn_timeout_ms for x in (sil_a, sil_b))
    if lat_bad or conn_bad:
        return Opportunity(status="stale", **base_kw)
    mid_a, mid_b = book_a.mid(), book_b.mid()
    if mid_a is None or mid_b is None:
        return Opportunity(status="no_mid", **base_kw)
    ref = (mid_a + mid_b) / TWO
    step = max(spec_a.step, spec_b.step)
    base = floor_to_step(q_usd / ref, step)
    basis = (mid_b - mid_a) / ref * BPS
    common = dict(base_qty=base, mid_a=mid_a, mid_b=mid_b, ref_mid=ref, basis_bps=basis, **base_kw)
    if base <= ZERO or base * ref < max(spec_a.min_notional, spec_b.min_notional):
        return Opportunity(status="below_min_notional", **common)

    buy_book, sell_book = (book_a, book_b) if direction is Direction.BUY_A_SELL_B else (book_b, book_a)
    buy_spec, sell_spec = (spec_a, spec_b) if direction is Direction.BUY_A_SELL_B else (spec_b, spec_a)
    maker_a, maker_b = mode is Mode.MAKER_A, mode is Mode.MAKER_B
    buy_is_a = direction is Direction.BUY_A_SELL_B
    buy_maker = maker_a if buy_is_a else maker_b
    sell_maker = maker_b if buy_is_a else maker_a

    open_buy = _leg_price(buy_book, True, buy_maker, base)
    open_sell = _leg_price(sell_book, False, sell_maker, base)
    close_sell = _leg_price(buy_book, False, buy_maker, base)       # unwind the long on the buy venue
    close_buy = _leg_price(sell_book, True, sell_maker, base)       # unwind the short on the sell venue
    if None in (open_buy, open_sell, close_sell, close_buy):
        return Opportunity(status="insufficient_depth", **common)
    assert open_buy is not None and open_sell is not None and close_sell is not None and close_buy is not None
    mid_buy, mid_sell = buy_book.mid(), sell_book.mid()
    assert mid_buy is not None and mid_sell is not None

    open_spread = (open_sell - open_buy) / ref * BPS
    open_slip = ((open_buy - mid_buy) / mid_buy + (mid_sell - open_sell) / mid_sell) * BPS
    close_slip = ((mid_buy - close_sell) / mid_buy + (close_buy - mid_sell) / mid_sell) * BPS
    fee_buy = buy_spec.maker_fee if buy_maker else buy_spec.taker_fee
    fee_sell = sell_spec.maker_fee if sell_maker else sell_spec.taker_fee
    fees = TWO * (fee_buy + fee_sell) * BPS                          # open + close, both legs
    net = open_spread - close_slip - fees - buffer_bps
    notional = base * ref
    resid = net_resid = None
    if basis_median_bps is not None:
        resid = basis - basis_median_bps
        net_resid = net - basis_median_bps if buy_is_a else net + basis_median_bps
    return Opportunity(status="ok", open_buy_px=open_buy, open_sell_px=open_sell, open_spread_bps=open_spread,
                       open_slip_bps=open_slip, close_slip_bps=close_slip, fees_bps=fees, net_bps=net,
                       net_usd=net / BPS * notional, residual_bps=resid, net_resid_bps=net_resid, **common)


def annualized_funding_diff(rate_hl_hourly: Decimal | None, rate_arcus_hourly: Decimal | None) -> Decimal | None:
    """(HL − Arcus) hourly rate × 8760. Positive: long Arcus / short HL RECEIVES carry (longs pay positive rates on
    both venues: docs.arcus.xyz/concepts/perpetuals/funding.md, hyperliquid-docs/trading/funding.md)."""
    if rate_hl_hourly is None or rate_arcus_hourly is None:
        return None
    return (rate_hl_hourly - rate_arcus_hourly) * Decimal(24 * 365)
