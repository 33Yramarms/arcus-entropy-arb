"""Arcus sequence continuity / resync and Hyperliquid l2 diff application."""
from __future__ import annotations

import base64
import json
import zlib
from decimal import Decimal

import pytest

from phase0_probe.book import (ArcusSync, BookIntegrityError, OrderBook, SequenceGap, arcus_apply_delta,
                               arcus_apply_snapshot, arcus_heartbeat, hl_apply_diff, hl_apply_snapshot,
                               hl_check_against_snapshot)
from phase0_probe.feeds import ArcusBookFeed, HlBookFeed, hl_decode

D = Decimal


def snap(seq: int, bids: list[list[str]] | None = None, asks: list[list[str]] | None = None) -> dict:
    return {"bids": bids if bids is not None else [["100", "1"], ["99", "2"]],
            "asks": asks if asks is not None else [["101", "1"], ["102", "2"]], "lastSequenceId": seq,
            "timestamp": 1_000_000}


def delta(seq: int, bids: list[list[str]] | None = None, asks: list[list[str]] | None = None) -> dict:
    return {"bids": bids or [], "asks": asks or [], "lastSequenceId": seq, "timestamp": 2_000_000}


def test_arcus_contiguous_deltas_apply_and_zero_removes() -> None:
    b = OrderBook("arcus", "BTC-USD")
    arcus_apply_snapshot(b, snap(10), 1)
    arcus_apply_delta(b, delta(11, bids=[["100", "0"]], asks=[["100.5", "3"]]), 2, 20)
    assert b.best_bid() == D(99) and b.best_ask() == D("100.5") and b.last_seq == 11 and b.confirmed_ms == 2
    assert b.exchange_ts_ms == 2000                                         # µs -> ms


def test_arcus_gap_raises_and_invalidates() -> None:
    b = OrderBook("arcus", "BTC-USD")
    arcus_apply_snapshot(b, snap(10), 1)
    with pytest.raises(SequenceGap) as ei:
        arcus_apply_delta(b, delta(12), 2, 20)
    assert ei.value.expected == 11 and ei.value.got == 12 and not b.valid


def test_arcus_duplicate_delta_is_ignored() -> None:
    b = OrderBook("arcus", "BTC-USD")
    arcus_apply_snapshot(b, snap(10), 1)
    arcus_apply_delta(b, delta(11, bids=[["100", "5"]]), 2, 20)
    arcus_apply_delta(b, delta(11, bids=[["100", "9"]]), 3, 20)
    assert b.bids[D(100)] == D(5) and b.last_seq == 11


def test_arcus_resync_drops_old_and_applies_newer_buffered_deltas() -> None:
    b = OrderBook("arcus", "BTC-USD")
    sync = ArcusSync(b, 100)
    for s in (9, 10, 11, 12):
        sync.on_delta(delta(s, bids=[["100", str(s)]]), s)
    assert not sync.on_snapshot(snap(7), 50)                                # buffer starts later than 8
    assert sync.on_snapshot(snap(10), 60) and b.valid and b.last_seq == 12 and b.bids[D(100)] == D(12)


def test_arcus_first_delta_gap_after_subscribe_triggers_resync_not_bad_book() -> None:
    b = OrderBook("arcus", "BTC-USD")
    sync = ArcusSync(b, 100)
    assert sync.on_snapshot(snap(10), 1) and sync.provisional
    sync.on_delta(delta(13), 2)                                             # observed live: ids skipped
    assert not b.valid and sync.baseline_gaps == 1
    sync.on_delta(delta(14), 3)
    assert sync.on_snapshot(snap(12), 4) and b.last_seq == 14


def test_arcus_midstream_gap_after_baseline_raises() -> None:
    b = OrderBook("arcus", "BTC-USD")
    sync = ArcusSync(b, 100)
    sync.on_snapshot(snap(10), 1)
    sync.on_delta(delta(11), 2)
    with pytest.raises(SequenceGap):
        sync.on_delta(delta(13), 3)


def test_arcus_heartbeat_confirm_behind_ahead_mismatch() -> None:
    b = OrderBook("arcus", "BTC-USD")
    arcus_apply_snapshot(b, snap(10), 1)
    assert arcus_heartbeat(b, snap(10), 5, 20) == "confirmed" and b.confirmed_ms == 5
    assert arcus_heartbeat(b, snap(11), 6, 20) == "behind" and b.confirmed_ms == 5
    assert arcus_heartbeat(b, snap(9), 7, 20) == "ahead"
    assert arcus_heartbeat(b, snap(10, bids=[["100", "7"]]), 8, 20) == "mismatch"


def test_arcus_feed_reconnect_on_midstream_gap() -> None:
    events: list[tuple] = []
    f = ArcusBookFeed("BTC-USD", lambda *a: events.append(a))
    f.handle({"type": "subscribed", "channel": "l2OrderbookUpdates", "id": "BTC-USD", "contents": snap(10)}, 1)
    f.handle({"type": "channel_data", "channel": "l2OrderbookUpdates", "id": "BTC-USD", "contents": delta(11)}, 2)
    with pytest.raises(SequenceGap):
        f.handle({"type": "channel_data", "channel": "l2OrderbookUpdates", "id": "BTC-USD", "contents": delta(15)}, 3)


def test_arcus_feed_checksum_mismatch_raises() -> None:
    f = ArcusBookFeed("BTC-USD", lambda *a: None)
    f.handle({"type": "subscribed", "channel": "l2OrderbookUpdates", "id": "BTC-USD", "contents": snap(10)}, 1)
    with pytest.raises(BookIntegrityError):
        f.handle({"type": "channel_data", "channel": "l2Orderbook", "id": "BTC-USD",
                  "contents": snap(10, asks=[["101", "9"]])}, 2)


def test_hl_snapshot_and_diff() -> None:
    b = OrderBook("hyperliquid", "BTC")
    hl_apply_snapshot(b, {"coin": "BTC", "time": 1, "levels": [
        [{"px": "100", "sz": "1", "n": 1}, {"px": "99", "sz": "2", "n": 1}],
        [{"px": "101", "sz": "1", "n": 1}, {"px": "102", "sz": "2", "n": 1}]]}, 10)
    hl_apply_diff(b, {"c": "BTC", "t": 2, "l": [[{"p": "99.5", "s": "4"}], [{"p": "102", "s": "3"}]],
                      "r": [[0], []]}, 11)
    assert b.sorted_bids() == [(D("99.5"), D(4)), (D(99), D(2))]
    assert b.sorted_asks() == [(D(101), D(1)), (D(102), D(3))] and b.exchange_ts_ms == 2


def test_hl_diff_bad_index_invalidates() -> None:
    b = OrderBook("hyperliquid", "BTC")
    hl_apply_snapshot(b, {"time": 1, "levels": [[{"px": "100", "sz": "1"}], [{"px": "101", "sz": "1"}]]}, 1)
    with pytest.raises(BookIntegrityError):
        hl_apply_diff(b, {"t": 2, "l": [[], []], "r": [[5], []]}, 2)
    assert not b.valid


def test_hl_compressed_diff_and_checksum() -> None:
    diff = {"c": "BTC", "t": 3, "l": [[{"p": "100", "s": "5"}], []], "r": [[], []]}
    co = zlib.compressobj(wbits=-15)
    payload = base64.b64encode(co.compress(json.dumps(diff).encode()) + co.flush()).decode()
    assert hl_decode(payload)["t"] == 3
    f = HlBookFeed("BTC", "BTC", lambda *a: None)
    f.handle({"channel": "l2", "data": {"s": {"coin": "BTC", "time": 1, "levels": [
        [{"px": "100", "sz": "1"}], [{"px": "101", "sz": "1"}]]}}}, 1)
    f.handle({"channel": "l2", "data": {"c": payload}}, 2)
    assert f.book.bids[D(100)] == D(5)
    snapshot = {"coin": "BTC", "time": 3, "levels": [[{"px": "100", "sz": "5"}], [{"px": "101", "sz": "1"}]]}
    assert hl_check_against_snapshot(f.book, snapshot) is True
    f.handle({"channel": "l2Book", "data": snapshot}, 3)
    assert f.stats.checks_ok == 1
    with pytest.raises(BookIntegrityError):
        f.handle({"channel": "l2Book", "data": {**snapshot, "levels": [[{"px": "100", "sz": "6"}], []]}}, 4)


def test_hl_doc_example_payload_decodes() -> None:
    got = hl_decode("q1ZyCnFWsqpWyk0syg6oULJSsjQ3NTDQM1Wq1VFyDfFAkTI2MzXQMwJLVVRWWfmFuTiiyBuamOoZKdXWAgA=")
    assert got["BTC"]["markPx"] == "97500.5" and got["xyz:NVDA"]["markPx"] == "145.2"


def test_hl_funding_from_active_asset_ctx_is_decimal() -> None:
    f = HlBookFeed("SOL", "SOL", lambda *a: None)
    f.handle({"channel": "activeAssetCtx", "data": {"coin": "SOL", "ctx": {"funding": "-0.0000003407"}}}, 1)
    assert f.funding.current_hourly == D("-0.0000003407")
