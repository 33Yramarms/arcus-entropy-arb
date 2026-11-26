"""PR #1.6 — public trade-tape parsing (READ-ONLY). Trades are RECORDED and used only by the Maker fill-through filter
and the side-consistency diagnostics in ``realism.py``; they never feed a price into the opportunity model
(``model.py`` prices from L2 books only).

Documented channels:
* Arcus WS ``{"type":"subscribe","channel":"trades","id":"<MARKET>"}`` (api-reference/channels.md ``trades``): no
  snapshot on subscribe; ``contents`` = array of fills of ONE taker order match (same ``takerOrderId``, ``timestamp``,
  ``sequenceNumber``); ``timestamp`` in Unix MICROseconds; fields ``price``, ``size``, ``side``, ``tradeId``.
  TODO: VERIFY_FROM_DOCS — the docs do not say whether ``side`` is the taker's or the maker's side; assumed TAKER
  (aggressor) because the message is defined as one taker order's match. Live check 2026-11-27 03:11 MYT
  (reports/trades_live_check_summary.md): BUY prints at/above the 1 Hz mid 96.7 % (30), SELL 0.0 % (29) -> consistent
  with the taker side; still undocumented.
* HL WS ``{"method":"subscribe","subscription":{"type":"trades","coin":"<coin>"}}`` (websocket/subscriptions.md
  item 8) -> ``WsTrade[]`` {coin, side, px, sz, hash, time (ms), tid, users}. ``tid`` is a 50-bit hash of
  (buyer_oid, seller_oid); a globally unique id is (time, coin, tid) (docs comment).
  TODO: VERIFY_FROM_DOCS — the meaning of ``side`` ("A"/"B") is not defined on the page; assumed the AGGRESSOR side
  ("B" = taker bought / lifted the ask, "A" = taker sold / hit the bid). Live check 2026-11-27 03:11 MYT: "B" at/above
  mid 98.0 % (100), "A" 5.4 % (148) -> consistent with the aggressor side; still undocumented.
  Observed live (undocumented): right after subscribing HL replays the most recent 30 trades of the coin (for io:MU
  these went back ~3 h). They carry their real exchange ``time`` and are de-duplicated on reconnect; analyses select
  trades by exchange time, so replayed rows outside the window are ignored.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from phase0_probe.dec import D

HL_SIDE = {"B": "BUY", "A": "SELL"}          # TODO: VERIFY_FROM_DOCS (see module docstring)
ARCUS_SIDE = {"BUY": "BUY", "SELL": "SELL"}  # TODO: VERIFY_FROM_DOCS (taker side assumed)


@dataclass(frozen=True)
class Trade:
    venue: str
    symbol: str                # Arcus base symbol (pair key), e.g. "NVDA"
    exch_ts_us: int            # exchange timestamp, epoch µs (HL ms × 1000)
    recv_ms: int               # local receive time, epoch ms
    price: Decimal
    size: Decimal
    side: str                  # BUY | SELL | UNKNOWN (aggressor, per the TODO assumptions above)
    raw_side: str
    trade_id: str


def parse_arcus_trades(msg: dict[str, Any], symbol: str, market: str, recv_ms: int) -> list[Trade]:
    if msg.get("channel") != "trades" or msg.get("type") != "channel_data" or msg.get("id") not in (None, market):
        return []
    out = []
    for f in msg.get("contents") or []:
        if not isinstance(f, dict) or f.get("marketDisplayName", market) != market:
            continue
        raw = str(f.get("side", ""))
        out.append(Trade("arcus", symbol, int(f["timestamp"]), recv_ms, D(str(f["price"])), D(str(f["size"])),
                         ARCUS_SIDE.get(raw.upper(), "UNKNOWN"), raw, str(f.get("tradeId", ""))))
    return out


def parse_hl_trades(msg: dict[str, Any], symbol: str, coin: str, recv_ms: int) -> list[Trade]:
    if msg.get("channel") != "trades" or not isinstance(msg.get("data"), list):
        return []
    out = []
    for t in msg["data"]:
        if not isinstance(t, dict) or t.get("coin") != coin:
            continue
        raw = str(t.get("side", ""))
        out.append(Trade("hyperliquid", symbol, int(t["time"]) * 1000, recv_ms, D(str(t["px"])), D(str(t["sz"])),
                         HL_SIDE.get(raw, "UNKNOWN"), raw, str(t.get("tid", ""))))
    return out
