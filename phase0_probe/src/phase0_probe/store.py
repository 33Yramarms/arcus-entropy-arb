"""SQLite persistence. Every Decimal is stored as TEXT (exact); timestamps are INTEGER epoch ms."""
from __future__ import annotations

import sqlite3
from decimal import Decimal
from typing import Any, Iterable

from phase0_probe.model import Opportunity

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities (
  ts_ms INTEGER NOT NULL, symbol TEXT NOT NULL, q_usd TEXT NOT NULL, direction TEXT NOT NULL, mode TEXT NOT NULL,
  status TEXT NOT NULL, base_qty TEXT, mid_a TEXT, mid_b TEXT, ref_mid TEXT, basis_bps TEXT, open_buy_px TEXT,
  open_sell_px TEXT, open_spread_bps TEXT, open_slip_bps TEXT, close_slip_bps TEXT, fees_bps TEXT, buffer_bps TEXT,
  net_bps TEXT, net_usd TEXT, age_a_ms INTEGER, age_b_ms INTEGER);
CREATE INDEX IF NOT EXISTS ix_opp ON opportunities(symbol, q_usd, mode, ts_ms);
CREATE TABLE IF NOT EXISTS book_health (
  ts_ms INTEGER NOT NULL, symbol TEXT NOT NULL, venue TEXT NOT NULL, valid INTEGER NOT NULL, age_ms INTEGER,
  exch_lag_ms INTEGER, best_bid TEXT, best_ask TEXT, n_bids INTEGER, n_asks INTEGER, last_seq INTEGER);
CREATE TABLE IF NOT EXISTS funding (
  ts_ms INTEGER NOT NULL, symbol TEXT NOT NULL, venue TEXT NOT NULL, current_hourly TEXT, predicted_hourly TEXT);
CREATE TABLE IF NOT EXISTS events (
  ts_ms INTEGER NOT NULL, venue TEXT NOT NULL, symbol TEXT, kind TEXT NOT NULL, detail TEXT);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
"""


def s(v: Decimal | None) -> str | None:
    return None if v is None else format(v, "f")


class Store:
    def __init__(self, path: str) -> None:
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA)

    def put_meta(self, k: str, v: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (k, v))
        self.db.commit()

    def opportunities(self, ts_ms: int, rows: Iterable[Opportunity]) -> None:
        self.db.executemany(
            "INSERT INTO opportunities VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(ts_ms, o.symbol, s(o.q_usd), o.direction.value, o.mode.value, o.status, s(o.base_qty), s(o.mid_a),
              s(o.mid_b), s(o.ref_mid), s(o.basis_bps), s(o.open_buy_px), s(o.open_sell_px), s(o.open_spread_bps),
              s(o.open_slip_bps), s(o.close_slip_bps), s(o.fees_bps), s(o.buffer_bps), s(o.net_bps), s(o.net_usd),
              o.age_a_ms, o.age_b_ms) for o in rows])

    def book_health(self, rows: Iterable[tuple[Any, ...]]) -> None:
        self.db.executemany("INSERT INTO book_health VALUES (?,?,?,?,?,?,?,?,?,?,?)", list(rows))

    def funding(self, rows: Iterable[tuple[Any, ...]]) -> None:
        self.db.executemany("INSERT INTO funding VALUES (?,?,?,?,?)", list(rows))

    def event(self, ts_ms: int, venue: str, symbol: str | None, kind: str, detail: str) -> None:
        self.db.execute("INSERT INTO events VALUES (?,?,?,?,?)", (ts_ms, venue, symbol, kind, detail[:500]))

    def commit(self) -> None:
        self.db.commit()

    def close(self) -> None:
        self.db.commit()
        self.db.close()
