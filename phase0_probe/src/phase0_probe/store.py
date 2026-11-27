"""SQLite persistence. Every Decimal is stored as TEXT (exact); timestamps are INTEGER epoch ms."""
from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Any, Iterable

from phase0_probe.model import Opportunity
from phase0_probe.trades import Trade

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
  ts_ms INTEGER NOT NULL, symbol TEXT NOT NULL, q_usd TEXT NOT NULL, direction TEXT NOT NULL, mode TEXT NOT NULL,
  status TEXT NOT NULL, base_qty TEXT, mid_a TEXT, mid_b TEXT, ref_mid TEXT, basis_bps TEXT, open_buy_px TEXT,
  open_sell_px TEXT, open_spread_bps TEXT, open_slip_bps TEXT, close_slip_bps TEXT, fees_bps TEXT, buffer_bps TEXT,
  net_bps TEXT, net_usd TEXT, basis_median_bps TEXT, residual_bps TEXT, net_resid_bps TEXT,
  lat_a_ms INTEGER, lat_b_ms INTEGER, idle_a_ms INTEGER, idle_b_ms INTEGER, silence_a_ms INTEGER,
  silence_b_ms INTEGER);
CREATE INDEX IF NOT EXISTS ix_opp ON opportunities(symbol, q_usd, mode, ts_ms);
CREATE TABLE IF NOT EXISTS book_health (
  ts_ms INTEGER NOT NULL, symbol TEXT NOT NULL, venue TEXT NOT NULL, ready INTEGER NOT NULL, valid INTEGER NOT NULL,
  network_latency_ms INTEGER, book_idle_ms INTEGER, conn_silence_ms INTEGER, proven_age_ms INTEGER,
  best_bid TEXT, best_ask TEXT, n_bids INTEGER, n_asks INTEGER, last_seq INTEGER);
CREATE TABLE IF NOT EXISTS funding (
  ts_ms INTEGER NOT NULL, symbol TEXT NOT NULL, venue TEXT NOT NULL, current_hourly TEXT, predicted_hourly TEXT);
CREATE TABLE IF NOT EXISTS events (
  ts_ms INTEGER NOT NULL, venue TEXT NOT NULL, symbol TEXT, kind TEXT NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS trades (
  venue TEXT NOT NULL, symbol TEXT NOT NULL, exch_ts_us INTEGER NOT NULL, recv_ms INTEGER NOT NULL,
  price TEXT NOT NULL, size TEXT NOT NULL, side TEXT NOT NULL, raw_side TEXT, trade_id TEXT NOT NULL,
  UNIQUE (venue, symbol, exch_ts_us, trade_id, price, size));
CREATE INDEX IF NOT EXISTS ix_trades ON trades(venue, symbol, exch_ts_us);
"""


def s(v: Decimal | None) -> str | None:
    return None if v is None else format(v, "f")


BUSY_TIMEOUT_S = 30


class Store:
    """Sprint 2: WAL journal (readers such as ``analyze_opportunity.py`` never block the recorder's commits and vice
    versa), ``synchronous=NORMAL`` (durable at checkpoints; a crash can lose at most the last commits, never corrupt)
    and a 30 s busy timeout. Copy a live / unclean DB together with its ``-wal`` and ``-shm`` files."""

    def __init__(self, path: str) -> None:
        self.db = sqlite3.connect(path, timeout=BUSY_TIMEOUT_S)
        self.db.execute("PRAGMA journal_mode=WAL")          # ':memory:' DBs answer 'memory' (no WAL): harmless
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_S * 1000}")
        self.db.executescript(SCHEMA)

    def put_meta(self, k: str, v: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (k, v))
        self.db.commit()

    def opportunities(self, ts_ms: int, rows: Iterable[Opportunity]) -> None:
        self.db.executemany(
            "INSERT INTO opportunities VALUES (" + ",".join("?" * 29) + ")",
            [(ts_ms, o.symbol, s(o.q_usd), o.direction.value, o.mode.value, o.status, s(o.base_qty), s(o.mid_a),
              s(o.mid_b), s(o.ref_mid), s(o.basis_bps), s(o.open_buy_px), s(o.open_sell_px), s(o.open_spread_bps),
              s(o.open_slip_bps), s(o.close_slip_bps), s(o.fees_bps), s(o.buffer_bps), s(o.net_bps), s(o.net_usd),
              s(o.basis_median_bps), s(o.residual_bps), s(o.net_resid_bps), o.lat_a_ms, o.lat_b_ms, o.idle_a_ms,
              o.idle_b_ms, o.silence_a_ms, o.silence_b_ms) for o in rows])

    def book_health(self, rows: Iterable[tuple[Any, ...]]) -> None:
        self.db.executemany("INSERT INTO book_health VALUES (" + ",".join("?" * 14) + ")", list(rows))

    def funding(self, rows: Iterable[tuple[Any, ...]]) -> None:
        self.db.executemany("INSERT INTO funding VALUES (?,?,?,?,?)", list(rows))

    def trades(self, rows: Iterable[Trade]) -> int:
        """PR #1.6: insert public trades (Decimal as exact TEXT); duplicates (e.g. a replay after reconnect) ignored.
        Committed with the next 1 Hz sample. Returns the number of new rows."""
        before = self.db.total_changes
        self.db.executemany("INSERT OR IGNORE INTO trades VALUES (?,?,?,?,?,?,?,?,?)",
                            [(t.venue, t.symbol, t.exch_ts_us, t.recv_ms, s(t.price), s(t.size), t.side, t.raw_side,
                              t.trade_id) for t in rows])
        return self.db.total_changes - before

    def event(self, ts_ms: int, venue: str, symbol: str | None, kind: str, detail: str) -> None:
        self.db.execute("INSERT INTO events VALUES (?,?,?,?,?)", (ts_ms, venue, symbol, kind, detail[:500]))

    def commit(self) -> None:
        self.db.commit()

    def journal_mode(self) -> str:
        return str(self.db.execute("PRAGMA journal_mode").fetchone()[0])

    def close(self) -> None:
        try:
            self.db.commit()
            # fold the WAL back into the main file so the .sqlite alone is complete after a clean exit
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            self.db.close()
