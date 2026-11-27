"""L2 order books (Decimal) for both venues.

* Arcus ``l2OrderbookUpdates`` (docs.arcus.xyz/api-reference/channels.md#l2orderbookupdates): the ``subscribed`` frame is a
  snapshot, then deltas; size ``"0"`` removes a level; ``lastSequenceId`` is contiguous (+1 per delta, including the
  first delta after the snapshot) — docs.arcus.xyz/api-reference/websocket.md#order-book-sequence-contiguity. Any gap
  raises ``SequenceGap`` and the caller reconnects.
* Hyperliquid ``l2`` (hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions.md, item 23):
  a ``WsBook`` snapshot under ``s`` then ``WsL2Diff`` under ``u`` (or compressed under ``c``): remove the levels at the
  indexes in ``r`` (positions in the PREVIOUS book) first, then add/replace levels in ``l`` by price. No sequence
  number exists, so integrity is cross-checked against ``l2Book`` snapshots when their ``time`` matches.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable

from phase0_probe.dec import D, TWO, ZERO

Level = tuple[Decimal, Decimal]          # (price, size)


class SequenceGap(Exception):
    def __init__(self, expected: int, got: int) -> None:
        super().__init__(f"lastSequenceId gap: expected {expected}, got {got}")
        self.expected, self.got = expected, got


class BookIntegrityError(Exception):
    pass


@dataclass
class OrderBook:
    venue: str
    symbol: str
    bids: dict[Decimal, Decimal] = field(default_factory=dict)
    asks: dict[Decimal, Decimal] = field(default_factory=dict)
    last_seq: int | None = None
    exchange_ts_ms: int | None = None      # exchange timestamp of the last applied frame
    confirmed_ms: int | None = None        # local time at which the current state was last proven current
    valid: bool = False                    # False until a snapshot is applied / after a detected gap
    provisional: bool = False              # Arcus: baselined from a snapshot, not yet proven by a contiguous delta
    # --- latency / idleness diagnostics (PR #1.5): kept separate on purpose ---
    last_msg_ms: int | None = None         # local receive time of the last frame on this book's connection (any)
    last_change_ms: int | None = None      # local receive time of the last frame that changed the book
    latency_ms: int | None = None          # (local recv + clock offset) - exchange timestamp, latest timestamped frame
    clock_offset_ms: int = 0               # venue server clock - local clock (Arcus: GET /v1/time); added to recv

    # ------------------------------------------------------------------ views
    def sorted_bids(self, n: int | None = None) -> list[Level]:
        lv = sorted(self.bids.items(), key=lambda kv: kv[0], reverse=True)
        return lv if n is None else lv[:n]

    def sorted_asks(self, n: int | None = None) -> list[Level]:
        lv = sorted(self.asks.items(), key=lambda kv: kv[0])
        return lv if n is None else lv[:n]

    def best_bid(self) -> Decimal | None:
        return max(self.bids) if self.bids else None

    def best_ask(self) -> Decimal | None:
        return min(self.asks) if self.asks else None

    def mid(self) -> Decimal | None:
        b, a = self.best_bid(), self.best_ask()
        if b is None or a is None or b >= a:
            return None
        return (b + a) / TWO

    def age_ms(self, now_ms: int) -> int | None:
        """Time since the local book was last PROVEN current (phase0 'age'; diagnostic only since PR #1.5)."""
        return None if self.confirmed_ms is None else now_ms - self.confirmed_ms

    @property
    def ready(self) -> bool:
        """False (= NOT_READY) while no snapshot is applied, after a gap, or during an Arcus resync / provisional
        baseline. Arbitrage evaluation is skipped for NOT_READY books."""
        return self.valid and not self.provisional

    def idle_ms(self, now_ms: int) -> int | None:
        """``book_idle_ms``: how long the book content has not changed (a quiet book is NOT stale by itself)."""
        return None if self.last_change_ms is None else now_ms - self.last_change_ms

    def silence_ms(self, now_ms: int) -> int | None:
        """Connection health: time since ANY frame arrived on this book's connection (heartbeats, pongs included)."""
        return None if self.last_msg_ms is None else now_ms - self.last_msg_ms

    def note_exchange_ts(self, exch_ms: int | None, recv_ms: int) -> None:
        """``network_latency_ms`` = local receive time (corrected by the measured clock offset) - exchange timestamp."""
        if isinstance(exch_ms, int):
            self.latency_ms = recv_ms + self.clock_offset_ms - exch_ms

    def invalidate(self) -> None:
        self.bids.clear()
        self.asks.clear()
        self.last_seq = None
        self.valid = False
        self.provisional = False
        self.confirmed_ms = None
        self.last_change_ms = None
        self.latency_ms = None

    def truncate(self, n: int) -> None:
        if len(self.bids) > n:
            self.bids = dict(self.sorted_bids(n))
        if len(self.asks) > n:
            self.asks = dict(self.sorted_asks(n))

    # ------------------------------------------------------------------ generic
    def replace(self, bids: Iterable[Level], asks: Iterable[Level]) -> None:
        self.bids = {p: s for p, s in bids if s > ZERO}
        self.asks = {p: s for p, s in asks if s > ZERO}


def _pairs(rows: Any) -> list[Level]:
    out: list[Level] = []
    for row in rows or []:
        p, s = D(str(row[0])), D(str(row[1]))
        if p <= ZERO or s < ZERO:
            raise BookIntegrityError(f"bad level {row!r}")
        out.append((p, s))
    return out


# ============================================================================================== Arcus
def arcus_apply_snapshot(book: OrderBook, contents: dict[str, Any], recv_ms: int) -> None:
    book.replace(_pairs(contents.get("bids")), _pairs(contents.get("asks")))
    seq = contents.get("lastSequenceId")
    if not isinstance(seq, int) or isinstance(seq, bool):
        raise BookIntegrityError("snapshot without integer lastSequenceId")
    book.last_seq = seq
    ts = contents.get("timestamp")
    book.exchange_ts_ms = ts // 1000 if isinstance(ts, int) else None      # Arcus timestamps are µs
    book.note_exchange_ts(book.exchange_ts_ms, recv_ms)
    book.confirmed_ms = recv_ms
    book.last_change_ms = recv_ms
    book.valid = True


def arcus_apply_delta(book: OrderBook, contents: dict[str, Any], recv_ms: int, n_levels: int) -> None:
    """Apply one ``l2OrderbookUpdates`` delta. Enforces ``lastSequenceId == previous + 1``."""
    if not book.valid or book.last_seq is None:
        raise BookIntegrityError("delta before snapshot")
    seq = contents.get("lastSequenceId")
    if not isinstance(seq, int) or isinstance(seq, bool):
        raise BookIntegrityError("delta without integer lastSequenceId")
    if seq <= book.last_seq:                      # duplicate / replay: ignore (never apply twice)
        return
    if seq != book.last_seq + 1:
        expected = book.last_seq + 1
        book.invalidate()
        raise SequenceGap(expected, seq)
    for side, levels in ((book.bids, contents.get("bids")), (book.asks, contents.get("asks"))):
        for p, s in _pairs(levels):
            if s == ZERO:
                side.pop(p, None)
            else:
                side[p] = s
    book.truncate(n_levels)
    book.last_seq = seq
    ts = contents.get("timestamp")
    book.exchange_ts_ms = ts // 1000 if isinstance(ts, int) else book.exchange_ts_ms
    book.note_exchange_ts(ts // 1000 if isinstance(ts, int) else None, recv_ms)
    book.confirmed_ms = recv_ms
    book.last_change_ms = recv_ms


class ArcusSync:
    """Baseline per docs.arcus.xyz/api-reference/websocket.md "Resyncing the order book": buffer deltas, take a
    snapshot (the ``subscribed`` frame or an ``l2Orderbook`` frame), apply only buffered deltas with a higher
    ``lastSequenceId`` (contiguously from snapshot+1), drop deltas at or below it. Needed because the live API was
    observed (2026-11-27) to skip 1–4 sequence ids between the ``subscribed`` snapshot and the first delta."""

    def __init__(self, book: OrderBook, depth: int, max_buffer: int = 5_000) -> None:
        self.book, self.depth, self.max_buffer = book, depth, max_buffer
        self.buffer: list[tuple[dict[str, Any], int]] = []
        self.baseline_gaps = 0          # snapshot -> first delta gaps handled by resync (not a mid-stream gap)

    @property
    def live(self) -> bool:
        return self.book.valid

    def on_delta(self, contents: dict[str, Any], recv_ms: int) -> None:
        if self.book.valid:
            seq = contents.get("lastSequenceId")
            if self.book.provisional and isinstance(seq, int) and self.book.last_seq is not None \
                    and seq > self.book.last_seq + 1:
                # first delta after the snapshot skipped ids: rebuild per the documented resync procedure
                self.baseline_gaps += 1
                self.book.invalidate()                      # -> NOT_READY until the rebuild completes
                self.buffer = [(contents, recv_ms)]
                return
            prev = self.book.last_seq
            arcus_apply_delta(self.book, contents, recv_ms, self.depth)     # LIVE: strict +1 (gap -> SequenceGap)
            # Sprint 2: only a delta that was actually APPLIED (contiguous prev + 1) proves the baseline; a duplicate /
            # replayed delta (seq <= prev, ignored by arcus_apply_delta) must not clear ``provisional``.
            if isinstance(seq, int) and prev is not None and seq == prev + 1 and self.book.last_seq == seq:
                self.book.provisional = False
            return
        self.buffer.append((contents, recv_ms))
        if len(self.buffer) > self.max_buffer:
            raise BookIntegrityError("resync buffer overflow")

    def on_snapshot(self, contents: dict[str, Any], recv_ms: int) -> bool:
        """Try to baseline from this snapshot. Returns True when the book is LIVE afterwards."""
        if self.book.valid:
            return True
        seq = contents.get("lastSequenceId")
        if not isinstance(seq, int):
            return False
        later = [(c, t) for c, t in self.buffer if isinstance(c.get("lastSequenceId"), int)
                 and c["lastSequenceId"] > seq]
        if later and later[0][0]["lastSequenceId"] != seq + 1:
            return False                                       # snapshot too old for the buffer: wait for next
        arcus_apply_snapshot(self.book, contents, recv_ms)
        self.book.truncate(self.depth)
        for c, t in later:
            arcus_apply_delta(self.book, c, t, self.depth)
        if later:
            self.book.confirmed_ms = recv_ms                    # proven current at the snapshot's arrival
            self.book.last_change_ms = recv_ms
            ts = contents.get("timestamp")
            self.book.note_exchange_ts(ts // 1000 if isinstance(ts, int) else None, recv_ms)
        self.book.provisional = not later
        self.buffer.clear()
        return True


def arcus_heartbeat(book: OrderBook, contents: dict[str, Any], recv_ms: int, n_levels: int) -> str:
    """``l2Orderbook`` full snapshot (~every 200 ms) used as a liveness proof + checksum for the delta-built book.

    Returns ``"confirmed"`` (same sequence and identical top-N: the book is proven current now), ``"behind"`` (server is
    ahead: deltas still in flight, nothing proven), ``"ahead"`` (our deltas are newer) or ``"mismatch"`` (same sequence,
    different levels: integrity failure)."""
    seq = contents.get("lastSequenceId")
    ts = contents.get("timestamp")
    if book.valid:
        book.note_exchange_ts(ts // 1000 if isinstance(ts, int) else None, recv_ms)   # every frame measures latency
    if not book.valid or not isinstance(seq, int) or book.last_seq is None:
        return "behind"
    if seq > book.last_seq:
        return "behind"
    if seq < book.last_seq:
        return "ahead"
    hb_b, hb_a = _pairs(contents.get("bids"))[:n_levels], _pairs(contents.get("asks"))[:n_levels]
    k = min(len(hb_b), len(book.bids)), min(len(hb_a), len(book.asks))
    if book.sorted_bids(k[0]) != [x for x in hb_b if x[1] > ZERO][:k[0]] or \
            book.sorted_asks(k[1]) != [x for x in hb_a if x[1] > ZERO][:k[1]]:
        return "mismatch"
    book.confirmed_ms = recv_ms
    # NOTE: a matching heartbeat does NOT clear ``provisional``: live (2026-11-27) the first delta after a snapshot
    # skipped ids even after an l2Orderbook frame at the same lastSequenceId had matched, so only a contiguous delta
    # proves the baseline (clearing it here turned the known first-delta skip into gap reconnect loops).
    return "confirmed"


# ============================================================================================== Hyperliquid
def _hl_levels(rows: Any) -> list[Level]:
    return [(D(str(r["px"])), D(str(r["sz"]))) for r in rows or []]


def hl_apply_snapshot(book: OrderBook, wsbook: dict[str, Any], recv_ms: int) -> None:
    levels = wsbook.get("levels") or [[], []]
    book.replace(_hl_levels(levels[0]), _hl_levels(levels[1]))
    t = wsbook.get("time")
    book.exchange_ts_ms = t if isinstance(t, int) else None
    book.note_exchange_ts(book.exchange_ts_ms, recv_ms)
    book.confirmed_ms = recv_ms
    book.last_change_ms = recv_ms
    book.valid = True


def hl_apply_diff(book: OrderBook, diff: dict[str, Any], recv_ms: int) -> None:
    """``WsL2Diff``: remove indexes ``r`` (positions in the previous, sorted book) per side, then upsert ``l``."""
    if not book.valid:
        raise BookIntegrityError("diff before snapshot")
    removes = diff.get("r") or [[], []]
    upserts = diff.get("l") or [[], []]
    for i, (side, ordered) in enumerate(((book.bids, book.sorted_bids()), (book.asks, book.sorted_asks()))):
        for idx in removes[i] or []:
            if not isinstance(idx, int) or idx < 0 or idx >= len(ordered):
                book.invalidate()
                raise BookIntegrityError(f"remove index {idx!r} outside previous book ({len(ordered)} levels)")
            side.pop(ordered[idx][0], None)
        for lv in upserts[i] or []:
            p, s = D(str(lv["p"])), D(str(lv["s"]))
            if p <= ZERO or s < ZERO:                   # Sprint 2: same rule as ``_pairs`` (invalidate + raise)
                book.invalidate()
                raise BookIntegrityError(f"bad l2 diff level {lv!r}")
            if s == ZERO:
                side.pop(p, None)
            else:
                side[p] = s
    t = diff.get("t")
    book.exchange_ts_ms = t if isinstance(t, int) else book.exchange_ts_ms
    book.note_exchange_ts(t if isinstance(t, int) else None, recv_ms)
    book.confirmed_ms = recv_ms
    if any(removes[i] or upserts[i] for i in (0, 1)):
        book.last_change_ms = recv_ms


def hl_check_against_snapshot(book: OrderBook, wsbook: dict[str, Any]) -> bool | None:
    """Compare the diff-built book with an ``l2Book`` snapshot of the SAME exchange ``time`` (None = not comparable)."""
    if not book.valid or wsbook.get("time") != book.exchange_ts_ms:
        return None
    levels = wsbook.get("levels") or [[], []]
    sb, sa = _hl_levels(levels[0]), _hl_levels(levels[1])
    return book.sorted_bids(len(sb)) == sb and book.sorted_asks(len(sa)) == sa
