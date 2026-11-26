"""Discovery parsing, fee math, Decimal helpers, SQLite round trip, analysis, and static safety scans."""
from __future__ import annotations

import ast
import pathlib
import re
from decimal import Decimal

import pytest

from phase0_probe.analysis import summarize
from phase0_probe.book import OrderBook
from phase0_probe.dec import D, floor_to_step, loads
from phase0_probe.discovery import overlap, parse_arcus, parse_hl, parse_predicted
from phase0_probe.model import Direction, Mode, VenueSpec, evaluate
from phase0_probe.store import Store
from phase0_probe.venues import hip3_fee_scale

ROOT = pathlib.Path(__file__).resolve().parents[1]
CODE = sorted((ROOT / "src").rglob("*.py")) + sorted((ROOT / "scripts").rglob("*.py"))


def test_loads_never_produces_float() -> None:
    v = loads('{"a": 0.1, "b": [1.5e-7, 2], "c": "3.3"}')
    assert isinstance(v["a"], Decimal) and isinstance(v["b"][0], Decimal) and v["b"][1] == 2


def test_D_refuses_float_and_bool() -> None:
    with pytest.raises(TypeError):
        D(0.1)  # noqa: the point of the test
    with pytest.raises(TypeError):
        D(True)
    assert D("1.10") == Decimal("1.10") and floor_to_step(D("0.0016666"), D("0.00001")) == D("0.00166")


def test_hip3_fee_scale_matches_doc_formula() -> None:
    assert hip3_fee_scale(D("1.0"), False) == D(2)
    assert hip3_fee_scale(D("0.5"), False) == D("1.5")
    assert hip3_fee_scale(D("1.0"), True) == D("0.2")


ARCUS = {"markets": [{"marketDisplayName": "BTC-USD", "marketId": 1, "status": "ONLINE", "baseAsset": "BTC",
                      "stepSize": "0.00000001", "tickSize": "0.1", "minOrderNotional": "5", "minOrderSize": "0.0001",
                      "effectiveMakerFeePpm": 150, "effectiveTakerFeePpm": 450, "fundingRate": "0.0000125",
                      "nextFundingRate": "0.00001", "initialMarginFraction": "0.025", "type": "PERPETUAL"},
                     {"marketDisplayName": "NVDA-USD", "marketId": 9, "status": "ONLINE", "baseAsset": "NVDA",
                      "stepSize": "0.0000001", "tickSize": "0.01", "minOrderNotional": "5", "minOrderSize": "0.01",
                      "effectiveMakerFeePpm": 0, "effectiveTakerFeePpm": 225, "fundingRate": "0",
                      "nextFundingRate": None, "initialMarginFraction": "0.05", "type": "PERPETUAL"}]}
FEES = {"feeSchedules": [{"marketId": 9, "tiers": [{"level": 1, "makerFeePpm": 0, "takerFeePpm": 200},
                                                     {"level": 0, "makerFeePpm": 0, "takerFeePpm": 225}]}]}
CORE = [{"universe": [{"name": "BTC", "szDecimals": 5, "maxLeverage": 40}]},
        [{"funding": "0.0000125", "markPx": "60000", "dayNtlVlm": "1"}]]
IO = [{"universe": [{"name": "io:NVDA", "szDecimals": 3, "maxLeverage": 25, "deployerFeeScale": "1.0",
                     "growthMode": "enabled"},
                    {"name": "io:AAPL", "szDecimals": 3, "maxLeverage": 25, "onlyIsolated": True,
                     "marginMode": "noCross", "deployerFeeScale": "1.0"}]},
      [{"funding": "-0.000001", "markPx": "150"}, {"funding": "0.0", "markPx": "300"}]]


def test_parse_and_overlap() -> None:
    a = parse_arcus(ARCUS, FEES)
    assert a[0].maker_fee == D("0.00015") and a[0].taker_fee == D("0.00045") and a[0].max_leverage == D(40)
    assert a[1].taker_fee == D("0.000225")                                      # tier 0 of the market schedule
    pred = parse_predicted([["BTC", [["BinPerp", {"fundingRate": "0.0001"}], ["HlPerp", {"fundingRate": "0.00002"}]]]])
    hl = parse_hl(CORE, dex="", predicted=pred) + parse_hl(IO, dex="io")
    assert hl[0].venue == "hl_core" and hl[0].step == D("0.00001") and hl[0].predicted_hourly == D("0.00002")
    nv = hl[1]
    assert nv.venue == "hl_io" and nv.base == "NVDA" and nv.growth_mode and nv.taker_fee == D("0.00045") * D("0.2")
    assert hl[2].margin_mode == "noCross" and hl[2].taker_fee == D("0.0009")
    rows = overlap(a, hl)
    assert [r["symbol"] for r in rows] == ["BTC", "NVDA"] and rows[0]["priority"]
    assert rows[0]["funding_diff_annual_hl_minus_arcus"] == (D("0.00002") - D("0.00001")) * 8760
    assert rows[0]["rt_dual_taker_fee_bps"] == D(18)


def _book(v: str, bid: str, ask: str, now: int, latency: int = 50) -> OrderBook:
    b = OrderBook(v, "BTC")
    b.replace([(D(bid), D(5))], [(D(ask), D(5))])
    b.valid, b.confirmed_ms, b.last_msg_ms, b.last_change_ms, b.latency_ms = True, now, now, now - 30_000, latency
    return b


def test_store_and_analysis_runs(tmp_path: pathlib.Path) -> None:
    st = Store(str(tmp_path / "x.sqlite"))
    sa = VenueSpec("arcus", "BTC", D("0.00000001"), D(5), D("0.00015"), D("0.00045"))
    sb = VenueSpec("hyperliquid", "BTC", D("0.00001"), D(10), D("0.00015"), D("0.00045"))
    t0 = 1_800_000_000_000
    hl_mid = ["60300", "60300", "60300", "60000", "60300", "60300", "60300"]  # runs of 3 s and 1 s
    for i, m in enumerate(hl_mid):
        ts = t0 + i * 1000
        a = _book("arcus", "59999", "60001", ts)
        a.provisional = i == 6                                                # resyncing -> NOT_READY
        hb = D(m)
        b = _book("hyperliquid", str(hb - 1), str(hb + 1), ts, latency=600 if i == 5 else 50)   # i=5: slow link
        rows = [evaluate(book_a=a, book_b=b, spec_a=sa, spec_b=sb, q_usd=D(100), direction=d, mode=Mode.DUAL_TAKER,
                         now_ms=ts, basis_median_bps=D(0)) for d in Direction]
        st.opportunities(ts, rows)
        st.book_health([(ts, "BTC", "hyperliquid", int(b.ready), int(b.valid), b.latency_ms, b.idle_ms(ts),
                         b.silence_ms(ts), b.age_ms(ts), None, None, 1, 1, None)])
        st.funding([(ts, "BTC", "arcus", "0.0000125", "0.00001"), (ts, "BTC", "hyperliquid", "0.00002", None)])
    st.commit()
    res = summarize(st.db, window_ms=None)
    r = next(x for x in res["rows"] if x["symbol"] == "BTC" and x["q_usd"] == "100" and x["mode"] == "DUAL_TAKER")
    assert r["seconds"] == 7 and r["opp_seconds"] == 4 and r["stale_seconds"] == 1 and r["not_ready_seconds"] == 1
    assert r["avg_duration_s"] == D("2") and r["max_run_s"] == 3
    assert r["pct_net_pos"] == D(4) / D(7) * 100
    h = res["health"]["BTC/hyperliquid"]
    assert h["latency_ms_max"] == 600 and h["book_idle_ms_p50"] == 30_000      # idle 30 s but never gated
    assert h["pct_latency_over_threshold"] == D(1) / D(7) * 100
    f = res["funding"]["BTC"]
    assert f["diff_annual_hl_minus_arcus"] == (D("0.00002") - D("0.00001")) * 8760
    st.close()


# ----------------------------------------------------------------------------------------------- static scans
def test_no_float_anywhere_in_src_and_scripts() -> None:
    for path in CODE:
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            assert not (isinstance(node, ast.Constant) and isinstance(node.value, float)), f"float literal in {path}"
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "float", f"float() call in {path}:{node.lineno}"
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "time":
                assert node.attr in ("time_ns", "monotonic_ns"), f"float clock time.{node.attr} in {path}"
            if isinstance(node, ast.Attribute) and node.attr in ("fromfloat", "from_float"):
                raise AssertionError(f"from_float in {path}")
            if isinstance(node, ast.Name) and node.id == "float":
                raise AssertionError(f"'float' referenced in {path}:{node.lineno}")


def test_read_only_no_signing_keys_or_order_endpoints() -> None:
    banned = re.compile(r"placeOrder|cancelOrder|scheduleCancel|private_?key|signing|eth_account|nacl|ed25519|"
                        r"secp256k1|/exchange\b|\"action\"|api_?secret", re.IGNORECASE)
    for path in CODE:
        text = path.read_text()
        hits = [m.group(0) for m in banned.finditer(text)]
        assert not hits, f"{path}: {hits}"


# PR #1.6: the public trade tape may be RECORDED (``--record-trades``) and used by the Maker fill-through filter,
# but never as a price input: only these modules may touch the ``trades`` channel / table.
TRADE_TAPE_ALLOWED = {"trades.py", "feeds.py", "store.py", "realism.py", "record_spreads.py", "analyze_opportunity.py"}
PRICING_MODULES = {"model.py", "book.py", "recorder.py", "analysis.py", "funding.py", "discovery.py"}


def test_never_reads_last_trade_price() -> None:
    for path in CODE:
        text = path.read_text()
        assert "lastTradePrice" not in text, path
        if path.name not in TRADE_TAPE_ALLOWED:
            assert "trades\"" not in text, path


def test_pricing_modules_never_touch_the_trade_tape() -> None:
    for path in CODE:
        if path.name in PRICING_MODULES:
            text = path.read_text()
            assert "phase0_probe.trades" not in text and "phase0_probe.realism" not in text, path
            assert "trades\"" not in text and "FROM trades" not in text, path
