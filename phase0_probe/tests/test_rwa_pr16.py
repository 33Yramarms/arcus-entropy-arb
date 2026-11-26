"""PR #1.6: NYSE session classifier (holiday / early close / DST), session-split funding statistics, real-fee
break-even, trade-tape parsing + storage, feed multiplexing, Maker fill-through filter and adverse selection."""
from __future__ import annotations

import datetime as dt
import pathlib
import sqlite3
from decimal import Decimal

import pytest

from phase0_probe.dec import BPS, HOURS_PER_YEAR
from phase0_probe.feeds import ArcusBookFeed, HlBookFeed
from phase0_probe.funding import (contiguous_blocks, round_trip_fees, session_direction_stats, split_by_session)
from phase0_probe.realism import adverse_bps, crosses, fill_evidence, legs, maker_realism, side_consistency
from phase0_probe.sessions import bucket, funding_hour_session, session_at
from phase0_probe.store import Store
from phase0_probe.trades import parse_arcus_trades, parse_hl_trades

D = Decimal
ROOT = pathlib.Path(__file__).resolve().parents[1]
H = 3_600_000


def utc_ms(y: int, mo: int, d: int, h: int, mi: int = 0) -> int:
    return int(dt.datetime(y, mo, d, h, mi, tzinfo=dt.timezone.utc).timestamp()) * 1000


# ----------------------------------------------------------------------------------------------- sessions
def test_regular_day_boundaries_est() -> None:
    # Wed 2026-11-25, EST (UTC-5): 09:30 ET = 14:30 UTC, 16:00 ET = 21:00 UTC, 04:00 ET = 09:00 UTC
    assert session_at(utc_ms(2026, 11, 25, 14, 29)) == "EXT"
    assert session_at(utc_ms(2026, 11, 25, 14, 30)) == "RTH"
    assert session_at(utc_ms(2026, 11, 25, 20, 59)) == "RTH"
    assert session_at(utc_ms(2026, 11, 25, 21, 0)) == "EXT"           # close is half-open
    assert session_at(utc_ms(2026, 11, 26, 0, 59)) == "EXT"           # 19:59 ET, inside the Arcus 04–20 window
    assert session_at(utc_ms(2026, 11, 26, 1, 0)) == "CLOSED"         # 20:00 ET
    assert session_at(utc_ms(2026, 11, 25, 8, 59)) == "CLOSED"        # 03:59 ET
    assert session_at(utc_ms(2026, 11, 25, 9, 0)) == "EXT"            # 04:00 ET


def test_thanksgiving_closed_and_half_day_ends_13_et() -> None:
    assert session_at(utc_ms(2026, 11, 26, 15, 0)) == "CLOSED"        # Thanksgiving 10:00 ET
    assert session_at(utc_ms(2026, 11, 26, 10, 0)) == "CLOSED"        # holiday pre-market too
    assert session_at(utc_ms(2026, 11, 27, 14, 30)) == "RTH"          # Fri half day 09:30 ET = 22:30 MYT
    assert session_at(utc_ms(2026, 11, 27, 17, 59)) == "RTH"          # 12:59 ET
    assert session_at(utc_ms(2026, 11, 27, 18, 0)) == "EXT"           # 13:00 ET = 02:00 Sat MYT: closed early
    assert session_at(utc_ms(2026, 12, 24, 18, 0)) == "EXT"           # Christmas Eve early close
    assert session_at(utc_ms(2026, 12, 25, 15, 0)) == "CLOSED"


def test_weekend_and_dst() -> None:
    assert session_at(utc_ms(2026, 11, 28, 15, 0)) == "CLOSED"        # Saturday
    assert session_at(utc_ms(2026, 11, 29, 15, 0)) == "CLOSED"        # Sunday
    # Wed 2026-10-28 is EDT (UTC-4): 09:30 ET = 13:30 UTC
    assert session_at(utc_ms(2026, 10, 28, 13, 29)) == "EXT"
    assert session_at(utc_ms(2026, 10, 28, 13, 30)) == "RTH"
    assert session_at(utc_ms(2026, 10, 28, 19, 59)) == "RTH"
    assert session_at(utc_ms(2026, 10, 28, 20, 0)) == "EXT"


def test_funding_hour_labelled_by_accrual_midpoint() -> None:
    day = [utc_ms(2026, 11, 25, h) for h in range(24)]                # payments at whole UTC hours
    rth = [t for t in day if funding_hour_session(t) == "RTH"]
    # payments 10:00 … 16:00 ET = 15:00 … 21:00 UTC (accrual midpoints 09:30 … 15:30 ET)
    assert rth == [utc_ms(2026, 11, 25, h) for h in range(15, 22)]
    half = [utc_ms(2026, 11, 27, h) for h in range(24)]
    assert [t for t in half if funding_hour_session(t) == "RTH"] == [utc_ms(2026, 11, 27, h) for h in range(15, 19)]
    assert not [t for t in (utc_ms(2026, 11, 26, h) for h in range(24)) if funding_hour_session(t) == "RTH"]
    assert bucket("EXT") == bucket("CLOSED") == "OFF_HOURS" and bucket("RTH") == "RTH"


# ----------------------------------------------------------------------------------------------- funding split
def test_contiguous_blocks_split_on_gaps() -> None:
    rows = [(0, D(1)), (H, D(1)), (3 * H, D(1)), (4 * H, D(1)), (5 * H, D(1)), (9 * H, D(1))]
    assert [len(b) for b in contiguous_blocks(rows)] == [2, 3, 1]


def test_session_stats_runs_and_flips_do_not_cross_gaps() -> None:
    # two blocks: [+,+] gap [+,-,+]; a naive series would give run 3 and 2 flips; within blocks: run 2, flips 2
    rows = [(0, D("0.00001")), (H, D("0.00001")), (10 * H, D("0.00001")), (11 * H, D("-0.00001")), (12 * H, D("0.00001"))]
    st = session_direction_stats(rows, {"DUAL_TAKER": D("0.00002")})
    assert st["blocks"] == 2 and st["longest_positive_run_h"] == 2 and st["sign_flips"] == 2
    assert st["total_carry_bps"] == D("0.3") and st["mean_hourly"] == D("0.000006")
    b = st["by_fee_mode"]["DUAL_TAKER"]
    assert b["round_trip_fee_bps"] == D("0.2") and b["net_hold_bps"] == D("0.1")
    assert b["blocks_beating_fee"] == 0                                # block carries 0.2 bps, 0.1 bps (not > 0.2)
    assert b["net_per_block_strategy_bps"] == D("-0.1")                # (0.2 − 0.2) + (0.1 − 0.2)
    assert b["expected_breakeven_h"] == D("0.00002") / D("0.000006")
    assert b["breakeven_h_from_first_hour"] == 2


def test_split_by_session_buckets_and_directions_are_mirror_images() -> None:
    t0 = utc_ms(2026, 11, 25, 14)                                      # payments 14:00 … 23:00 UTC
    al = [(t0 + i * H, D("0.00001"), D("0.00002") if funding_hour_session(t0 + i * H) == "RTH" else D("0.000005"))
          for i in range(10)]
    fees = round_trip_fees(D(0), D("0.000225"), D("0.00003"), D("0.00009"))
    out = split_by_session(al, lambda t: bucket(funding_hour_session(t)), fees)
    assert out["RTH"]["hours"] == 7 and out["OFF_HOURS"]["hours"] == 3 and out["ALL"]["hours"] == 10
    assert out["RTH"]["diff_hl_minus_arcus_annualized"] == D("0.00001") * HOURS_PER_YEAR
    assert out["OFF_HOURS"]["diff_hl_minus_arcus_annualized"] == D("-0.000005") * HOURS_PER_YEAR
    r = out["RTH"]["directions"]
    assert r["LONG_ARCUS_SHORT_HL"]["annualized"] == -r["SHORT_ARCUS_LONG_HL"]["annualized"]
    assert r["LONG_ARCUS_SHORT_HL"]["pct_hours_positive"] == 100 and r["SHORT_ARCUS_LONG_HL"]["pct_hours_positive"] == 0
    assert out["ALL"]["diff_sign_flips_within_blocks"] == 2            # − + … + −  (14:00 off, 15–21 RTH, 22–23 off)


def test_round_trip_fees_from_real_equity_fees() -> None:
    """Live 2026-11-27: Arcus equities tier 0 maker 0 ppm / taker 225 ppm (feeSchedules); io growth mode, scale 1.0:
    maker 0.3 bps / taker 0.9 bps."""
    f = round_trip_fees(D(0), D("0.000225"), D("0.00003"), D("0.00009"))
    assert f["DUAL_TAKER"] * BPS == D("6.300") and f["MAKER_ARCUS_TAKER_HL"] * BPS == D("1.800")
    assert f["MAKER_HL_TAKER_ARCUS"] * BPS == D("5.100")
    st = session_direction_stats([(i * H, D("0.00001")) for i in range(30)], f)          # 0.1 bps / h
    assert st["by_fee_mode"]["MAKER_ARCUS_TAKER_HL"]["expected_breakeven_h"] == D(18)
    assert st["by_fee_mode"]["MAKER_ARCUS_TAKER_HL"]["breakeven_h_from_first_hour"] == 18
    assert st["by_fee_mode"]["DUAL_TAKER"]["net_hold_bps"] == D("3.0") - D("6.300")
    assert st["by_fee_mode"]["DUAL_TAKER"]["breakeven_h_from_first_hour"] is None        # needs 63 h, only 30
    assert session_direction_stats([], f) == {"hours": 0}


# ----------------------------------------------------------------------------------------------- trade tape
ARCUS_DOC_MSG = {"type": "channel_data", "channel": "trades", "id": "BTC-USD", "contents": [
    {"marketDisplayName": "BTC-USD", "marketId": 1, "side": "BUY", "price": D("94500.0"), "size": D("0.25"),
     "tradeId": "18000809", "timestamp": 1712345679000000, "makerOrderId": "509198ca54b04ee8",
     "takerOrderId": "15cdceb34c4f400f", "sequenceNumber": 5001}]}
HL_MSG = {"channel": "trades", "data": [
    {"coin": "io:NVDA", "side": "B", "px": "150.62", "sz": "0.5", "hash": "0x0", "time": 1795720034058, "tid": 210522},
    {"coin": "io:NVDA", "side": "A", "px": "150.60", "sz": "1.25", "hash": "0x0", "time": 1795720034059, "tid": 7},
    {"coin": "io:MU", "side": "A", "px": "600", "sz": "1", "hash": "0x0", "time": 1795720034059, "tid": 8}]}


def test_parse_arcus_trades_doc_example() -> None:
    (t,) = parse_arcus_trades(ARCUS_DOC_MSG, "BTC", "BTC-USD", 1712345679100)
    assert (t.venue, t.symbol, t.exch_ts_us, t.recv_ms) == ("arcus", "BTC", 1712345679000000, 1712345679100)
    assert t.price == D("94500.0") and isinstance(t.price, Decimal) and t.size == D("0.25")
    assert (t.side, t.raw_side, t.trade_id) == ("BUY", "BUY", "18000809")
    assert parse_arcus_trades(ARCUS_DOC_MSG, "ETH", "ETH-USD", 0) == []         # other market's frame ignored
    assert parse_arcus_trades({**ARCUS_DOC_MSG, "type": "subscribed"}, "BTC", "BTC-USD", 0) == []


def test_parse_hl_trades_ms_to_us_and_side_mapping() -> None:
    ts = parse_hl_trades(HL_MSG, "NVDA", "io:NVDA", 5)
    assert len(ts) == 2                                                          # io:MU row filtered
    assert ts[0].exch_ts_us == 1795720034058000 and ts[0].side == "BUY" and ts[0].raw_side == "B"
    assert ts[1].side == "SELL" and ts[1].price == D("150.60") and ts[1].trade_id == "7"
    assert parse_hl_trades({"channel": "l2", "data": {}}, "NVDA", "io:NVDA", 5) == []


def test_store_trades_exact_decimal_text_and_dedup(tmp_path: pathlib.Path) -> None:
    st = Store(str(tmp_path / "t.sqlite"))
    rows = parse_hl_trades(HL_MSG, "NVDA", "io:NVDA", 5)
    assert st.trades(rows) == 2
    assert st.trades(rows) == 0                                                  # HL replays 30 trades on resubscribe
    st.commit()
    got = st.db.execute("SELECT venue, symbol, exch_ts_us, recv_ms, price, size, side, raw_side, trade_id FROM trades "
                        "ORDER BY exch_ts_us").fetchall()
    assert got[0] == ("hyperliquid", "NVDA", 1795720034058000, 5, "150.62", "0.5", "BUY", "B", "210522")
    assert all(isinstance(r[4], str) for r in got)


def test_feeds_multiplex_trades_on_existing_socket_without_touching_book() -> None:
    got: list = []
    af = ArcusBookFeed("BTC-USD", lambda *a: None, trade_sink=got.extend)
    af.handle(ARCUS_DOC_MSG, 1)
    assert len(got) == 1 and not af.book.valid and af.stats.extra["trades"] == 1
    hf = HlBookFeed("NVDA", "io:NVDA", lambda *a: None, trade_sink=got.extend)
    hf.handle(HL_MSG, 2)
    assert len(got) == 3 and not hf.book.valid and hf.stats.extra["trades"] == 2
    quiet = ArcusBookFeed("BTC-USD", lambda *a: None)                            # no --record-trades: ignored
    quiet.handle(ARCUS_DOC_MSG, 1)
    assert "trades" not in quiet.stats.extra


# ----------------------------------------------------------------------------------------------- fill-through filter
def test_legs_mapping_all_four_cases() -> None:
    a = legs("BUY_ARCUS_SELL_HL", "MAKER_ARCUS_TAKER_HL")
    assert (a.maker_venue, a.maker_side, a.maker_px_field, a.hedge_venue, a.hedge_side) == \
        ("arcus", "BUY", "open_buy_px", "hyperliquid", "SELL")
    b = legs("BUY_HL_SELL_ARCUS", "MAKER_ARCUS_TAKER_HL")
    assert (b.maker_venue, b.maker_side, b.hedge_venue, b.hedge_side, b.hedge_px_field) == \
        ("arcus", "SELL", "hyperliquid", "BUY", "open_buy_px")
    c = legs("BUY_ARCUS_SELL_HL", "MAKER_HL_TAKER_ARCUS")
    assert (c.maker_venue, c.maker_side, c.hedge_venue, c.hedge_side) == ("hyperliquid", "SELL", "arcus", "BUY")
    d = legs("BUY_HL_SELL_ARCUS", "MAKER_HL_TAKER_ARCUS")
    assert (d.maker_venue, d.maker_side, d.maker_px_field, d.hedge_venue, d.hedge_side) == \
        ("hyperliquid", "BUY", "open_buy_px", "arcus", "SELL")
    with pytest.raises(ValueError):
        legs("BUY_ARCUS_SELL_HL", "DUAL_TAKER")


def test_crosses_touch_vs_through() -> None:
    assert crosses("BUY", D(100), D(100), False) and not crosses("BUY", D(100), D(100), True)
    assert crosses("BUY", D(100), D("99.99"), True) and not crosses("BUY", D(100), D("100.01"), False)
    assert crosses("SELL", D(100), D(100), False) and crosses("SELL", D(100), D("100.01"), True)
    assert not crosses("SELL", D(100), D("99.99"), False)


def test_fill_evidence_trade_criterion_and_window() -> None:
    trades = [(1000, D("100.5")), (2000, D("100.0")), (9000, D("99"))]
    assert fill_evidence("BUY", D(100), 1000, 5000, trades, []) == "trade"           # touch at t+1 s
    assert fill_evidence("BUY", D(100), 1000, 5000, trades, [], through=True) is None  # 99 is at t+8 s: outside
    assert fill_evidence("BUY", D(100), 1000, 10000, trades, [], through=True) == "trade"
    assert fill_evidence("BUY", D(100), 2000, 5000, trades, []) is None             # trade AT t is not after t
    assert fill_evidence("SELL", D(100), 0, 5000, trades, []) == "trade"            # 100.5 ≥ 100


def test_fill_evidence_book_advance_criterion() -> None:
    tops = [(1000, D("99.9"), D("100.2")), (2000, D("99.9"), D("100.1")), (3000, D("99.8"), D("100.0"))]
    assert fill_evidence("BUY", D(100), 0, 5000, [], tops) == "book"                # ask fell to our bid at t+3 s
    assert fill_evidence("BUY", D(100), 0, 2000, [], tops) is None                  # not within 2 s
    assert fill_evidence("BUY", D(100), 0, 5000, [], tops, through=True) is None    # touch only
    assert fill_evidence("SELL", D("100.1"), 0, 5000, [], tops) is None             # bid never rose to 100.1
    assert fill_evidence("SELL", D("99.9"), 0, 5000, [], tops) == "book"


def test_adverse_bps_sign() -> None:
    assert adverse_bps("SELL", D(100), D("99.9")) == D(10)        # we sell the hedge: lower bid hurts
    assert adverse_bps("BUY", D(100), D("100.1")) == D(10)        # we buy the hedge: higher ask hurts
    assert adverse_bps("BUY", D(100), D("99.9")) == D(-10)


def _mini_db(with_trades: bool) -> sqlite3.Connection:
    """MU-like artifact: maker SELL on HL at its ask 101.0 for 3 s while the HL bid stays at 100.0 and nothing
    trades on HL; hedge = BUY on Arcus (taker VWAP 100.50 → 100.52 → 100.55 → 100.60 …)."""
    db = sqlite3.connect(":memory:")
    from phase0_probe.store import SCHEMA
    db.executescript(SCHEMA)
    base = 1_000_000
    for i in range(10):
        ts = base + i * 1000
        pos = i < 3
        hedge = ["100.50", "100.52", "100.55", "100.60", "100.61", "100.62", "100.63", "100.64", "100.65", "100.66"][i]
        db.execute("INSERT INTO opportunities (ts_ms, symbol, q_usd, direction, mode, status, open_buy_px, open_sell_px, "
                   "net_resid_bps) VALUES (?,?,?,?,?,?,?,?,?)",
                   (ts, "MU", "100", "BUY_ARCUS_SELL_HL", "MAKER_HL_TAKER_ARCUS", "ok", hedge, "101.0",
                    "3.0" if pos else "-1.0"))
        db.execute("INSERT INTO book_health (ts_ms, symbol, venue, ready, valid, best_bid, best_ask) VALUES "
                   "(?,?,?,?,?,?,?)", (ts, "MU", "hyperliquid", 1, 1, "100.0", "101.0"))
        db.execute("INSERT INTO book_health (ts_ms, symbol, venue, ready, valid, best_bid, best_ask) VALUES "
                   "(?,?,?,?,?,?,?)", (ts, "MU", "arcus", 1, 1, "100.4", hedge))
    if with_trades:                                    # an HL buyer lifts 101.0 at t0 + 2.5 s
        db.execute("INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?)",
                   ("hyperliquid", "MU", (base + 2500) * 1000, base + 2600, "101.0", "0.2", "BUY", "B", "1"))
    return db


def test_maker_realism_suppresses_artifact_without_evidence() -> None:
    db = _mini_db(with_trades=False)
    (row,) = maker_realism(db, 1_000_000, 1_009_000)["rows"]
    assert row["opp_seconds_raw"] == 3 and row["runs_raw"] == 1 and row["opp_seconds_filtered"] == 0
    assert row["suppressed_pct"] == 100
    u = row["adverse_selection"]["unfiltered_triggers"]
    assert u["+1s"]["n"] == 1 and u["+1s"]["mean_adverse_bps"] == (D("100.52") - D("100.50")) / D("100.50") * BPS
    assert u["+5s"]["mean_adverse_bps"] == (D("100.62") - D("100.50")) / D("100.50") * BPS


def test_maker_realism_trade_criterion_keeps_and_measures_adverse_selection() -> None:
    db = _mini_db(with_trades=True)
    r = maker_realism(db, 1_000_000, 1_009_000)
    (row,) = r["rows"]
    assert r["trades_table"] and row["evidence_trade"] == 3 and row["opp_seconds_filtered"] == 3   # trade at t0+2.5 s
    trig = row["adverse_selection"]["triggers"]
    assert trig["+3s"]["n"] == 1 and trig["+3s"]["mean_adverse_bps"] == (D("100.60") - D("100.50")) / D("100.50") * BPS
    assert trig["+3s"]["pct_adverse"] == 100 and trig["+3s"]["top_of_book_fallback"] == 0
    strict = maker_realism(db, 1_000_000, 1_009_000, through=True)["rows"][0]
    assert strict["opp_seconds_filtered"] == 0                     # trade only TOUCHED 101.0
    sc = side_consistency(db, 1_000_000, 1_009_000)
    assert sc["hyperliquid/B"]["trades"] == 1 and sc["hyperliquid/B"]["pct_at_or_above_mid"] == 100


def test_thanksgiving_mu_sample_artifact_is_suppressed() -> None:
    """Real recording (reports/rwa_connectivity_10m.sqlite, NYSE closed, no trades table): MU MAKER_HL_TAKER_ARCUS
    showed net_resid > 0 in ~86 % of seconds; the book-advance criterion keeps none of them within 5 s."""
    path = ROOT / "reports" / "rwa_connectivity_10m.sqlite"
    if not path.exists():
        pytest.skip("sample DB not present")
    db = sqlite3.connect(path)
    lo, hi = db.execute("SELECT MIN(ts_ms), MAX(ts_ms) FROM opportunities").fetchone()
    r = maker_realism(db, lo, hi)
    assert not r["trades_table"]
    mu = [x for x in r["rows"] if x["symbol"] == "MU" and x["mode"] == "MAKER_HL_TAKER_ARCUS"]
    assert len(mu) == 3
    for x in mu:
        assert x["opp_seconds_raw"] >= 500 and x["opp_seconds_filtered"] == 0 and x["evidence_trade"] == 0
