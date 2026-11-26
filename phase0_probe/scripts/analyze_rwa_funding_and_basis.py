"""PR #1.6 item 1 — Arcus ∩ Entropy (HL dex "io") US-equity perps: live oracle / mark / mid gaps, real fees, RTH vs
off-hours margin parameters, and a 14 / 30-day hourly funding back-test split by NYSE session (READ-ONLY, zero keys).

Usage: uv run python scripts/analyze_rwa_funding_and_basis.py [--samples 5] [--every-s 5] [--days 30 --days 14]
       [--out reports] [--name rwa_funding_basis]

Sources (all public, documented; snapshots in docs_snapshot/):
* Arcus GET /v1/markets (oraclePrice, markPrice, fundingRate, nextFundingRate, initialMarginFraction,
  maintenanceMarginFraction, offHoursInitialMarginFraction, regularTradingHours, isOutsideRth, markTier,
  currentSettlementPrice, upper/lowerTradingBound), GET /v1/markets/feeSchedules (tier 0 maker/taker ppm),
  GET /v1/feetiers, GET /v1/l2OrderBook/{market} (book mid), GET /v1/fundingRates (µs, limit ≤ 1000, newest first).
* HL POST /info metaAndAssetCtxs {"dex":"io"} (oraclePx, markPx, midPx, funding, maxLeverage, marginMode,
  deployerFeeScale, growthMode), l2Book (book mid), fundingHistory {"coin":"io:XXX"} (≤ 500 rows / call).
* Third-party cross-check only (NOT a venue): Kraken public ticker USDTZUSD (USDT/USD), as in PR #1.5.
Mids are (best bid + best ask) / 2 of the L2 books; the last trade price is never used.
"""
from __future__ import annotations

import argparse
import asyncio
import pathlib
import sys
from decimal import Decimal
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import aiohttp  # noqa: E402

from phase0_probe.dec import BPS, HOURS_PER_YEAR, D, D_opt, dumps, fmt, now_ms  # noqa: E402
from phase0_probe.discovery import parse_arcus, parse_hl  # noqa: E402
from phase0_probe.funding import align_hourly, decompose_basis, round_trip_fees, split_by_session  # noqa: E402
from phase0_probe.sessions import bucket, funding_hour_session, session_at, to_et  # noqa: E402
from phase0_probe.venues import ARCUS_REST, ENTROPY_DEX, get_json, hl_info  # noqa: E402

KRAKEN_USDT = "https://api.kraken.com/0/public/Ticker"
DOCS = {
    "arcus_markets": "https://docs.arcus.xyz/api-reference/public/get-markets.md",
    "arcus_fee_schedules": "https://docs.arcus.xyz/api-reference/public/get-market-fee-schedules.md",
    "arcus_funding_rates": "https://docs.arcus.xyz/api-reference/public/get-market-funding-rates.md",
    "arcus_prices": "https://docs.arcus.xyz/concepts/perpetuals/prices.md",
    "hl_perp_info": "https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals.md",
    "hl_fees": "https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees.md",
    "hl_hip3": "https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/"
              "hip-3-builder-deployed-perpetuals.md",
    "nyse_calendar": "https://www.nyse.com/trade/hours-calendars/",
}
ORACLE_KEYS = ("oracle_diff_bps", "mark_diff_bps", "mid_diff_bps", "book_premium_diff_bps", "hl_premium_bps",
               "arcus_premium_bps")


def median(xs: list[Decimal]) -> Decimal | None:
    if not xs:
        return None
    ys = sorted(xs)
    n = len(ys)
    return ys[n // 2] if n % 2 else (ys[n // 2 - 1] + ys[n // 2]) / 2


async def usdt_usd(sess: aiohttp.ClientSession) -> dict[str, Any]:
    try:
        body = await get_json(sess, KRAKEN_USDT, params={"pair": "USDTZUSD"})
        t = body["result"]["USDTZUSD"]
        mid = (D(t["a"][0]) + D(t["b"][0])) / 2
        return {"mid": mid, "implied_usdt_premium_bps": (1 / mid - 1) * BPS}
    except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, ValueError) as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


async def discover(sess: aiohttp.ClientSession) -> dict[str, Any]:
    markets = await get_json(sess, f"{ARCUS_REST}/v1/markets")
    fee_body = await get_json(sess, f"{ARCUS_REST}/v1/markets/feeSchedules")
    feetiers = await get_json(sess, f"{ARCUS_REST}/v1/feetiers")
    io_raw = await hl_info(sess, {"type": "metaAndAssetCtxs", "dex": ENTROPY_DEX})
    arcus = {a.base: a for a in parse_arcus(markets, fee_body)}
    a_raw = {str(m["baseAsset"]).upper(): m for m in markets["markets"]}
    sched = {int(r["marketId"]): r for r in fee_body.get("feeSchedules") or []}
    io = {h.base: h for h in parse_hl(io_raw, dex=ENTROPY_DEX) if h.base in arcus and not h.is_delisted}
    io_uni = {u["name"]: u for u in io_raw[0]["universe"]}
    syms = sorted(io, key=lambda s: -min(D(str(a_raw[s].get("volume24hNotional") or "0")), io[s].day_ntl_vlm or D(0)))
    return {"arcus": arcus, "a_raw": a_raw, "sched": sched, "feetiers": feetiers, "io": io, "io_uni": io_uni,
            "syms": syms, "io_collateralToken": io_raw[0].get("collateralToken")}


async def live_sample(sess: aiohttp.ClientSession, syms: list[str], coins: dict[str, str]) -> dict[str, Any]:
    t0 = now_ms()
    markets, io_raw = await asyncio.gather(get_json(sess, f"{ARCUS_REST}/v1/markets"),
                                           hl_info(sess, {"type": "metaAndAssetCtxs", "dex": ENTROPY_DEX}))
    a_books = await asyncio.gather(*[get_json(sess, f"{ARCUS_REST}/v1/l2OrderBook/{s}-USD", params={"nLevels": "5"})
                                     for s in syms])
    h_books = await asyncio.gather(*[hl_info(sess, {"type": "l2Book", "coin": coins[s]}) for s in syms])
    t1 = now_ms()
    a_by = {str(m["baseAsset"]).upper(): m for m in markets["markets"]}
    ctx_by = {u["name"]: c for u, c in zip(io_raw[0]["universe"], io_raw[1])}
    out: dict[str, Any] = {"t_start_ms": t0, "t_end_ms": t1, "session_et": session_at(t0), "symbols": {}}
    for s, ab, hb in zip(syms, a_books, h_books):
        am, ctx = a_by[s], ctx_by[coins[s]]
        a_or, a_mk = D(str(am["oraclePrice"])), D(str(am["markPrice"]))
        h_or, h_mk = D(str(ctx["oraclePx"])), D(str(ctx["markPx"]))
        a_mid = (D(ab["bids"][0][0]) + D(ab["asks"][0][0])) / 2 if ab.get("bids") and ab.get("asks") else None
        lv = hb.get("levels") or [[], []]
        h_mid = (D(lv[0][0]["px"]) + D(lv[1][0]["px"])) / 2 if lv[0] and lv[1] else None
        row: dict[str, Any] = {
            "arcus": {"oraclePrice": a_or, "markPrice": a_mk, "book_mid": a_mid, "isOutsideRth": am.get("isOutsideRth"),
                      "currentSettlementPrice": am.get("currentSettlementPrice"),
                      "lowerTradingBound": am.get("lowerTradingBound"), "upperTradingBound": am.get("upperTradingBound")},
            "hl": {"oraclePx": h_or, "markPx": h_mk, "ctx_midPx": D_opt(None if ctx.get("midPx") is None else str(ctx["midPx"])),
                   "book_mid": h_mid, "premium": ctx.get("premium")},
            "mark_diff_bps": (h_mk - a_mk) / a_or * BPS,
        }
        if a_mid is not None and h_mid is not None:
            dcmp = decompose_basis(a_or, a_mid, h_or, h_mid)
            row |= {k: getattr(dcmp, k) for k in ("oracle_diff_bps", "book_premium_diff_bps", "mid_diff_bps",
                                                    "hl_premium_bps", "arcus_premium_bps")}
        else:
            row["oracle_diff_bps"] = (h_or - a_or) / a_or * BPS
        out["symbols"][s] = row
    out["usdt_usd"] = await usdt_usd(sess)
    return out


async def arcus_history(sess: aiohttp.ClientSession, market: str, start_ms: int, end_ms: int) -> list[tuple[int, Decimal]]:
    out: list[tuple[int, Decimal]] = []
    to_us = end_ms * 1000
    while True:
        body = await get_json(sess, f"{ARCUS_REST}/v1/fundingRates",
                              params={"market": market, "from": str(start_ms * 1000), "to": str(to_us), "limit": "1000"})
        rows = body.get("fundingRates") or []
        out += [(int(r["time"]) // 1000, D(r["fundingRate"])) for r in rows]
        if len(rows) < 1000:
            break
        to_us = min(int(r["time"]) for r in rows) - 1
        await asyncio.sleep(1)
    return sorted(set(out))


async def hl_history(sess: aiohttp.ClientSession, coin: str, start_ms: int, end_ms: int) -> list[tuple[int, Decimal]]:
    out: list[tuple[int, Decimal]] = []
    t = start_ms
    while t < end_ms:
        rows = await hl_info(sess, {"type": "fundingHistory", "coin": coin, "startTime": t, "endTime": end_ms})
        if not rows:
            break
        out += [(int(r["time"]), D(r["fundingRate"])) for r in rows]
        last = max(int(r["time"]) for r in rows)
        if len(rows) < 500 or last + 1 <= t:
            break
        t = last + 1
        await asyncio.sleep(1)
    return sorted(set(out))


def fee_margin_row(s: str, disc: dict[str, Any]) -> dict[str, Any]:
    a, am, h, u = disc["arcus"][s], disc["a_raw"][s], disc["io"][s], disc["io_uni"][disc["io"][s].coin]
    sc = disc["sched"].get(a.market_id) or {}
    tier0 = min(sc.get("tiers") or [{}], key=lambda t: int(t.get("level", 0)))
    imf, mmf = D_opt(str(am["initialMarginFraction"])), D_opt(str(am["maintenanceMarginFraction"]))
    off = D_opt(None if am.get("offHoursInitialMarginFraction") is None else str(am["offHoursInitialMarginFraction"]))
    return {
        "arcus": {"market": a.market, "category": a.category, "maker_fee": a.maker_fee, "taker_fee": a.taker_fee,
                  "maker_bps": a.maker_fee * BPS, "taker_bps": a.taker_fee * BPS,
                  "feeSchedules_tier0_raw": tier0, "hasCustomFeeSchedule": a.has_custom_fee,
                  "baseMakerFeePpm": am.get("baseMakerFeePpm"), "baseTakerFeePpm": am.get("baseTakerFeePpm"),
                  "initialMarginFraction": imf, "maintenanceMarginFraction": mmf,
                  "offHoursInitialMarginFraction": off,
                  "max_leverage_rth": (1 / imf) if imf else None, "max_leverage_off_hours": (1 / off) if off else None,
                  "maintenance_off_hours_note": "not uplifted off-hours (get-markets.md)",
                  "regularTradingHours": am.get("regularTradingHours"), "isOutsideRth": am.get("isOutsideRth"),
                  "markTier": am.get("markTier"), "minOrderNotional": am.get("minOrderNotional"),
                  "openInterestCapNotional": am.get("openInterestCapNotional")},
        "io": {"coin": h.coin, "maker_fee": h.maker_fee, "taker_fee": h.taker_fee, "maker_bps": h.maker_fee * BPS,
               "taker_bps": h.taker_fee * BPS, "deployerFeeScale": h.deployer_fee_scale, "growthMode": h.growth_mode,
               "maxLeverage": h.max_leverage, "marginMode": h.margin_mode, "onlyIsolated": h.only_isolated,
               "marginTableId": u.get("marginTableId"),
               "session_margin_note": "no RTH/off-hours margin field in metaAndAssetCtxs for HIP-3 [待实测确认]",
               "min_notional_usd": h.min_notional, "min_notional_note": "TODO: VERIFY_FROM_DOCS ($10 observed)"},
    }


def three_way(hour_ms: int) -> str:
    return funding_hour_session(hour_ms)


def history_block(a: list[tuple[int, Decimal]], h: list[tuple[int, Decimal]], start_ms: int,
                  fees: dict[str, Decimal]) -> dict[str, Any]:
    al = [r for r in align_hourly(a, h) if r[0] >= start_ms]
    labels = {t: funding_hour_session(t) for t, _, _ in al}
    off_rates = [ar for t, ar, _ in al if labels[t] == "CLOSED"]        # Arcus outside its 04:00–20:00 window
    rth_rates = [ar for t, ar, _ in al if labels[t] == "RTH"]
    mode_off = max(set(off_rates), key=off_rates.count) if off_rates else None
    return {
        "aligned_hours": len(al), "first_hour_ms": al[0][0] if al else None, "last_hour_ms": al[-1][0] if al else None,
        "hours_by_label": {k: sum(1 for v in labels.values() if v == k) for k in ("RTH", "EXT", "CLOSED")},
        "arcus_off_hours_modal_rate": mode_off,
        "arcus_off_hours_share_at_modal_rate_pct": (Decimal(off_rates.count(mode_off)) / Decimal(len(off_rates)) * 100)
        if off_rates else None,
        "arcus_rth_distinct_rates": len(set(rth_rates)),
        "arcus_closed_distinct_rates": len(set(off_rates)),
        "arcus_closed_hour_to_hour_changes": sum(1 for x, y in zip(al, al[1:]) if y[0] - x[0] == 3_600_000
                                                 and labels[x[0]] == labels[y[0]] == "CLOSED" and x[1] != y[1]),
        "split": split_by_session(al, lambda t: bucket(funding_hour_session(t)), fees),
        "split_3way": {k: v for k, v in split_by_session(al, three_way, fees).items() if k != "ALL"},
    }


def md(rep: dict[str, Any]) -> str:
    L = ["# Arcus × Entropy io — US-equity oracle / fees / margin / funding (PR #1.6, read-only)", "",
         f"Generated at epoch ms {rep['generated_ms']} ({rep['generated_et']} ET, session label "
         f"`{rep['session_now']}`). Markets: {len(rep['symbols'])} non-delisted Arcus ∩ io overlaps "
         f"({', '.join(rep['symbols'])}). io collateralToken index {rep['io_collateralToken']}.", "",
         "## a) Live oracle / mark / mid (median of samples, bps of the Arcus oracle; HL − Arcus)", "",
         f"Samples: {len(rep['samples'])} × {len(rep['symbols'])} markets; session at sampling: "
         f"{', '.join(sorted({x['session_et'] for x in rep['samples']}))}. "
         + ("**Sampled outside RTH.** Arcus outside its RTH window: the oracle is *derived from the exchange's own "
            "mark price* (order book, no Pyth, no oracle clamp; concepts/perpetuals/prices.md), so the HL − Arcus "
            "'oracle' Δ below is HL's deployer oracle vs Arcus' own book — NOT an oracle-vs-oracle comparison. Re-run "
            "with `--skip-history` in RTH (tonight's command does) for the real Pyth-vs-HL gap."
            if any(x["session_et"] != "RTH" for x in rep["samples"]) else ""), "",
         "| Symbol | Arcus oracle | Arcus mark | Arcus mid | HL oracle | HL mark | HL mid | oracle Δ bps | (min…max) | "
         "mark Δ bps | mid Δ bps | book-premium Δ bps | HL mid−oracle bps | Arcus mid−oracle bps | Arcus outside RTH |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in rep["symbols"]:
        last = rep["samples"][-1]["symbols"][s]
        g = rep["oracle"]["per_symbol"][s]
        L.append(f"| {s} | {last['arcus']['oraclePrice']} | {last['arcus']['markPrice']} | {fmt(last['arcus']['book_mid'], 3)} "
                 f"| {last['hl']['oraclePx']} | {last['hl']['markPx']} | {fmt(last['hl']['book_mid'], 3)} | "
                 f"{fmt(g['oracle_diff_bps'], 2)} | {fmt(g['oracle_diff_bps_min'], 2)}…{fmt(g['oracle_diff_bps_max'], 2)} | "
                 f"{fmt(g['mark_diff_bps'], 2)} | {fmt(g['mid_diff_bps'], 2)} | {fmt(g['book_premium_diff_bps'], 2)} | "
                 f"{fmt(g['hl_premium_bps'], 2)} | {fmt(g['arcus_premium_bps'], 2)} | {last['arcus']['isOutsideRth']} |")
    o = rep["oracle"]
    L += ["", f"Cross-market oracle Δ: median **{fmt(o['cross_market_median_bps'], 2)} bps**, range "
              f"{fmt(o['cross_market_min_bps'], 2)} … {fmt(o['cross_market_max_bps'], 2)} bps "
              f"(spread {fmt(o['cross_market_range_bps'], 2)} bps). USDT/USD (Kraken, third-party): "
              f"{o['usdt_usd_mid'] if o['usdt_usd_mid'] is not None else 'n/a'} → implied USDT premium "
              f"{fmt(o['implied_usdt_premium_bps'], 2)} bps. Crypto reference (PR #1.5): ~12.5 bps.", "",
          f"Verdict: {o['verdict']}", "",
          "## b) Fees (tier 0) and margin (Arcus RTH vs off-hours; io static)", "",
          "| Symbol | Arcus maker/taker bps (custom sched.) | base ppm m/t | io maker/taker bps (scale, growth) | "
          "RT DUAL_TAKER bps | RT MAKER_ARCUS bps | RT MAKER_HL bps | Arcus IMF RTH → off-hours (max lev) | Arcus MMF | "
          "Arcus RTH window ET | markTier | io max lev / margin mode |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in rep["symbols"]:
        f = rep["fees_margin"][s]
        a, i, rt = f["arcus"], f["io"], rep["round_trip_fees"][s]
        w = a["regularTradingHours"] or {}
        win = (f"{int(w['startSecondsOfDay']) // 3600:02d}:00–{int(w['endSecondsOfDay']) // 3600:02d}:00 "
               f"{w.get('timezone')}") if w else "24/7"
        L.append(f"| {s} | {fmt(a['maker_bps'], 2)} / {fmt(a['taker_bps'], 2)} ({a['hasCustomFeeSchedule']}) | "
                 f"{a['baseMakerFeePpm']} / {a['baseTakerFeePpm']} | {fmt(i['maker_bps'], 2)} / {fmt(i['taker_bps'], 2)} "
                 f"({i['deployerFeeScale']}, {i['growthMode']}) | {fmt(rt['DUAL_TAKER'] * BPS, 2)} | "
                 f"{fmt(rt['MAKER_ARCUS_TAKER_HL'] * BPS, 2)} | {fmt(rt['MAKER_HL_TAKER_ARCUS'] * BPS, 2)} | "
                 f"{a['initialMarginFraction']} → {a['offHoursInitialMarginFraction']} "
                 f"({fmt(a['max_leverage_rth'], 1)}× → {fmt(a['max_leverage_off_hours'], 1)}×) | "
                 f"{a['maintenanceMarginFraction']} | {win} | {a['markTier']} | {i['maxLeverage']}× / {i['marginMode']} |")
    L += ["", "RT = open + close, both legs. Arcus maintenance margin is not uplifted off-hours (get-markets.md). io: no "
              "session-dependent margin field exposed [待实测确认]; io min notional $10 TODO: VERIFY_FROM_DOCS.", ""]
    for days_key, blk in rep["funding"].items():
        L += [f"## c) Funding back-test — last {days_key} days (hourly, both venues, aligned by payment hour)", "",
              "Session of a payment at H = label of H − 30 min (the accrual hour's midpoint). RTH = NYSE 09:30–16:00 ET "
              "(13:00 on early-close days, holidays excluded); OFF_HOURS = pre/post (EXT) + overnight/weekend/holiday "
              "(CLOSED). Carry = funding received per hour. Runs / flips only inside contiguous blocks. "
              "`net hold` = bucket carry − one round trip; `per-block` = round trip paid every block (e.g. every RTH "
              "session). Funding only: no basis / price PnL, slippage or buffer.", "",
              "### Summary (better direction per bucket; cheapest real mode MAKER_ARCUS_TAKER_HL and DUAL_TAKER)", "",
              "| Symbol | bucket | h | Δ ann. HL−Arcus % | better direction | carry ann. % | % h > 0 | flips | "
              "longest + run h | total carry bps | BE h (fee/mean) maker-A / dual | net hold bps maker-A / dual | "
              "per-block net bps maker-A / dual |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for s in rep["symbols"]:
            b = blk["symbols"].get(s)
            if not b or not b["aligned_hours"]:
                continue
            for bk in ("RTH", "OFF_HOURS", "ALL"):
                g = b["split"].get(bk)
                if not g or not g["hours"]:
                    continue
                dname, st = max(g["directions"].items(), key=lambda kv: kv[1]["mean_hourly"])
                mk, dt_ = st["by_fee_mode"]["MAKER_ARCUS_TAKER_HL"], st["by_fee_mode"]["DUAL_TAKER"]
                be = (lambda x: fmt(x, 1) if x is not None else "never")
                L.append(f"| {s} | {bk} | {g['hours']} | {fmt(g['diff_hl_minus_arcus_annualized'] * 100, 2)} | {dname} | "
                         f"{fmt(st['annualized'] * 100, 2)} | {fmt(st['pct_hours_positive'], 1)} | {st['sign_flips']} | "
                         f"{st['longest_positive_run_h']} | {fmt(st['total_carry_bps'], 2)} | "
                         f"{be(mk['expected_breakeven_h'])} / {be(dt_['expected_breakeven_h'])} | "
                         f"{fmt(mk['net_hold_bps'], 2)} / {fmt(dt_['net_hold_bps'], 2)} | "
                         f"{fmt(mk['net_per_block_strategy_bps'], 2)} / {fmt(dt_['net_per_block_strategy_bps'], 2)} |")
        L += ["", "### Detail (both directions)", "",
              "| Symbol | bucket | h | Arcus mean bps/h | HL mean bps/h | Δ ann. HL−Arcus % | Δ flips | Direction | "
              "carry ann. % | % h > 0 | longest + run h | total carry bps | blocks (mean len h) | mean block carry bps |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for s in rep["symbols"]:
            b = blk["symbols"].get(s)
            if not b or not b["aligned_hours"]:
                L.append(f"| {s} | — | 0 | | | | | | | | | | | |")
                continue
            for bk in ("RTH", "OFF_HOURS", "ALL"):
                g = b["split"].get(bk)
                if not g or not g["hours"]:
                    continue
                for dname, st in g["directions"].items():
                    L.append(f"| {s} | {bk} | {g['hours']} | {fmt(g['arcus_mean_hourly'] * BPS, 4)} | "
                             f"{fmt(g['hl_mean_hourly'] * BPS, 4)} | {fmt(g['diff_hl_minus_arcus_annualized'] * 100, 2)} | "
                             f"{g['diff_sign_flips_within_blocks']} | {dname} | {fmt(st['annualized'] * 100, 2)} | "
                             f"{fmt(st['pct_hours_positive'], 1)} | {st['longest_positive_run_h']} | "
                             f"{fmt(st['total_carry_bps'], 2)} | {st['blocks']} ({fmt(st['mean_block_len_h'], 1)}) | "
                             f"{fmt(st['mean_block_carry_bps'], 3)} |")
        L += ["", f"### Break-even and net after real round-trip fees — {days_key} d", "",
              "| Symbol | bucket | Direction | mode | RT fee bps | expected BE h (fee/mean) | BE h from 1st hour | "
              "net hold bps | blocks beating fee | net per-block strategy bps |", "|---|---|---|---|---|---|---|---|---|---|"]
        for s in rep["symbols"]:
            b = blk["symbols"].get(s)
            if not b or not b["aligned_hours"]:
                continue
            for bk in ("RTH", "OFF_HOURS", "ALL"):
                g = b["split"].get(bk)
                if not g or not g["hours"]:
                    continue
                for dname, st in g["directions"].items():
                    for mode, x in st["by_fee_mode"].items():
                        be = x["expected_breakeven_h"]
                        L.append(f"| {s} | {bk} | {dname} | {mode} | {fmt(x['round_trip_fee_bps'], 2)} | "
                                 f"{fmt(be, 1) if be is not None else 'never (mean ≤ 0)'} | "
                                 f"{x['breakeven_h_from_first_hour'] or 'never'} | {fmt(x['net_hold_bps'], 2)} | "
                                 f"{x['blocks_beating_fee']}/{st['blocks']} | {fmt(x['net_per_block_strategy_bps'], 2)} |")
        L += ["", f"### Coverage — {days_key} d", ""]
        for s in rep["symbols"]:
            b = blk["symbols"].get(s) or {}
            L.append(f"* {s}: Arcus rows {b.get('arcus_rows')}, HL rows {b.get('hl_rows')}, aligned {b.get('aligned_hours')} "
                     f"h {b.get('hours_by_label')}; Arcus off-hours modal rate {b.get('arcus_off_hours_modal_rate')} "
                     f"({fmt(b.get('arcus_off_hours_share_at_modal_rate_pct'), 1)} % of CLOSED h; ×8760 = "
                     f"{fmt(b['arcus_off_hours_modal_rate'] * HOURS_PER_YEAR * 100, 3) if b.get('arcus_off_hours_modal_rate') is not None else 'n/a'} %/yr); "
                     f"Arcus distinct RTH rates {b.get('arcus_rth_distinct_rates')}; CLOSED hours: "
                     f"{b.get('arcus_closed_distinct_rates')} distinct Arcus rates, "
                     f"{b.get('arcus_closed_hour_to_hour_changes')} hour-to-hour changes (pinned SOFR + 0.5 %)")
        L.append("")
    L += ["## Docs", ""] + [f"* {k}: {v}" for k, v in DOCS.items()]
    return "\n".join(L) + "\n"


def oracle_summary(samples: list[dict[str, Any]], syms: list[str]) -> dict[str, Any]:
    per: dict[str, Any] = {}
    for s in syms:
        per[s] = {}
        for k in ORACLE_KEYS:
            vals = [x["symbols"][s][k] for x in samples if x["symbols"][s].get(k) is not None]
            per[s][k] = median(vals)
            if k == "oracle_diff_bps" and vals:
                per[s][k + "_min"], per[s][k + "_max"] = min(vals), max(vals)
    od = [per[s]["oracle_diff_bps"] for s in syms if per[s]["oracle_diff_bps"] is not None]
    u = [x["usdt_usd"] for x in samples if "mid" in (x.get("usdt_usd") or {})]
    usdt = u[-1]["implied_usdt_premium_bps"] if u else None
    med, lo, hi = median(od), (min(od) if od else None), (max(od) if od else None)
    rng = hi - lo if od else None
    off = any(x["symbols"][s]["arcus"].get("isOutsideRth") for x in samples for s in syms)
    if med is None:
        verdict = "no data"
    else:
        common = rng is not None and rng <= Decimal(3)
        near = usdt is not None and abs(med - usdt) <= Decimal(3)
        verdict = (f"cross-market median {fmt(med, 2)} bps, range {fmt(rng, 2)} bps → "
                   + ("a COMMON static offset across all equities" if common else
                      "NOT one common offset (per-market dispersion > 3 bps: idiosyncratic oracle / session effects)")
                   + ("; matches the USDT/USD premium (±3 bps) → same quote-currency effect as crypto" if near else
                      "; does NOT match the USDT/USD premium within ±3 bps")
                   + (". INCONCLUSIVE for the static-oracle question: sampled while Arcus isOutsideRth=true (Arcus "
                      "oracle = its own mark off-hours); decide from the RTH sample." if off else "."))
    return {"per_symbol": per, "cross_market_median_bps": med, "cross_market_min_bps": lo, "cross_market_max_bps": hi,
            "cross_market_range_bps": rng, "usdt_usd_mid": u[-1]["mid"] if u else None,
            "implied_usdt_premium_bps": usdt, "verdict": verdict}


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=5)
    ap.add_argument("--every-s", type=int, default=5)
    ap.add_argument("--days", type=int, action="append", default=None)
    ap.add_argument("--out", default="reports")
    ap.add_argument("--name", default="rwa_funding_basis")
    ap.add_argument("--skip-history", action="store_true", help="oracle/mark/mid sampling + fees only (e.g. in RTH)")
    args = ap.parse_args(argv)
    days = sorted(set(args.days or [30, 14]), reverse=True)
    t0 = now_ms()
    end = t0 // 3_600_000 * 3_600_000 + 60_000
    start = end - days[0] * 24 * 3_600_000
    async with aiohttp.ClientSession() as sess:
        disc = await discover(sess)
        syms = disc["syms"]
        coins = {s: disc["io"][s].coin for s in syms}
        samples = []
        for i in range(args.samples):
            samples.append(await live_sample(sess, syms, coins))
            if i + 1 < args.samples:
                await asyncio.sleep(args.every_s)
        hist: dict[str, tuple[list[tuple[int, Decimal]], list[tuple[int, Decimal]]]] = {}
        for s in ([] if args.skip_history else syms):
            hist[s] = (await arcus_history(sess, f"{s}-USD", start, end), await hl_history(sess, coins[s], start, end))
            await asyncio.sleep(1)
    fm = {s: fee_margin_row(s, disc) for s in syms}
    rtf = {s: round_trip_fees(disc["arcus"][s].maker_fee, disc["arcus"][s].taker_fee, disc["io"][s].maker_fee,
                              disc["io"][s].taker_fee) for s in syms}
    funding: dict[str, Any] = {}
    for d in ([] if args.skip_history else days):
        st = end - d * 24 * 3_600_000
        funding[str(d)] = {"start_ms": st, "end_ms": end, "symbols": {}}
        for s in syms:
            a, h = hist[s]
            funding[str(d)]["symbols"][s] = {"arcus_rows": sum(1 for t, _ in a if t >= st),
                                             "hl_rows": sum(1 for t, _ in h if t >= st)} | history_block(a, h, st, rtf[s])
    rep = {"generated_ms": t0, "generated_et": to_et(t0).isoformat(), "session_now": session_at(t0), "docs": DOCS,
           "symbols": syms, "io_collateralToken": disc["io_collateralToken"],
           "feetiers_raw": disc["feetiers"], "samples": samples, "oracle": oracle_summary(samples, syms),
           "fees_margin": fm, "round_trip_fees": rtf, "funding": funding,
           "hourly_30d": {s: [{"hour_ms": t, "session": funding_hour_session(t), "arcus": ar, "hl": hr}
                              for t, ar, hr in align_hourly(*hist[s]) if t >= start] for s in hist}}
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.name}.json").write_text(dumps(rep))
    text = md(rep)
    (out / f"{args.name}.md").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
