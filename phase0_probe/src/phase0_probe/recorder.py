"""Per-second sampler: evaluates every (symbol, Q, direction, mode) and writes SQLite snapshots."""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from decimal import Decimal

import aiohttp

from phase0_probe.dec import now_ms
from phase0_probe.discovery import parse_predicted
from phase0_probe.feeds import ArcusBookFeed, ArcusMarketsFeed, HlBookFeed
from phase0_probe.model import Direction, Mode, RollingMedian, VenueSpec, evaluate, mid_basis_bps
from phase0_probe.store import Store, s
from phase0_probe.venues import hl_info

log = logging.getLogger("phase0.recorder")


@dataclass
class Pair:
    symbol: str
    arcus: ArcusBookFeed
    hl: HlBookFeed
    spec_a: VenueSpec
    spec_b: VenueSpec


class Recorder:
    def __init__(self, store: Store, pairs: list[Pair], markets: ArcusMarketsFeed, *, qs: list[Decimal],
                 max_latency_ms: int = 500, conn_timeout_ms: int = 5000, buffer_bps: Decimal = Decimal(2),
                 resid_window_s: int = 300, resid_min_samples: int = 30) -> None:
        self.store, self.pairs, self.markets = store, pairs, markets
        self.qs, self.max_latency_ms, self.conn_timeout_ms, self.buffer_bps = qs, max_latency_ms, conn_timeout_ms, \
            buffer_bps
        self.resid_window_ms, self.resid_min_samples = resid_window_s * 1000, resid_min_samples
        self.medians: dict[str, RollingMedian] = {}
        self.hl_predicted: dict[str, Decimal] = {}
        self.ticks = 0
        self.commit_errors = 0                                # Sprint 2: seconds whose SQLite write/commit failed
        self._db_errors: list[tuple[int, str]] = []           # error events not yet written (DB was locked)

    def sink(self, venue: str, symbol: str | None, kind: str, detail: str) -> None:
        lvl = logging.INFO if kind in ("connected", "snapshot", "baseline") else logging.WARNING
        log.log(lvl, "%s %s %s %s", venue, symbol, kind, detail)
        self.store.event(now_ms(), venue, symbol, kind, detail)

    def sample(self, ts: int) -> None:
        rows, health = [], []
        for p in self.pairs:
            rm = self.medians.setdefault(p.symbol, RollingMedian(self.resid_window_ms, self.resid_min_samples))
            med = rm.median(ts)                                # previous window only (no look-ahead)
            for q in self.qs:
                for d in Direction:
                    for m in Mode:
                        rows.append(evaluate(book_a=p.arcus.book, book_b=p.hl.book, spec_a=p.spec_a, spec_b=p.spec_b,
                                             q_usd=q, direction=d, mode=m, now_ms=ts,
                                             max_latency_ms=self.max_latency_ms, conn_timeout_ms=self.conn_timeout_ms,
                                             buffer_bps=self.buffer_bps, basis_median_bps=med))
            fresh = any(r.symbol == p.spec_a.symbol and r.status not in ("not_ready", "stale") for r in rows[-1:])
            basis = mid_basis_bps(p.arcus.book, p.hl.book)
            if basis is not None and fresh:
                rm.push(ts, basis)
            for venue, b in (("arcus", p.arcus.book), ("hyperliquid", p.hl.book)):
                health.append((ts, p.symbol, venue, int(b.ready), int(b.valid), b.latency_ms, b.idle_ms(ts),
                               b.silence_ms(ts), b.age_ms(ts), s(b.best_bid()), s(b.best_ask()), len(b.bids),
                               len(b.asks), b.last_seq))
        try:
            if self._db_errors:                               # events of earlier failed seconds, now that we can write
                for ev_ts, detail in self._db_errors:
                    self.store.event(ev_ts, "recorder", None, "db_commit_error", detail)
                self._db_errors.clear()                       # in the open transaction from here on
            self.store.opportunities(ts, rows)
            self.store.book_health(health)
            if self.ticks % 5 == 0:
                fr = []
                for p in self.pairs:
                    fa = self.markets.funding.get(p.spec_a.symbol + "-USD")
                    if fa is not None:
                        fr.append((ts, p.symbol, "arcus", s(fa.current_hourly), s(fa.predicted_hourly)))
                    fr.append((ts, p.symbol, "hyperliquid", s(p.hl.funding.current_hourly),
                               s(self.hl_predicted.get(p.hl.coin))))
                self.store.funding(fr)
            self.store.commit()
        except sqlite3.OperationalError as exc:
            # Sprint 2 (P1): a locked / busy DB must never kill the sampler. Skip this second; rows already inserted
            # stay in the open transaction and are committed with the next successful second (no rollback, so
            # buffered trades are not lost). The ``db_commit_error`` event is queued and written with the next second
            # that can write (writing it now would hit the same lock).
            self.commit_errors += 1
            log.warning("sqlite write/commit failed at %s, second skipped: %s", ts, exc)
            if len(self._db_errors) < 1000:
                self._db_errors.append((now_ms(), f"ts={ts} {type(exc).__name__}: {exc}"))
        self.ticks += 1

    async def poll_predicted(self, stop: asyncio.Event, every_s: int = 60) -> None:
        async with aiohttp.ClientSession() as sess:
            while not stop.is_set():
                try:
                    self.hl_predicted = parse_predicted(await hl_info(sess, {"type": "predictedFundings"}))
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
                    self.sink("hyperliquid", None, "predicted_fundings_error", f"{type(exc).__name__}: {exc}")
                try:
                    await asyncio.wait_for(stop.wait(), timeout=every_s)
                except asyncio.TimeoutError:
                    pass

    async def sampler(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            ts = now_ms()
            nxt = (ts // 1000 + 1) * 1000                        # align to whole seconds
            try:
                await asyncio.wait_for(stop.wait(), timeout=(nxt - ts) / 1000)
                break
            except asyncio.TimeoutError:
                pass
            self.sample(nxt)
