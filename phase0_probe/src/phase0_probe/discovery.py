"""Overlap discovery between Arcus perps and Hyperliquid (core perp dex "" and Entropy HIP-3 dex "io")."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

from phase0_probe.dec import D, D_opt, HOURS_PER_YEAR, step_from_decimals
from phase0_probe.venues import HL_BASE_MAKER, HL_BASE_TAKER, HL_MIN_NOTIONAL, hip3_fee_scale

PRIORITY = ("BTC", "ETH", "SOL")
PPM = Decimal(1_000_000)


@dataclass
class ArcusMarket:
    market: str
    market_id: int
    base: str
    status: str
    category: str | None
    step: Decimal
    tick: Decimal
    min_notional: Decimal
    min_size: Decimal
    maker_fee: Decimal             # effectiveMakerFeePpm / 1e6 (tier 0 of the market's schedule)
    taker_fee: Decimal
    has_custom_fee: bool
    funding_hourly: Decimal | None
    next_funding_hourly: Decimal | None
    max_leverage: Decimal | None   # 1 / initialMarginFraction
    margin_modes: str


@dataclass
class HlMarket:
    venue: str                     # "hl_core" | "hl_io"
    dex: str
    coin: str                      # WS / info coin name, e.g. "BTC" or "io:NVDA"
    base: str
    step: Decimal
    sz_decimals: int
    min_notional: Decimal
    max_leverage: int
    margin_mode: str               # cross | noCross | strictIsolated
    only_isolated: bool
    is_delisted: bool
    deployer_fee_scale: Decimal | None
    growth_mode: bool
    maker_fee: Decimal
    taker_fee: Decimal
    funding_hourly: Decimal | None
    predicted_hourly: Decimal | None
    mark_px: Decimal | None
    day_ntl_vlm: Decimal | None


def parse_arcus(markets_body: dict[str, Any], fee_body: dict[str, Any] | None) -> list[ArcusMarket]:
    fees: dict[int, dict[str, Any]] = {}
    for row in (fee_body or {}).get("feeSchedules") or []:
        fees[int(row["marketId"])] = row
    out = []
    for m in markets_body.get("markets") or []:
        if m.get("type") not in (None, "PERPETUAL"):
            continue
        mid = int(m["marketId"])
        sched = fees.get(mid)
        tier0 = None
        if sched and sched.get("tiers"):
            tier0 = min(sched["tiers"], key=lambda t: int(t["level"]))
        maker_ppm = D(str(tier0["makerFeePpm"])) if tier0 else D(str(m["effectiveMakerFeePpm"]))
        taker_ppm = D(str(tier0["takerFeePpm"])) if tier0 else D(str(m["effectiveTakerFeePpm"]))
        imf = D_opt(str(m["initialMarginFraction"])) if m.get("initialMarginFraction") is not None else None
        out.append(ArcusMarket(
            market=m["marketDisplayName"], market_id=mid, base=str(m["baseAsset"]).upper(), status=m.get("status", ""),
            category=m.get("category"), step=D(str(m["stepSize"])), tick=D(str(m["tickSize"])),
            min_notional=D(str(m["minOrderNotional"])), min_size=D(str(m["minOrderSize"])),
            maker_fee=maker_ppm / PPM, taker_fee=taker_ppm / PPM,
            has_custom_fee=bool(m.get("hasCustomFeeSchedule")),
            funding_hourly=D_opt(m.get("fundingRate") if m.get("fundingRate") is None else str(m["fundingRate"])),
            next_funding_hourly=D_opt(None if m.get("nextFundingRate") is None else str(m["nextFundingRate"])),
            max_leverage=(Decimal(1) / imf) if imf else None,
            margin_modes="CROSS|ISOLATED (per account; docs concepts/perpetuals/margin-modes.md)"))
    return out


def parse_hl(meta_ctxs: list[Any], *, dex: str, predicted: dict[str, Decimal] | None = None) -> list[HlMarket]:
    meta, ctxs = meta_ctxs[0], meta_ctxs[1]
    venue = "hl_core" if dex == "" else f"hl_{dex}"
    out = []
    for a, c in zip(meta["universe"], ctxs):
        coin = a["name"]
        base = coin.split(":", 1)[1] if ":" in coin else coin
        szd = int(a["szDecimals"])
        mode = a.get("marginMode") or ("noCross" if a.get("onlyIsolated") else "cross")
        dfs = D(str(a["deployerFeeScale"])) if a.get("deployerFeeScale") is not None else None
        growth = str(a.get("growthMode", "")).lower() == "enabled"
        scale = hip3_fee_scale(dfs, growth) if dex != "" and dfs is not None else Decimal(1)
        out.append(HlMarket(
            venue=venue, dex=dex, coin=coin, base=base.upper(), step=step_from_decimals(szd), sz_decimals=szd,
            min_notional=HL_MIN_NOTIONAL, max_leverage=int(a["maxLeverage"]), margin_mode=mode,
            only_isolated=bool(a.get("onlyIsolated")), is_delisted=bool(a.get("isDelisted")),
            deployer_fee_scale=dfs, growth_mode=growth, maker_fee=HL_BASE_MAKER * scale,
            taker_fee=HL_BASE_TAKER * scale,
            funding_hourly=D_opt(None if c.get("funding") is None else str(c["funding"])),
            predicted_hourly=(predicted or {}).get(coin),
            mark_px=D_opt(None if c.get("markPx") is None else str(c["markPx"])),
            day_ntl_vlm=D_opt(None if c.get("dayNtlVlm") is None else str(c["dayNtlVlm"]))))
    return out


def parse_predicted(body: list[Any]) -> dict[str, Decimal]:
    """``predictedFundings`` -> {coin: HlPerp HOURLY rate}. Each venue's ``fundingRate`` is per its own
    ``fundingIntervalHours`` (live: HlPerp 1, BinPerp/BybitPerp 8), so the rate is divided by that interval.
    PR #1.5 hardening: Phase 0 took the raw value, which is only correct while HlPerp's interval is 1 h (it was in
    every observed response, so Phase 0 numbers are unaffected)."""
    out: dict[str, Decimal] = {}
    for coin, venues in body or []:
        for name, info in venues or []:
            if name == "HlPerp" and info and info.get("fundingRate") is not None:
                hours = info.get("fundingIntervalHours")
                rate = D(str(info["fundingRate"]))
                out[coin] = rate / D(hours) if isinstance(hours, int) and hours > 0 else rate
    return out


def overlap(arcus: list[ArcusMarket], hl: list[HlMarket]) -> list[dict[str, Any]]:
    by_base: dict[str, list[HlMarket]] = {}
    for h in hl:
        by_base.setdefault(h.base, []).append(h)
    rows = []
    for a in arcus:
        for h in by_base.get(a.base, []):
            f_a = a.next_funding_hourly if a.next_funding_hourly is not None else a.funding_hourly
            f_h = h.predicted_hourly if h.predicted_hourly is not None else h.funding_hourly
            rows.append({
                "symbol": a.base, "priority": a.base in PRIORITY, "hl_venue": h.venue, "hl_coin": h.coin,
                "arcus": asdict(a), "hl": asdict(h),
                "rt_dual_taker_fee_bps": 2 * (a.taker_fee + h.taker_fee) * 10_000,
                "funding_diff_annual_hl_minus_arcus": (f_h - f_a) * HOURS_PER_YEAR
                if f_h is not None and f_a is not None else None,
            })
    rows.sort(key=lambda r: (not r["priority"], PRIORITY.index(r["symbol"]) if r["priority"] else 0,
                             r["symbol"], r["hl_venue"]))
    return rows
