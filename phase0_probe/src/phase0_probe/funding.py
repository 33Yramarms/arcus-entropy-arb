"""Funding-rate conversion, basis decomposition and historical funding statistics (Decimal only, pure functions).

Conventions (documented):
* Arcus: ``fundingRate`` / ``nextFundingRate`` on GET /v1/markets and ``fundingRate`` on GET /v1/fundingRates are
  HOURLY rates as decimal fractions ("Hourly funding rate (decimal string)", api-reference/public/
  get-market-funding-rates.md); charged once an hour; positive => longs pay shorts (concepts/perpetuals/funding.md).
* Hyperliquid: the 8-hour formula ``F = P + clamp(0.0001 − P, −0.0005, 0.0005)`` is paid every hour at F/8; positive
  => longs pay shorts (trading/funding.md). ``fundingHistory`` / asset-ctx ``funding`` / ``predictedFundings`` HlPerp
  (``fundingIntervalHours`` = 1) are hourly fractions (verified numerically: ``hl_hourly_from_premium``).
* Carry for SHORT Arcus + LONG HL per hour = arcus_rate − hl_rate (short receives the Arcus rate, long pays the HL
  rate). Phase 0's "Δ = HL − Arcus" is exactly the negative of that carry.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable

from phase0_probe.dec import BPS, HOURS_PER_YEAR, ZERO

HOUR_MS = 3_600_000
HL_INTEREST_8H = Decimal("0.0001")            # 0.01 % per 8 h (trading/funding.md)
HL_CLAMP_8H = Decimal("0.0005")
EIGHT = Decimal(8)


def clamp(x: Decimal, lo: Decimal, hi: Decimal) -> Decimal:
    return lo if x < lo else hi if x > hi else x


def hl_hourly_from_premium(premium: Decimal, interest_8h: Decimal = HL_INTEREST_8H,
                           clamp_8h: Decimal = HL_CLAMP_8H) -> Decimal:
    """HL hourly rate from the (hour-averaged) premium: (P + clamp(r − P, ±0.0005)) / 8."""
    return (premium + clamp(interest_8h - premium, -clamp_8h, clamp_8h)) / EIGHT


def annualize_hourly(rate_hourly: Decimal) -> Decimal:
    return rate_hourly * HOURS_PER_YEAR


# ------------------------------------------------------------------------------------------------ basis
@dataclass(frozen=True)
class BasisDecomposition:
    oracle_diff_bps: Decimal          # (HL_oracle − Arcus_oracle) / Arcus_oracle
    book_premium_diff_bps: Decimal    # ((HL_mid − HL_oracle) − (Arcus_mid − Arcus_oracle)) / Arcus_oracle
    mid_diff_bps: Decimal             # (HL_mid − Arcus_mid) / Arcus_oracle  (= the two above, exactly)
    hl_premium_bps: Decimal           # (HL_mid − HL_oracle) / HL_oracle
    arcus_premium_bps: Decimal        # (Arcus_mid − Arcus_oracle) / Arcus_oracle


def decompose_basis(arcus_oracle: Decimal, arcus_mid: Decimal, hl_oracle: Decimal, hl_mid: Decimal) -> BasisDecomposition:
    ref = arcus_oracle
    o = (hl_oracle - arcus_oracle) / ref * BPS
    b = ((hl_mid - hl_oracle) - (arcus_mid - arcus_oracle)) / ref * BPS
    m = (hl_mid - arcus_mid) / ref * BPS
    return BasisDecomposition(o, b, m, (hl_mid - hl_oracle) / hl_oracle * BPS,
                              (arcus_mid - arcus_oracle) / arcus_oracle * BPS)


# ------------------------------------------------------------------------------------------------ history
def hour_bucket(ts_ms: int) -> int:
    """Funding payment hour (epoch ms floored to the hour); HL stamps arrive a few ms after the hour."""
    return ts_ms // HOUR_MS * HOUR_MS


def align_hourly(arcus: Iterable[tuple[int, Decimal]], hl: Iterable[tuple[int, Decimal]]
                 ) -> list[tuple[int, Decimal, Decimal]]:
    """[(hour_ms, arcus_rate, hl_rate)] for hours present on BOTH venues (ascending). Duplicates: last wins."""
    a = {hour_bucket(t): r for t, r in arcus}
    h = {hour_bucket(t): r for t, r in hl}
    return [(t, a[t], h[t]) for t in sorted(set(a) & set(h))]


def runs_positive(xs: list[Decimal]) -> list[int]:
    runs: list[int] = []
    cur = 0
    for x in xs:
        if x > ZERO:
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    return runs


def sign_flips(xs: list[Decimal]) -> int:
    """Number of sign changes, ignoring exact zeros (a zero keeps the previous sign)."""
    flips, prev = 0, 0
    for x in xs:
        sgn = 1 if x > ZERO else -1 if x < ZERO else 0
        if sgn and prev and sgn != prev:
            flips += 1
        if sgn:
            prev = sgn
    return flips


def hours_to_breakeven(carry: list[Decimal], fee: Decimal) -> int | None:
    """First hour count n with cumulative carry ≥ fee (round-trip fee as a fraction); None if never."""
    cum = ZERO
    for i, c in enumerate(carry, start=1):
        cum += c
        if cum >= fee:
            return i
    return None


def direction_stats(carry: list[Decimal], fees: dict[str, Decimal]) -> dict[str, Any]:
    """``carry`` = hourly funding received (fraction of notional) for one direction, oldest first."""
    n = len(carry)
    if n == 0:
        return {"hours": 0}
    mean = sum(carry, ZERO) / Decimal(n)
    runs = runs_positive(carry)
    total = sum(carry, ZERO)
    out: dict[str, Any] = {
        "hours": n, "mean_hourly": mean, "daily_mean": mean * 24, "annualized": mean * HOURS_PER_YEAR,
        "pct_hours_positive": Decimal(sum(1 for c in carry if c > ZERO)) / Decimal(n) * 100,
        "longest_positive_run_h": max(runs) if runs else 0,
        "avg_positive_run_h": (Decimal(sum(runs)) / Decimal(len(runs))) if runs else ZERO,
        "positive_runs": len(runs), "sign_flips": sign_flips(carry),
        "total_carry_fraction": total, "total_carry_bps": total * BPS, "by_fee_mode": {},
    }
    for mode, fee in fees.items():
        be_start = hours_to_breakeven(carry, fee)
        # rolling entries: enter at every hour, how long until the funding pays the round-trip fees?
        waits = [w for w in (hours_to_breakeven(carry[i:], fee) for i in range(n)) if w is not None]
        waits.sort()
        out["by_fee_mode"][mode] = {
            "round_trip_fee_bps": fee * BPS,
            "expected_breakeven_h": (fee / mean) if mean > ZERO else None,
            "breakeven_h_entering_at_window_start": be_start,
            "rolling_entries": n, "rolling_entries_breaking_even": len(waits),
            "rolling_median_breakeven_h": waits[len(waits) // 2] if waits else None,
            "net_pnl_hold_whole_window_bps": (total - fee) * BPS,
        }
    return out
