"""READ-ONLY WebSocket market-data feeds (public channels only; nothing is authenticated or signed)."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import zlib
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable

import websockets

from phase0_probe.book import (ArcusSync, BookIntegrityError, OrderBook, SequenceGap, arcus_heartbeat, hl_apply_diff,
                               hl_apply_snapshot, hl_check_against_snapshot)
from phase0_probe.dec import D_opt, loads, now_ms
from phase0_probe.venues import ARCUS_WS, HL_WS

log = logging.getLogger("phase0.feeds")
EventSink = Callable[[str, str | None, str, str], None]          # (venue, symbol, kind, detail)
N_LEVELS = 20            # levels compared by the l2Orderbook checksum (and HL l2 depth)
ARCUS_DEPTH = 100        # l2OrderbookUpdates depth kept locally (deeper than the checksum to avoid edge churn)


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
    LIVE, any ``lastSequenceId`` gap or checksum mismatch -> log + reconnect + rebuild."""

    def __init__(self, market: str, sink: EventSink, url: str = ARCUS_WS) -> None:
        self.market, self.sink, self.url = market, sink, url
        self.book = OrderBook("arcus", market)
        self.sync = ArcusSync(self.book, ARCUS_DEPTH)
        self.stats = FeedStats()

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self._session(stop)
            except (SequenceGap, BookIntegrityError) as exc:
                self.stats.gaps += isinstance(exc, SequenceGap)
                self.stats.integrity_errors += isinstance(exc, BookIntegrityError)
                self.sink("arcus", self.market, "gap_reconnect" if isinstance(exc, SequenceGap) else "integrity_reconnect",
                          str(exc))
            except (OSError, websockets.WebSocketException, asyncio.TimeoutError) as exc:
                self.sink("arcus", self.market, "conn_error", f"{type(exc).__name__}: {exc}")
            self.book.invalidate()
            self.sync.buffer.clear()
            if stop.is_set():
                break
            self.stats.reconnects += 1
            await asyncio.sleep(1)

    async def _session(self, stop: asyncio.Event) -> None:
        async with websockets.connect(self.url, max_size=2 ** 24, ping_interval=20, open_timeout=15) as ws:
            for ch in ("l2OrderbookUpdates", "l2Orderbook"):
                await ws.send(json.dumps({"type": "subscribe", "channel": ch, "id": self.market,
                                          "nLevels": ARCUS_DEPTH}))
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
            if res == "confirmed":
                self.stats.hb_confirmed += 1
            elif res == "mismatch":
                self.stats.hb_mismatch += 1
                self.book.invalidate()
                raise BookIntegrityError(f"l2Orderbook checksum mismatch at seq {c.get('lastSequenceId')}")

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

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                async with websockets.connect(self.url, max_size=2 ** 24, ping_interval=20, open_timeout=15) as ws:
                    await ws.send(json.dumps({"type": "subscribe", "channel": "markets"}))
                    while not stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=1)
                        except asyncio.TimeoutError:
                            continue
                        self.handle(loads(raw), now_ms())
            except (OSError, websockets.WebSocketException, asyncio.TimeoutError) as exc:
                self.sink("arcus", None, "markets_conn_error", f"{type(exc).__name__}: {exc}")
                self.stats.reconnects += 1
                await asyncio.sleep(1)

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
    5 s here so a pong proves connection health even when the book is idle)."""
    ping_every_ms = 5_000

    def __init__(self, symbol: str, coin: str, sink: EventSink, url: str = HL_WS) -> None:
        self.symbol, self.coin, self.sink, self.url = symbol, coin, sink, url
        self.book = OrderBook("hyperliquid", coin)
        self.funding = FundingState()
        self.stats = FeedStats()

    async def run(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self._session(stop)
            except BookIntegrityError as exc:
                self.stats.integrity_errors += 1
                self.sink("hyperliquid", self.symbol, "integrity_reconnect", str(exc))
            except (OSError, websockets.WebSocketException, asyncio.TimeoutError) as exc:
                self.sink("hyperliquid", self.symbol, "conn_error", f"{type(exc).__name__}: {exc}")
            self.book.invalidate()
            if stop.is_set():
                break
            self.stats.reconnects += 1
            await asyncio.sleep(1)

    async def _session(self, stop: asyncio.Event) -> None:
        async with websockets.connect(self.url, max_size=2 ** 24, ping_interval=None, open_timeout=15) as ws:
            for sub in ({"type": "l2", "c": self.coin}, {"type": "l2Book", "coin": self.coin},
                        {"type": "activeAssetCtx", "coin": self.coin}):
                await ws.send(json.dumps({"method": "subscribe", "subscription": sub}))
            self.sink("hyperliquid", self.symbol, "connected", self.url)
            last_ping = now_ms()
            while not stop.is_set():
                if now_ms() - last_ping >= self.ping_every_ms:
                    await ws.send(json.dumps({"method": "ping"}))
                    last_ping = now_ms()
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1)
                except asyncio.TimeoutError:
                    continue
                self.handle(loads(raw), now_ms())

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
        elif ch == "activeAssetCtx" and isinstance(data, dict) and data.get("coin") == self.coin:
            ctx = data.get("ctx") or {}
            self.funding.current_hourly = D_opt(None if ctx.get("funding") is None else str(ctx["funding"]))
            self.funding.updated_ms = recv
