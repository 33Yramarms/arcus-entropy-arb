"""Sprint 2 (P0/P1 hardening): supervision, SIGTERM/SIGHUP, SQLite WAL / locked commits, reconnect backoff, HL
watchdog, Arcus delta-stall guard, book edge cases, realism adverse-selection / trades-table semantics.
No network: websockets.connect, clocks and sleeps are faked."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import pathlib
import random
import signal
import sqlite3
import sys
import time
from decimal import Decimal
from typing import Any

import pytest

from phase0_probe import feeds
from phase0_probe.book import ArcusSync, BookIntegrityError, OrderBook, arcus_apply_snapshot, hl_apply_diff, \
    hl_apply_snapshot
from phase0_probe.feeds import ArcusBookFeed, Backoff, FeedWatchdog, HlBookFeed
from phase0_probe.model import Direction, Mode, VenueSpec, evaluate
from phase0_probe.realism import has_trades_table, maker_realism
from phase0_probe.recorder import Pair, Recorder
from phase0_probe.store import SCHEMA, Store

D = Decimal
ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_record_spreads() -> Any:
    spec = importlib.util.spec_from_file_location("record_spreads_s2", ROOT / "scripts" / "record_spreads.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["record_spreads_s2"] = mod
    spec.loader.exec_module(mod)
    return mod


rs = _load_record_spreads()


def _specs(sym: str = "MU") -> tuple[VenueSpec, VenueSpec]:
    return (VenueSpec("arcus", sym, D("0.01"), D(0), D(0), D("0.000225")),
            VenueSpec("hyperliquid", sym, D("0.01"), D(10), D("0.00003"), D("0.00009")))


# ============================================================================ P0: supervisor + signals
def test_supervise_crash_writes_event_invalidates_and_restarts() -> None:
    events: list[tuple] = []
    feed = ArcusBookFeed("MU-USD", lambda *a: None)
    arcus_apply_snapshot(feed.book, {"bids": [["100", "1"]], "asks": [["101", "1"]], "lastSequenceId": 5}, 1)
    assert feed.book.valid
    calls = {"n": 0}
    stop = asyncio.Event()

    async def flaky() -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom in feed")
        assert not feed.book.valid                     # invalidated right after the crash, before the restart
        stop.set()

    health = rs.TaskHealth("arcus:MU")

    async def go() -> None:
        await rs._supervise("arcus:MU", flaky, stop, lambda *a: events.append(a), health=health, venue="arcus",
                            symbol="MU-USD", on_crash=feed.invalidate, backoff=Backoff(base_ms=1, cap_ms=2))

    asyncio.run(go())
    assert calls["n"] == 2 and health.crashes == 1 and "boom in feed" in health.last_exc
    assert events and events[0][:3] == ("arcus", "MU-USD", "task_crash") and "boom in feed" in events[0][3]
    assert "crashes=1" in health.meta()


def test_supervise_survives_failing_sink_and_propagates_cancellation() -> None:
    stop = asyncio.Event()
    health = rs.TaskHealth("x")
    n = {"c": 0}

    async def crash_twice() -> None:
        n["c"] += 1
        if n["c"] <= 2:
            raise KeyError("bad")
        await asyncio.Event().wait()                  # then hang until cancelled

    def bad_sink(*_a: Any) -> None:
        raise sqlite3.OperationalError("database is locked")

    async def go() -> None:
        t = asyncio.create_task(rs._supervise("x", crash_twice, stop, bad_sink, health=health,
                                              backoff=Backoff(base_ms=1, cap_ms=2)))
        for _ in range(200):
            await asyncio.sleep(0)
            if n["c"] >= 3:
                break
        await asyncio.sleep(0.05)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t

    asyncio.run(go())
    assert health.crashes == 2 and n["c"] == 3


def test_sigterm_and_sighup_set_stop() -> None:
    for sig in (signal.SIGTERM, signal.SIGHUP):
        async def go() -> dict[str, str]:
            stop, info = asyncio.Event(), {}
            loop = asyncio.get_running_loop()
            installed = rs._install_stop_signals(loop, stop, info)
            assert int(sig) in installed
            os.kill(os.getpid(), sig)
            await asyncio.wait_for(stop.wait(), timeout=2)
            for s_ in installed:
                loop.remove_signal_handler(s_)
            return info
        info = asyncio.run(go())
        assert info["stop_reason"] == f"signal {sig.name}"


def test_main_sigterm_writes_ended_ms_crash_meta_and_closes_db(tmp_path: pathlib.Path,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end on ``record_spreads.main`` with the network replaced: one feed crashes once (restarted), SIGTERM
    arrives -> ``ended_ms``, ``stop_reason``, ``task_crashes:*`` written and the DB closed (WAL checkpointed)."""
    async def fake_specs(pairs: list) -> dict:
        return {sym: _specs(sym) for sym, _ in pairs}

    async def fake_offset() -> tuple[int, int]:
        return 0, 1

    crashed = {"n": 0}

    async def idle(self: Any, stop: asyncio.Event) -> None:
        await stop.wait()

    async def hl_run(self: HlBookFeed, stop: asyncio.Event) -> None:
        if crashed["n"] == 0:
            crashed["n"] += 1
            raise RuntimeError("synthetic HL crash")
        await stop.wait()

    monkeypatch.setattr(rs, "load_specs", fake_specs)
    monkeypatch.setattr(rs, "arcus_clock_offset_ms", fake_offset)
    monkeypatch.setattr(rs.ArcusBookFeed, "run", idle)
    monkeypatch.setattr(rs.ArcusMarketsFeed, "run", idle)
    monkeypatch.setattr(rs.HlBookFeed, "run", hl_run)
    monkeypatch.setattr(rs.Recorder, "poll_predicted", idle)
    monkeypatch.setattr(feeds.Backoff, "next_delay_ms", lambda self, now: 1)
    db = tmp_path / "run.sqlite"

    async def go() -> int:
        loop = asyncio.get_running_loop()
        loop.call_later(1.3, os.kill, os.getpid(), signal.SIGTERM)
        return await rs.main(["--duration-s", "60", "--db", str(db), "--log", str(tmp_path / "run.log"),
                              "--pair", "MU=io:MU", "--record-trades"])

    root_handlers = list(logging.getLogger().handlers)
    t0 = time.monotonic_ns()
    try:
        assert asyncio.run(go()) == 0
    finally:
        for h in logging.getLogger().handlers[:]:
            if h not in root_handlers:
                logging.getLogger().removeHandler(h)
                h.close()
    assert time.monotonic_ns() - t0 < 20 * 10 ** 9                       # stopped by SIGTERM, not by duration
    assert not pathlib.Path(str(db) + "-wal").exists() or pathlib.Path(str(db) + "-wal").stat().st_size == 0
    con = sqlite3.connect(db)
    meta = dict(con.execute("SELECT k, v FROM meta"))
    assert "ended_ms" in meta and meta["stop_reason"] == "signal SIGTERM"
    assert meta["task_crashes:hyperliquid:MU"].startswith("crashes=1") and "synthetic HL crash" in \
        meta["task_crashes:hyperliquid:MU"]
    assert meta["task_crashes_total"] == "1" and meta["task_crashes:sampler"].startswith("crashes=0")
    assert meta["tasks_not_finished"] == "-" and meta["db_commit_errors"] == "0"
    assert "stats:hyperliquid:MU" in meta and "trades_recorded" in meta
    kinds = [r[0] for r in con.execute("SELECT kind FROM events WHERE symbol = 'MU'")]
    assert "task_crash" in kinds
    assert con.execute("SELECT COUNT(*) FROM book_health").fetchone()[0] >= 2     # sampler kept writing (≥1 s)
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


# ============================================================================ P1: SQLite WAL + locked commits
def test_store_uses_wal_and_reader_never_blocks_writer(tmp_path: pathlib.Path) -> None:
    path = str(tmp_path / "w.sqlite")
    st = Store(path)
    assert st.journal_mode() == "wal"
    assert st.db.execute("PRAGMA synchronous").fetchone()[0] == 1               # NORMAL
    assert st.db.execute("PRAGMA busy_timeout").fetchone()[0] == 30_000
    st.event(1, "arcus", "MU", "x", "first")
    st.commit()
    reader = sqlite3.connect(path, isolation_level=None)
    reader.execute("BEGIN")
    assert reader.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1       # long read txn holds a snapshot
    t0 = time.monotonic_ns()
    for i in range(50):
        st.event(2 + i, "arcus", "MU", "x", "while reading")
        st.commit()                                                            # would be 'database is locked' w/o WAL
    assert time.monotonic_ns() - t0 < 2 * 10 ** 9
    assert reader.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1       # snapshot isolation
    reader.execute("COMMIT")
    assert reader.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 51
    reader.close()
    st.close()
    wal = pathlib.Path(path + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0                          # checkpoint(TRUNCATE) on close


def _recorder_with_pair(st: Store) -> Recorder:
    sa, sb = _specs()
    markets = feeds.ArcusMarketsFeed(["MU-USD"], sink=lambda *a: None)
    rec = Recorder(st, [], markets, qs=[D(100)])
    rec.pairs.append(Pair("MU", ArcusBookFeed("MU-USD", rec.sink), HlBookFeed("MU", "io:MU", rec.sink), sa, sb))
    return rec


def test_sampler_skips_second_on_real_lock_and_continues(tmp_path: pathlib.Path) -> None:
    path = str(tmp_path / "l.sqlite")
    st = Store(path)
    st.db.execute("PRAGMA busy_timeout=50")                     # keep the test fast (production: 30 s)
    rec = _recorder_with_pair(st)
    rec.sample(1_000)
    locker = sqlite3.connect(path, isolation_level=None)
    locker.execute("BEGIN IMMEDIATE")                           # another writer holds the write lock
    rec.sample(2_000)                                           # OperationalError -> skipped, no exception
    assert rec.commit_errors == 1 and rec.ticks == 2
    locker.execute("COMMIT")
    locker.close()
    rec.sample(3_000)
    assert rec.ticks == 3
    ts = [r[0] for r in st.db.execute("SELECT DISTINCT ts_ms FROM book_health ORDER BY ts_ms")]
    assert ts == [1_000, 3_000]
    ev = st.db.execute("SELECT kind, detail FROM events WHERE kind = 'db_commit_error'").fetchall()
    assert len(ev) == 1 and "ts=2000" in ev[0][1] and "locked" in ev[0][1]
    st.close()


def test_sampler_commit_operational_error_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    st = Store(":memory:")
    rec = _recorder_with_pair(st)
    real = st.commit
    n = {"c": 0}

    def flaky_commit() -> None:
        n["c"] += 1
        if n["c"] == 1:
            raise sqlite3.OperationalError("database is locked")
        real()

    monkeypatch.setattr(st, "commit", flaky_commit)

    async def go() -> None:
        stop = asyncio.Event()
        t = asyncio.create_task(rec.sampler(stop))
        while rec.ticks < 2:
            await asyncio.sleep(0.05)
        stop.set()
        await asyncio.wait_for(t, timeout=3)
        assert t.exception() is None

    asyncio.run(go())
    assert rec.commit_errors == 1 and rec.ticks >= 2
    # rows of the failed second stayed in the open transaction and were committed with the next one (no loss)
    assert st.db.execute("SELECT COUNT(DISTINCT ts_ms) FROM book_health").fetchone()[0] == rec.ticks
    assert st.db.execute("SELECT COUNT(*) FROM events WHERE kind='db_commit_error'").fetchone()[0] == 1


# ============================================================================ P1: backoff
def test_backoff_exponential_jitter_bounds_and_cap() -> None:
    b = Backoff(rng=random.Random(7))
    lows = [1_000, 2_000, 4_000, 8_000, 16_000]
    for lo in lows:
        d = b.next_delay_ms(0)
        assert lo <= d <= lo + lo // 5
    for _ in range(20):
        d = b.next_delay_ms(0)
        assert 27_000 <= d <= 30_000                              # capped, still jittered
    seen = {Backoff(rng=random.Random(i)).next_delay_ms(0) for i in range(50)}
    assert len(seen) > 10 and min(seen) >= 1_000 and max(seen) <= 1_200


def test_backoff_resets_only_after_stable_session() -> None:
    b = Backoff(rng=random.Random(1))
    for _ in range(4):
        b.next_delay_ms(0)
    assert b.attempt == 4
    b.connected(100_000)
    assert b.next_delay_ms(159_999) >= 16_000                   # up 59.999 s: not stable, keep growing
    b.connected(200_000)
    assert b.next_delay_ms(260_000) <= 1_200 and b.attempt == 1  # up 60 s: reset to base


class FakeWS:
    def __init__(self, frames: list[str] | None = None, on_empty: str = "timeout") -> None:
        self.frames, self.on_empty, self.sent = list(frames or []), on_empty, []

    async def __aenter__(self) -> "FakeWS":
        return self

    async def __aexit__(self, *a: Any) -> None:
        return None

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))

    async def recv(self) -> str:
        await asyncio.sleep(0)
        if self.frames:
            return self.frames.pop(0)
        if self.on_empty == "pong":
            return '{"channel": "pong"}'
        raise asyncio.TimeoutError


class FakeClock:
    def __init__(self, start: int = 1_000_000, step: int = 1_000) -> None:
        self.t, self.step = start, step

    def __call__(self) -> int:
        self.t += self.step
        return self.t


def test_feeds_use_backoff_delays(monkeypatch: pytest.MonkeyPatch) -> None:
    delays: list[int] = []
    stop = asyncio.Event()

    def boom(*_a: Any, **_k: Any) -> FakeWS:
        raise OSError("connection refused")

    async def fake_sleep(stop_: asyncio.Event, ms: int) -> None:
        delays.append(ms)
        if len(delays) == 4:
            stop_.set()

    monkeypatch.setattr(feeds.websockets, "connect", boom)
    monkeypatch.setattr(feeds, "sleep_or_stop", fake_sleep)
    for f in (ArcusBookFeed("MU-USD", lambda *a: None), HlBookFeed("MU", "io:MU", lambda *a: None),
              feeds.ArcusMarketsFeed(["MU-USD"], lambda *a: None)):
        delays.clear()
        stop.clear()
        f.backoff.rng = random.Random(3)
        asyncio.run(f.run(stop))
        assert [d // 1_000 for d in delays] == [1, 2, 4, 8] and f.stats.reconnects == 4, type(f).__name__


# ============================================================================ P1: payload errors, HL watchdog
def test_payload_error_invalidates_and_reconnects(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple] = []
    f = ArcusBookFeed("MU-USD", lambda *a: events.append(a))
    snapshot = {"type": "subscribed", "channel": "l2OrderbookUpdates", "id": "MU-USD",
                "contents": {"bids": [["100", "1"]], "asks": [["101", "1"]], "lastSequenceId": 1}}
    monkeypatch.setattr(feeds.websockets, "connect", lambda *a, **k: FakeWS([json.dumps(snapshot), "not json{"]))
    stop = asyncio.Event()

    async def fake_sleep(stop_: asyncio.Event, ms: int) -> None:
        stop_.set()

    monkeypatch.setattr(feeds, "sleep_or_stop", fake_sleep)
    asyncio.run(f.run(stop))
    assert any(e[2] == "payload_error" for e in events) and not f.book.valid
    assert f.stats.extra["payload_errors"] == 1 and f.stats.reconnects == 1


def test_hl_watchdog_fires_after_15s_silence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feeds, "now_ms", FakeClock(step=1_000))
    ws = FakeWS(on_empty="timeout")
    monkeypatch.setattr(feeds.websockets, "connect", lambda *a, **k: ws)
    f = HlBookFeed("MU", "io:MU", lambda *a: None)
    with pytest.raises(FeedWatchdog):
        asyncio.run(f._session(asyncio.Event()))
    assert any(m.get("method") == "ping" for m in ws.sent)            # it did ping; nothing (not even pong) came


def test_hl_watchdog_quiet_while_pongs_arrive(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = FakeClock(step=1_000)
    monkeypatch.setattr(feeds, "now_ms", clock)
    monkeypatch.setattr(feeds.websockets, "connect", lambda *a, **k: FakeWS(on_empty="pong"))
    f = HlBookFeed("MU", "io:MU", lambda *a: None)
    stop = asyncio.Event()
    orig = f.handle

    def handle(msg: dict, recv: int) -> None:
        orig(msg, recv)
        if f.stats.frames >= 60:                                   # ~60+ s of fake time
            stop.set()

    f.handle = handle  # type: ignore[method-assign]
    asyncio.run(f._session(stop))                                  # returns normally: no FeedWatchdog
    assert f.stats.frames >= 60


def test_hl_watchdog_reconnects_through_run(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple] = []
    monkeypatch.setattr(feeds, "now_ms", FakeClock(step=1_000))
    monkeypatch.setattr(feeds.websockets, "connect", lambda *a, **k: FakeWS(on_empty="timeout"))

    async def fake_sleep(stop_: asyncio.Event, ms: int) -> None:
        stop_.set()

    monkeypatch.setattr(feeds, "sleep_or_stop", fake_sleep)
    f = HlBookFeed("MU", "io:MU", lambda *a: events.append(a))
    hl_apply_snapshot(f.book, {"time": 1, "levels": [[{"px": "100", "sz": "1"}], [{"px": "101", "sz": "1"}]]}, 1)
    asyncio.run(f.run(asyncio.Event()))
    assert [e[2] for e in events if e[2] != "connected"] == ["watchdog_reconnect"]
    assert f.stats.extra["watchdog_reconnects"] == 1 and f.stats.reconnects == 1 and not f.book.valid


# ============================================================================ P1: Arcus delta stall
def _ab(seq: int, ts_ms: int, bids: list | None = None) -> dict:
    return {"bids": bids or [["100", "1"]], "asks": [["101", "1"]], "lastSequenceId": seq, "timestamp": ts_ms * 1000}


def _live_arcus(t0: int) -> ArcusBookFeed:
    f = ArcusBookFeed("MU-USD", lambda *a: None)
    f.handle({"type": "subscribed", "channel": "l2OrderbookUpdates", "id": "MU-USD", "contents": _ab(10, t0)}, t0)
    f.handle({"type": "channel_data", "channel": "l2OrderbookUpdates", "id": "MU-USD",
              "contents": {"bids": [], "asks": [], "lastSequenceId": 11, "timestamp": (t0 + 10) * 1000}}, t0 + 20)
    assert f.book.ready and f.book.latency_ms == 10
    return f


def _hl_live(now: int) -> OrderBook:
    b = OrderBook("hyperliquid", "io:MU")
    hl_apply_snapshot(b, {"time": now, "levels": [[{"px": "100.1", "sz": "10"}], [{"px": "100.9", "sz": "10"}]]}, now)
    b.last_msg_ms = now
    return b


def test_arcus_delta_stall_goes_stale_then_rebuilds() -> None:
    t0 = 1_000_000
    f = _live_arcus(t0)
    sa, sb = _specs()
    stall_from = t0 + 1_000
    raised = None
    for i in range(0, 60):
        now = stall_from + i * 100                                   # heartbeats every 100 ms, seq racing ahead
        try:
            f.handle({"type": "channel_data", "channel": "l2Orderbook", "id": "MU-USD",
                      "contents": _ab(12 + i, now - 10)}, now)
        except BookIntegrityError as exc:
            raised = (i, now, exc)
            break
        assert f.book.last_msg_ms == now                              # connection alive (frames do arrive)
        lat = f.book.latency_ms
        assert lat is not None and lat >= now - (stall_from - 10)     # measured from the first 'behind' heartbeat
        if i == 6:                                                    # ~600 ms behind -> stale through evaluate
            o = evaluate(book_a=f.book, book_b=_hl_live(now), spec_a=sa, spec_b=sb, q_usd=D(100),
                         direction=Direction.BUY_A_SELL_B, mode=Mode.DUAL_TAKER, now_ms=now)
            assert o.status == "stale"
    assert raised is not None and raised[1] - stall_from >= 5_000 and "stalled" in str(raised[2])
    assert not f.book.valid and f.stats.extra["delta_stall_rebuild"] == 1


def test_arcus_healthy_book_with_trailing_deltas_never_rebuilds_or_goes_stale() -> None:
    t0 = 1_000_000
    f = _live_arcus(t0)
    sa, sb = _specs()
    seq = 11
    for i in range(1, 120):                                          # 12 s: every heartbeat is 1 seq ahead ...
        now = t0 + i * 100
        f.handle({"type": "channel_data", "channel": "l2Orderbook", "id": "MU-USD",
                  "contents": _ab(seq + 1, now - 10)}, now)
        seq += 1                                                     # ... and the delta lands 5 ms later
        f.handle({"type": "channel_data", "channel": "l2OrderbookUpdates", "id": "MU-USD",
                  "contents": {"bids": [], "asks": [], "lastSequenceId": seq, "timestamp": (now - 8) * 1000}}, now + 5)
        assert f.book.ready and f.book.latency_ms is not None and f.book.latency_ms < 50
    o = evaluate(book_a=f.book, book_b=_hl_live(now + 5), spec_a=sa, spec_b=sb, q_usd=D(100),
                 direction=Direction.BUY_A_SELL_B, mode=Mode.DUAL_TAKER, now_ms=now + 5)
    assert o.status not in ("stale", "not_ready")
    assert "delta_stall_rebuild" not in f.stats.extra


def test_arcus_behind_without_seq_advance_does_not_rebuild() -> None:
    t0 = 1_000_000
    f = _live_arcus(t0)
    for i in range(1, 80):                                            # same server seq for 8 s: no proof of a stall
        now = t0 + i * 100
        f.handle({"type": "channel_data", "channel": "l2Orderbook", "id": "MU-USD", "contents": _ab(12, now)}, now)
    assert f.book.valid and "delta_stall_rebuild" not in f.stats.extra


# ============================================================================ book edge cases
def test_duplicate_delta_keeps_provisional() -> None:
    b = OrderBook("arcus", "MU-USD")
    sync = ArcusSync(b, 100)
    assert sync.on_snapshot(_ab(10, 1), 1) and b.provisional and not b.ready
    sync.on_delta({"bids": [], "asks": [], "lastSequenceId": 10, "timestamp": 2000}, 2)     # duplicate / replay
    assert b.provisional and not b.ready                                                    # was cleared before
    sync.on_delta({"bids": [], "asks": [], "lastSequenceId": 9, "timestamp": 2000}, 3)      # older replay
    assert b.provisional
    sync.on_delta({"bids": [["100", "2"]], "asks": [], "lastSequenceId": 11, "timestamp": 3000}, 4)
    assert not b.provisional and b.ready and b.bids[D(100)] == D(2)


@pytest.mark.parametrize("lv", [{"p": "0", "sz": "1", "s": "1"}, {"p": "-100", "s": "1"}, {"p": "100", "s": "-1"},
                                {"p": "-1", "s": "0"}])
def test_hl_upsert_rejects_non_positive_price_or_negative_size(lv: dict) -> None:
    b = OrderBook("hyperliquid", "io:MU")
    hl_apply_snapshot(b, {"time": 1, "levels": [[{"px": "100", "sz": "1"}], [{"px": "101", "sz": "1"}]]}, 1)
    with pytest.raises(BookIntegrityError):
        hl_apply_diff(b, {"t": 2, "r": [[], []], "l": [[lv], []]}, 2)
    assert not b.valid and not b.bids and not b.asks


def test_hl_upsert_zero_size_still_removes() -> None:
    b = OrderBook("hyperliquid", "io:MU")
    hl_apply_snapshot(b, {"time": 1, "levels": [[{"px": "100", "sz": "1"}, {"px": "99", "sz": "2"}],
                                                [{"px": "101", "sz": "1"}]]}, 1)
    hl_apply_diff(b, {"t": 2, "r": [[], []], "l": [[{"p": "100", "s": "0"}], [{"p": "101.5", "s": "3"}]]}, 2)
    assert b.valid and b.best_bid() == D(99) and b.asks[D("101.5")] == D(3)


# ============================================================================ realism
def _realism_db(hedge_status_after_t0: str) -> sqlite3.Connection:
    """MU MAKER_HL_TAKER_ARCUS signal at t0 only; hedge = BUY on Arcus. At t0+k the opportunity row has
    ``hedge_status_after_t0`` while the 1 Hz Arcus top-of-book ask (a BBO, not a VWAP) sits at 100.50 (lower)."""
    db = sqlite3.connect(":memory:")
    db.executescript(SCHEMA)
    base = 1_000_000
    for i in range(7):
        ts = base + i * 1000
        ok = i == 0 or hedge_status_after_t0 == "ok"
        db.execute("INSERT INTO opportunities (ts_ms, symbol, q_usd, direction, mode, status, open_buy_px, "
                   "open_sell_px, net_resid_bps) VALUES (?,?,?,?,?,?,?,?,?)",
                   (ts, "MU", "100", "BUY_ARCUS_SELL_HL", "MAKER_HL_TAKER_ARCUS", "ok" if ok else hedge_status_after_t0,
                    "100.60" if ok else None, "101.0" if ok else None, "3.0" if i == 0 else "-1.0"))
        for venue, bid, ask in (("hyperliquid", "100.0", "101.0"), ("arcus", "100.4", "100.50")):
            db.execute("INSERT INTO book_health (ts_ms, symbol, venue, ready, valid, best_bid, best_ask) VALUES "
                       "(?,?,?,?,?,?,?)", (ts, "MU", venue, 1, 1, bid, ask))
    return db


def test_adverse_selection_never_mixes_bbo_into_vwap() -> None:
    db = _realism_db("insufficient_depth")
    (row,) = maker_realism(db, 1_000_000, 1_000_000)["rows"]
    for k in ("+1s", "+3s", "+5s"):
        a = row["adverse_selection"]["unfiltered_triggers"][k]
        # old code: p1 = Arcus best ask 100.50 (BBO) vs p0 = VWAP 100.60 -> a fake -9.9 bps "favourable" move
        assert a["n"] == 0 and a["mean_adverse_bps"] is None
        assert a["missing_hedge_vwap"] == 1 and a["missing"] == 1 and a["top_of_book_fallback"] == 0


def test_adverse_selection_uses_vwap_when_present() -> None:
    db = _realism_db("ok")
    (row,) = maker_realism(db, 1_000_000, 1_000_000)["rows"]
    a = row["adverse_selection"]["unfiltered_triggers"]["+1s"]
    assert a["n"] == 1 and a["mean_adverse_bps"] == 0 and a["missing_hedge_vwap"] == 0


def test_has_trades_table_honours_meta_record_trades() -> None:
    db = sqlite3.connect(":memory:")
    assert not has_trades_table(db)                                           # no table at all (pre-PR #1.6)
    db.executescript(SCHEMA)
    assert not has_trades_table(db)                                           # table exists, no flag, empty
    db.execute("INSERT INTO trades VALUES ('hyperliquid','MU',1,1,'100','1','BUY','B','1')")
    assert has_trades_table(db)                                               # no flag but rows -> recorded
    db.execute("INSERT INTO meta VALUES ('record_trades', '0')")
    assert not has_trades_table(db)                                           # flag says not recorded
    db.execute("DELETE FROM trades")
    db.execute("INSERT OR REPLACE INTO meta VALUES ('record_trades', '1')")
    assert has_trades_table(db)                                               # recorded, quiet market (0 trades)
    r = maker_realism(db, 0, 1)
    assert r["trades_table"] is True


def test_store_close_is_safe_for_memory_db() -> None:
    st = Store(":memory:")
    assert st.journal_mode() == "memory"
    st.close()
