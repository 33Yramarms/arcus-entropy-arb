"""READ-ONLY WebSocket market-data feeds (public channels only; nothing is authenticated or signed)."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
import zlib
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

import websockets

from phase0_probe.book import (ArcusSync, BookIntegrityError, OrderBook, SequenceGap, arcus_heartbeat, hl_apply_diff,
                               hl_apply_snapshot, hl_check_against_snapshot)
from phase0_probe.dec import D_opt, loads, now_ms
from phase0_probe.trades import Trade, parse_arcus_trades, parse_hl_trades
from phase0_probe.venues import ARCUS_WS, HL_WS

log = logging.getLogger("phase0.feeds")
EventSink = Callable[[str, str | None, str, str], None]          # (venue, symbol, kind, detail)
TradeSink = Callable[[list[Trade]], None]                         # PR #1.6 --record-trades (None = not subscribed)
N_LEVELS = 20            # levels compared by the l2Orderbook checksum (and HL l2 depth)
ARCUS_DEPTH = 100        # l2OrderbookUpdates depth kept locally (deeper than the checksum to avoid edge churn)

# Sprint 2 (P1): reconnect policy shared by every feed (all integer milliseconds; never money).
BACKOFF_BASE_MS = 1_000          # first retry after ~1 s
BACKOFF_CAP_MS = 30_000          # never wait longer than 30 s
BACKOFF_STABLE_MS = 60_000       # a session that stayed up >= 60 s resets the backoff to the base
HL_WATCHDOG_MS = 15_000          # HL: no frame at all (not even a pong to our 5 s ping) for 15 s -> reconnect
ARCUS_STALL_MS = 5_000           # Arcus: l2Orderbook keeps showing a newer seq while no delta lands for 5 s -> rebuild
# Malformed / unexpected payloads (bad JSON, missing keys, bad numbers, bad compressed frame): log, invalidate the
# book and reconnect with backoff instead of letting the task die. (InvalidOperation / IndexError added on purpose:
# ``Decimal("x")`` and short level arrays raise those, not ValueError.)
PAYLOAD_ERRORS: tuple[type[BaseException], ...] = (ValueError, KeyError, TypeError, IndexError, InvalidOperation,
                                                   zlib.error)
CONN_ERRORS: tuple[type[BaseException], ...] = (OSError, websockets.WebSocketException, asyncio.TimeoutError)


class FeedWatchdog(Exception):
    """Raised inside a session when the connection has been silent for too long (forces a reconnect)."""


class Backoff:
    """Exponential reconnect backoff with random jitter, in integer ms.

    Attempt n (0-based) waits ``raw = min(cap, base * 2**n)`` plus jitter ``U[0, raw // 5]``; a delay that would
    exceed the cap is instead drawn from ``[cap - cap // 10, cap]`` so many feeds hitting the cap still spread out.
    Bounds: ``base <= delay <= cap`` always (1 s .. 30 s). :meth:`connected` marks a successful (re)connect; when the
    connection then stayed up for at least ``stable_ms`` before dropping, the next delay starts again from the base."""

    def __init__(self, base_ms: int = BACKOFF_BASE_MS, cap_ms: int = BACKOFF_CAP_MS, stable_ms: int = BACKOFF_STABLE_MS,
                 rng: random.Random | None = None) -> None:
        self.base_ms, self.cap_ms, self.stable_ms = base_ms, cap_ms, stable_ms
        self.rng = rng if rng is not None else random.Random()
        self.attempt = 0
        self.connected_ms: int | None = None

    def connected(self, now: int) -> None:
        self.connected_ms = now

    def next_delay_ms(self, now: int) -> int:
        if self.connected_ms is not None and now - self.connected_ms >= self.stable_ms:
            self.attempt = 0                                  # the last session was stable: start over
        self.connected_ms = None
        raw = min(self.cap_ms, self.base_ms << min(self.attempt, 30))
        delay = raw + self.rng.randint(0, raw // 5)
        if delay > self.cap_ms:
            delay = self.cap_ms - self.rng.randint(0, self.cap_ms // 10)
        self.attempt += 1
        return delay


async def sleep_or_stop(stop: asyncio.Event, delay_ms: int) -> None:
    """Wait ``delay_ms`` or until ``stop`` is set, whichever comes first."""
    try:
        await asyncio.wait_for(stop.wait(), timeout=delay_ms / 1000)
    except asyncio.TimeoutError:
        pass


@dataclass
class FundingState:
    current_hourly: Decimal | None = None
    predicted_hourly: Decimal | None = None
    updated_ms: int | None = None


@dataclass
class FeedStats:
    frames: int = 0
    reconnects: int = 0
    gaps: int = 0
    integrity_errors: int = 0
    hb_confirmed: int = 0
    hb_mismatch: int = 0
    checks_ok: int = 0
    checks_bad: int = 0
    extra: dict[str, int] = field(default_factory=dict)


class ArcusBookFeed:
    """One connection per market: ``l2OrderbookUpdates`` (book + contiguous lastSequenceId) and ``l2Orderbook``
    (~200 ms full snapshot: baseline, liveness proof + checksum). Baseline per the documented resync procedure; once
    LIVE, any ``lastSequenceId`` gap or checksum mismatch -> log + reconnect + rebuild.
    PR #1.6: with a ``trade_sink`` the public ``trades`` channel of the same market is subscribed on the SAME socket
    (no extra connection)."""

    def __init__(self, market: str, sink: EventSink, url: str = ARCUS_WS, trade_sink: TradeSink | None = None) -> None:
        self.market, self.sink, self.url, self.trade_sink = market, sink, url, trade_sink
        self.symbol = market.split("-", 1)[0]
        self.book = OrderBook("arcus", market)
        self.sync = ArcusSync(self.book, ARCUS_DEPTH)
        self.stats = FeedStats()
        self.backoff = Backoff()
        # Sprint 2 delta-stall detector: set while l2Orderbook heartbeats are AHEAD of the delta-built book
        self._behind_book_seq: int | None = None     # our book's last_seq when the current "behind" streak started
        self._behind_hb_seq: int | None = None       # heartbeat seq at the start of the streak
        self._behind_exch_ms: int | None = None      # exchange time of the first heartbeat proving the book is behind
        self._behind_recv_ms: int | None = None      # local time of that heartbeat

    def invalidate(self) -> None:
        self.book.invalidate()
        self.sync.buffer.clear()
        self._reset_behind()

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self._session(stop)
            except (SequenceGap, BookIntegrityError) as exc:
                self.stats.gaps += isinstance(exc, SequenceGap)
                self.stats.integrity_errors += isinstance(exc, BookIntegrityError)
                self.sink("arcus", self.market, "gap_reconnect" if isinstance(exc, SequenceGap) else "integrity_reconnect",
                          str(exc))
            except CONN_ERRORS as exc:
                self.sink("arcus", self.market, "conn_error", f"{type(exc).__name__}: {exc}")
            except PAYLOAD_ERRORS as exc:
                self.stats.extra["payload_errors"] = self.stats.extra.get("payload_errors", 0) + 1
                log.warning("arcus %s payload error: %r", self.market, exc)
                self.sink("arcus", self.market, "payload_error", f"{type(exc).__name__}: {exc}")
            self.invalidate()
            if stop.is_set():
                break
            self.stats.reconnects += 1
            await sleep_or_stop(stop, self.backoff.next_delay_ms(now_ms()))

    async def _session(self, stop: asyncio.Event) -> None:
        async with websockets.connect(self.url, max_size=2 ** 24, ping_interval=20, open_timeout=15) as ws:
            self.backoff.connected(now_ms())
            for ch in ("l2OrderbookUpdates", "l2Orderbook"):
                await ws.send(json.dumps({"type": "subscribe", "channel": ch, "id": self.market,
                                          "nLevels": ARCUS_DEPTH}))
            if self.trade_sink is not None:
                await ws.send(json.dumps({"type": "subscribe", "channel": "trades", "id": self.market}))
            self.sink("arcus", self.market, "connected", self.url)
            while not stop.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1)
                except asyncio.TimeoutError:
                    continue
                self.handle(loads(raw), now_ms())

    def handle(self, msg: dict[str, Any], recv: int) -> None:
        self.stats.frames += 1
        self.book.last_msg_ms = recv                     # connection health: any frame counts
        typ, ch, c = msg.get("type"), msg.get("channel"), msg.get("contents")
        if typ == "error":
            self.sink("arcus", self.market, "server_error", json.dumps(msg, default=str)[:300])
            return
        if ch == "trades":
            if self.trade_sink is not None:
                tr = parse_arcus_trades(msg, self.symbol, self.market, recv)
                if tr:
                    self.stats.extra["trades"] = self.stats.extra.get("trades", 0) + len(tr)
                    self.trade_sink(tr)
            return
        if msg.get("id") not in (None, self.market) or not isinstance(c, dict):
            return
        if ch == "l2OrderbookUpdates":
            if typ == "subscribed":
                self._baseline(c, recv, "updates-snapshot")
            elif typ == "channel_data":
                before = self.sync.baseline_gaps
                self.sync.on_delta(c, recv)
                if self.sync.baseline_gaps != before:
                    self.stats.extra["baseline_gap_resync"] = self.sync.baseline_gaps
                    self.sink("arcus", self.market, "baseline_gap_resync",
                              f"first delta {c.get('lastSequenceId')} after snapshot skipped ids; rebuilding")
        elif ch == "l2Orderbook" and typ in ("subscribed", "channel_data"):
            if not self.book.valid:
                self._baseline(c, recv, "l2Orderbook")
                return
            res = arcus_heartbeat(self.book, c, recv, N_LEVELS)
            if res == "behind":
                self._on_behind(c, recv)
                return
            self._reset_behind()
            if res == "confirmed":
                self.stats.hb_confirmed += 1
            elif res == "mismatch":
                self.stats.hb_mismatch += 1
                self.book.invalidate()
                raise BookIntegrityError(f"l2Orderbook checksum mismatch at seq {c.get('lastSequenceId')}")

    def _reset_behind(self) -> None:
        self._behind_book_seq = self._behind_hb_seq = self._behind_exch_ms = self._behind_recv_ms = None

    def _on_behind(self, c: dict[str, Any], recv: int) -> None:
        """Sprint 2 (P1) delta-stall guard. ``arcus_heartbeat`` measured this frame's network latency, but a heartbeat
        that is AHEAD of our book proves nothing about the book: the staleness clock must not be refreshed by it.
        From the first heartbeat of a "behind" streak (exchange time T0) the book is known to lag the venue by at least
        ``now - T0``, so ``latency_ms`` is pinned to ``recv + offset - T0`` (never lower than the measured network
        latency). Any applied delta (book ``last_seq`` moves) ends the streak, so a healthy book whose deltas merely
        trail the snapshot channel by a few ms keeps its normal latency; a stalled delta stream crosses
        ``--max-latency-ms`` and the existing ``model.evaluate`` gate marks it ``stale``. After ``ARCUS_STALL_MS`` of
        uninterrupted "behind" while the heartbeat seq keeps advancing, the book is invalidated and rebuilt
        (BookIntegrityError -> reconnect + fresh baseline)."""
        seq, ts = c.get("lastSequenceId"), c.get("timestamp")
        if not self.book.valid or not isinstance(seq, int) or isinstance(seq, bool):
            return
        if self._behind_recv_ms is None or self._behind_book_seq != self.book.last_seq:
            self._behind_book_seq, self._behind_hb_seq = self.book.last_seq, seq
            self._behind_exch_ms = ts // 1000 if isinstance(ts, int) else None
            self._behind_recv_ms = recv
        if self._behind_exch_ms is not None:
            pinned = recv + self.book.clock_offset_ms - self._behind_exch_ms
            if self.book.latency_ms is None or pinned > self.book.latency_ms:
                self.book.latency_ms = pinned
        assert self._behind_hb_seq is not None
        if recv - self._behind_recv_ms >= ARCUS_STALL_MS and seq > self._behind_hb_seq:
            self.stats.extra["delta_stall_rebuild"] = self.stats.extra.get("delta_stall_rebuild", 0) + 1
            book_seq, behind_ms = self.book.last_seq, recv - self._behind_recv_ms
            self.invalidate()
            raise BookIntegrityError(f"delta stream stalled: book seq {book_seq}, l2Orderbook seq {seq} "
                                     f"(behind for {behind_ms} ms)")

    def _baseline(self, c: dict[str, Any], recv: int, source: str) -> None:
        if self.sync.on_snapshot(c, recv):
            self.sink("arcus", self.market, "baseline", f"{source} seq={self.book.last_seq}")
        else:
            self.stats.extra["baseline_retry"] = self.stats.extra.get("baseline_retry", 0) + 1


class ArcusMarketsFeed:
    """Global ``markets`` channel: per-market ``fundingRate`` (current hourly) and ``nextFundingRate`` (forecast)."""

    def __init__(self, markets: list[str], sink: EventSink, url: str = ARCUS_WS) -> None:
        self.url, self.sink = url, sink
        self.funding: dict[str, FundingState] = {m: FundingState() for m in markets}
        self.stats = FeedStats()
        self.backoff = Backoff()

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                async with websockets.connect(self.url, max_size=2 ** 24, ping_interval=20, open_timeout=15) as ws:
                    self.backoff.connected(now_ms())
                    await ws.send(json.dumps({"type": "subscribe", "channel": "markets"}))
                    while not stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=1)
                        except asyncio.TimeoutError:
                            continue
                        self.handle(loads(raw), now_ms())
            except CONN_ERRORS as exc:
                self.sink("arcus", None, "markets_conn_error", f"{type(exc).__name__}: {exc}")
            except PAYLOAD_ERRORS as exc:
                self.stats.extra["payload_errors"] = self.stats.extra.get("payload_errors", 0) + 1
                log.warning("arcus markets payload error: %r", exc)
                self.sink("arcus", None, "markets_payload_error", f"{type(exc).__name__}: {exc}")
            if stop.is_set():
                break
            self.stats.reconnects += 1
            await sleep_or_stop(stop, self.backoff.next_delay_ms(now_ms()))

    def handle(self, msg: dict[str, Any], recv: int) -> None:
        if msg.get("channel") != "markets" or not isinstance(msg.get("contents"), dict):
            return
        self.stats.frames += 1
        for m in (msg["contents"].get("markets") or {}).values():
            name = m.get("marketDisplayName")
            if name in self.funding:
                f = self.funding[name]
                f.current_hourly = D_opt(None if m.get("fundingRate") is None else str(m["fundingRate"]))
                f.predicted_hourly = D_opt(None if m.get("nextFundingRate") is None else str(m["nextFundingRate"]))
                f.updated_ms = recv


def hl_decode(payload: str) -> Any:
    """base64 -> raw DEFLATE (RFC 1951, wbits=-15) -> UTF-8 JSON (subscriptions.md, ``fastAssetCtxs``)."""
    return loads(zlib.decompress(base64.b64decode(payload), wbits=-15).decode("utf-8"))


class HlBookFeed:
    """One connection per coin: ``l2`` (snapshot + diffs; documented as item 23 of websocket/subscriptions.md),
    ``l2Book`` (checksum when ``time`` matches; pushed only every ~12 s with the default ``fast: false`` — see README)
    and ``activeAssetCtx`` (``funding``). Client ``{"method":"ping"}`` every ``ping_every_ms`` (docs require < 60 s;
    5 s here so a pong proves connection health even when the book is idle).
    PR #1.6: with a ``trade_sink`` the ``trades`` subscription for the coin is multiplexed on the SAME connection, so
    ``--record-trades`` adds no WebSocket connection (HL limit: 10 per IP)."""
    ping_every_ms = 5_000
    watchdog_ms = HL_WATCHDOG_MS        # Sprint 2: no frame (pong included) for this long -> drop + reconnect

    def __init__(self, symbol: str, coin: str, sink: EventSink, url: str = HL_WS,
                 trade_sink: TradeSink | None = None) -> None:
        self.symbol, self.coin, self.sink, self.url, self.trade_sink = symbol, coin, sink, url, trade_sink
        self.book = OrderBook("hyperliquid", coin)
        self.funding = FundingState()
        self.stats = FeedStats()
        self.backoff = Backoff()

    def invalidate(self) -> None:
        self.book.invalidate()

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self._session(stop)
            except BookIntegrityError as exc:
                self.stats.integrity_errors += 1
                self.sink("hyperliquid", self.symbol, "integrity_reconnect", str(exc))
            except FeedWatchdog as exc:
                self.stats.extra["watchdog_reconnects"] = self.stats.extra.get("watchdog_reconnects", 0) + 1
                self.sink("hyperliquid", self.symbol, "watchdog_reconnect", str(exc))
            except CONN_ERRORS as exc:
                self.sink("hyperliquid", self.symbol, "conn_error", f"{type(exc).__name__}: {exc}")
            except PAYLOAD_ERRORS as exc:
                self.stats.extra["payload_errors"] = self.stats.extra.get("payload_errors", 0) + 1
                log.warning("hyperliquid %s payload error: %r", self.symbol, exc)
                self.sink("hyperliquid", self.symbol, "payload_error", f"{type(exc).__name__}: {exc}")
            self.invalidate()
            if stop.is_set():
                break
            self.stats.reconnects += 1
            await sleep_or_stop(stop, self.backoff.next_delay_ms(now_ms()))

    async def _session(self, stop: asyncio.Event) -> None:
        async with websockets.connect(self.url, max_size=2 ** 24, ping_interval=None, open_timeout=15) as ws:
            self.backoff.connected(now_ms())
            subs = [{"type": "l2", "c": self.coin}, {"type": "l2Book", "coin": self.coin},
                    {"type": "activeAssetCtx", "coin": self.coin}]
            if self.trade_sink is not None:
                subs.append({"type": "trades", "coin": self.coin})
            for sub in subs:
                await ws.send(json.dumps({"method": "subscribe", "subscription": sub}))
            self.sink("hyperliquid", self.symbol, "connected", self.url)
            last_ping = last_rx = now_ms()
            while not stop.is_set():
                if now_ms() - last_rx >= self.watchdog_ms:
                    raise FeedWatchdog(f"no frame for {now_ms() - last_rx} ms (watchdog {self.watchdog_ms} ms)")
                if now_ms() - last_ping >= self.ping_every_ms:
                    await ws.send(json.dumps({"method": "ping"}))
                    last_ping = now_ms()
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1)
                except asyncio.TimeoutError:
                    continue
                last_rx = now_ms()
                self.handle(loads(raw), last_rx)

    def handle(self, msg: dict[str, Any], recv: int) -> None:
        self.stats.frames += 1
        self.book.last_msg_ms = recv                     # connection health: any frame (pong, ctx, ...) counts
        ch, data = msg.get("channel"), msg.get("data")
        if ch == "error":
            self.sink("hyperliquid", self.symbol, "server_error", json.dumps(msg, default=str)[:300])
        elif ch == "l2" and isinstance(data, dict):
            if "s" in data:
                hl_apply_snapshot(self.book, data["s"], recv)
                self.sink("hyperliquid", self.symbol, "snapshot", f"time={self.book.exchange_ts_ms}")
            elif "u" in data:
                hl_apply_diff(self.book, data["u"], recv)
            elif isinstance(data.get("c"), str):
                hl_apply_diff(self.book, hl_decode(data["c"]), recv)
        elif ch == "l2Book" and isinstance(data, dict) and data.get("coin") == self.coin:
            if self.book.valid:
                self.book.note_exchange_ts(data.get("time") if isinstance(data.get("time"), int) else None, recv)
            ok = hl_check_against_snapshot(self.book, data)
            if ok is True:
                self.stats.checks_ok += 1
            elif ok is False:
                self.stats.checks_bad += 1
                raise BookIntegrityError(f"l2 diff book != l2Book snapshot at time {data.get('time')}")
        elif ch == "trades" and isinstance(data, list):
            if self.trade_sink is not None:
                tr = parse_hl_trades(msg, self.symbol, self.coin, recv)
                if tr:
                    self.stats.extra["trades"] = self.stats.extra.get("trades", 0) + len(tr)
                    self.trade_sink(tr)
        elif ch == "activeAssetCtx" and isinstance(data, dict) and data.get("coin") == self.coin:
            ctx = data.get("ctx") or {}
            self.funding.current_hourly = D_opt(None if ctx.get("funding") is None else str(ctx["funding"]))
            self.funding.updated_ms = recv
