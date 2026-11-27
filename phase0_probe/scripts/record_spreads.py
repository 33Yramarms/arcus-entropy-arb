"""Record Arcus vs Hyperliquid L2 books + funding and evaluate arbitrage every second (READ-ONLY, public data).

Usage: uv run python scripts/record_spreads.py --duration-s 600 [--db reports/spreads.sqlite]
       [--pair BTC=BTC --pair ETH=ETH --pair SOL=SOL] [--pair NVDA=io:NVDA] [--q 100 --q 500 --q 2000]
       [--max-latency-ms 500] [--conn-timeout-ms 5000] [--resid-window-s 300] [--buffer-bps 2]
Staleness (PR #1.5) = network latency (local recv − exchange timestamp, Arcus corrected by the GET /v1/time clock
offset) or a silent connection; book idleness is recorded (book_health.book_idle_ms) but never gates.
--pair SYMBOL=HLCOIN maps Arcus ``SYMBOL-USD`` to a Hyperliquid coin (``BTC`` core, ``io:NVDA`` Entropy dex).
PR #1.6 ``--record-trades``: also subscribes the public trade tape of every pair on both venues (Arcus ``trades``,
HL ``trades``) on the EXISTING per-pair sockets (no extra WebSocket connection; HL allows 10 per IP) and stores
(venue, symbol, exchange ts µs, local recv ms, price, size, side, raw side, trade id) in the ``trades`` table, prices
and sizes as exact Decimal TEXT. Trades are never used as a price input of the opportunity model.
Sprint 2: every background task runs under ``_supervise`` (an unexpected exception -> ``task_crash`` event, the
related books invalidated, restart with backoff; per-task crash counts in ``meta``) and SIGTERM / SIGHUP (e.g. tmux
closed) stop the run cleanly so ``ended_ms``, the stats meta and the WAL checkpoint are still written.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import pathlib
import signal
import sqlite3
import sys
from decimal import Decimal
from typing import Any, Awaitable, Callable

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import aiohttp  # noqa: E402

from phase0_probe.dec import D, now_ms  # noqa: E402
from phase0_probe.discovery import parse_arcus, parse_hl  # noqa: E402
from phase0_probe.feeds import ArcusBookFeed, ArcusMarketsFeed, Backoff, HlBookFeed, sleep_or_stop  # noqa: E402
from phase0_probe.model import VenueSpec  # noqa: E402
from phase0_probe.recorder import Pair, Recorder  # noqa: E402
from phase0_probe.store import Store  # noqa: E402
from phase0_probe.venues import ARCUS_REST, get_json, hl_info  # noqa: E402


async def load_specs(pairs: list[tuple[str, str]]) -> dict[str, tuple[VenueSpec, VenueSpec]]:
    dexes = sorted({c.split(":", 1)[0] if ":" in c else "" for _, c in pairs})
    async with aiohttp.ClientSession() as s:
        markets = await get_json(s, f"{ARCUS_REST}/v1/markets")
        fees = await get_json(s, f"{ARCUS_REST}/v1/markets/feeSchedules")
        hl = []
        for dex in dexes:
            body = {"type": "metaAndAssetCtxs"} | ({"dex": dex} if dex else {})
            hl += parse_hl(await hl_info(s, body), dex=dex)
    arcus = {a.base: a for a in parse_arcus(markets, fees)}
    hlm = {h.coin: h for h in hl}
    out = {}
    for sym, coin in pairs:
        a, h = arcus[sym], hlm[coin]
        out[sym] = (VenueSpec("arcus", sym, a.step, a.min_notional, a.maker_fee, a.taker_fee),
                    VenueSpec("hyperliquid", sym, h.step, h.min_notional, h.maker_fee, h.taker_fee))
    return out


async def arcus_clock_offset_ms(samples: int = 5) -> tuple[int, int]:
    """(offset, rtt) in ms: Arcus server clock − local clock, from GET /v1/time (``timeNs``, docs
    api-reference/public/get-current-server-time.md); the sample with the smallest round trip wins (NTP-style)."""
    best: tuple[int, int] | None = None
    async with aiohttp.ClientSession() as sess:
        for _ in range(samples):
            t0 = now_ms()
            body = await get_json(sess, f"{ARCUS_REST}/v1/time")
            t1 = now_ms()
            server = int(body["timeNs"]) // 1_000_000
            cand = (server - (t0 + t1) // 2, t1 - t0)
            if best is None or cand[1] < best[1]:
                best = cand
            await asyncio.sleep(2)                      # rate-limited to 1 token per call
    assert best is not None
    return best


class TaskHealth:
    """Crash bookkeeping of one supervised task (written to ``meta`` at the end of the run)."""

    def __init__(self, name: str) -> None:
        self.name, self.crashes, self.last_exc = name, 0, ""

    def meta(self) -> str:
        return f"crashes={self.crashes} last={self.last_exc or '-'}"


async def _supervise(name: str, factory: Callable[[], Awaitable[Any]], stop: asyncio.Event,
                     sink: Callable[[str, str | None, str, str], None], *, health: TaskHealth,
                     venue: str = "recorder", symbol: str | None = None,
                     on_crash: Callable[[], None] | None = None, backoff: Backoff | None = None) -> None:
    """Run ``factory()`` until ``stop``; an unexpected exception (anything but cancellation) is never silent: it is
    logged, written as a ``task_crash`` event, the related book(s) are invalidated at once (``on_crash``) so no row is
    priced from a dead feed, and the task restarts after an exponential backoff (1 s .. 30 s, see ``feeds.Backoff``).
    ``asyncio.CancelledError`` always propagates. A clean return ends supervision."""
    bo = backoff if backoff is not None else Backoff()
    while not stop.is_set():
        bo.connected(now_ms())
        try:
            await factory()
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:                                  # noqa: BLE001 - supervisor boundary by design
            health.crashes += 1
            health.last_exc = repr(exc)[:300]
            logging.getLogger("phase0.supervisor").exception("task %s crashed (#%s)", name, health.crashes)
            if on_crash is not None:
                try:
                    on_crash()
                except Exception:                                 # noqa: BLE001 - never let cleanup kill the loop
                    logging.getLogger("phase0.supervisor").exception("on_crash of %s failed", name)
            try:
                sink(venue, symbol, "task_crash", f"{name} #{health.crashes}: {health.last_exc}")
            except Exception:                                     # noqa: BLE001 - e.g. DB locked: event is best effort
                logging.getLogger("phase0.supervisor").exception("task_crash event of %s not written", name)
            if stop.is_set():
                return
            await sleep_or_stop(stop, bo.next_delay_ms(now_ms()))


def _install_stop_signals(loop: asyncio.AbstractEventLoop, stop: asyncio.Event, reason: dict[str, str]) -> list[int]:
    """SIGTERM / SIGHUP (kill, tmux kill-session / closed terminal) -> set ``stop`` so the ``finally`` block writes
    ``ended_ms`` + stats and closes the DB. Returns the installed signal numbers."""
    installed = []
    for sig in (signal.SIGTERM, signal.SIGHUP):
        def _handler(sig_name: str = sig.name) -> None:
            reason.setdefault("stop_reason", f"signal {sig_name}")
            logging.warning("received %s: stopping cleanly", sig_name)
            stop.set()
        try:
            loop.add_signal_handler(sig, _handler)
            installed.append(int(sig))
        except (NotImplementedError, RuntimeError, ValueError):   # non-Unix loop / not the main thread
            pass
    return installed


async def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration-s", type=int, default=600)
    ap.add_argument("--db", default="reports/spreads.sqlite")
    ap.add_argument("--log", default="reports/record_spreads.log")
    ap.add_argument("--pair", action="append", default=None)
    ap.add_argument("--q", action="append", default=None)
    ap.add_argument("--max-latency-ms", "--stale-ms", dest="max_latency_ms", type=int, default=500)
    ap.add_argument("--conn-timeout-ms", type=int, default=5000)
    ap.add_argument("--resid-window-s", type=int, default=300)
    ap.add_argument("--resid-min-samples", type=int, default=30)
    ap.add_argument("--buffer-bps", default="2")
    ap.add_argument("--record-trades", action="store_true", help="also record both venues' public trades (PR #1.6)")
    args = ap.parse_args(argv)
    pairs = [tuple(p.split("=", 1)) for p in (args.pair or ["BTC=BTC", "ETH=ETH", "SOL=SOL"])]
    qs = [D(q) for q in (args.q or ["100", "500", "2000"])]
    pathlib.Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        handlers=[logging.FileHandler(args.log), logging.StreamHandler()])
    specs = await load_specs(pairs)          # type: ignore[arg-type]
    offset, rtt = await arcus_clock_offset_ms()
    logging.info("arcus clock offset %s ms (rtt %s ms)", offset, rtt)
    store = Store(args.db)
    store.put_meta("arcus_clock_offset_ms", f"{offset} (rtt {rtt} ms; GET /v1/time; hyperliquid: no documented "
                                            f"server-time endpoint -> uncorrected)")
    store.put_meta("started_ms", str(now_ms()))
    store.put_meta("args", " ".join(argv))
    store.put_meta("record_trades", "1" if args.record_trades else "0")
    trade_counts = {"new": 0, "received": 0}

    def trade_sink(rows: list) -> None:          # rows: list[Trade]; committed with the next 1 Hz sample
        trade_counts["received"] += len(rows)
        trade_counts["new"] += store.trades(rows)

    tsink = trade_sink if args.record_trades else None
    stop = asyncio.Event()
    markets = ArcusMarketsFeed([f"{sym}-USD" for sym, _ in pairs], sink=lambda *a: None)
    rec = Recorder(store, [], markets, qs=qs, max_latency_ms=args.max_latency_ms,
                   conn_timeout_ms=args.conn_timeout_ms, buffer_bps=Decimal(args.buffer_bps),
                   resid_window_s=args.resid_window_s, resid_min_samples=args.resid_min_samples)
    markets.sink = rec.sink
    for sym, coin in pairs:
        sa, sb = specs[sym]
        af = ArcusBookFeed(f"{sym}-USD", rec.sink, trade_sink=tsink)
        af.book.clock_offset_ms = offset
        rec.pairs.append(Pair(sym, af, HlBookFeed(sym, coin, rec.sink, trade_sink=tsink), sa, sb))
        store.put_meta(f"spec:{sym}", f"arcus step={sa.step} min={sa.min_notional} maker={sa.maker_fee} "
                                      f"taker={sa.taker_fee} | hl coin={coin} step={sb.step} min={sb.min_notional} "
                                      f"maker={sb.maker_fee} taker={sb.taker_fee}")
    health: dict[str, TaskHealth] = {}
    tasks: list[asyncio.Task[None]] = []

    def spawn(name: str, factory: Callable[[], Awaitable[Any]], venue: str, symbol: str | None,
              on_crash: Callable[[], None] | None) -> None:
        health[name] = TaskHealth(name)
        tasks.append(asyncio.create_task(_supervise(name, factory, stop, rec.sink, health=health[name], venue=venue,
                                                    symbol=symbol, on_crash=on_crash), name=name))

    spawn("arcus_markets", lambda: markets.run(stop), "arcus", None, None)
    spawn("hl_predicted_poll", lambda: rec.poll_predicted(stop), "hyperliquid", None, None)
    spawn("sampler", lambda: rec.sampler(stop), "recorder", None, None)
    for p in rec.pairs:
        spawn(f"arcus:{p.symbol}", lambda f=p.arcus: f.run(stop), "arcus", p.arcus.market, p.arcus.invalidate)
        spawn(f"hyperliquid:{p.symbol}", lambda f=p.hl: f.run(stop), "hyperliquid", p.symbol, p.hl.invalidate)
    stop_info: dict[str, str] = {}
    loop = asyncio.get_running_loop()
    installed = _install_stop_signals(loop, stop, stop_info)
    try:
        try:
            await asyncio.wait_for(stop.wait(), timeout=args.duration_s)
        except asyncio.TimeoutError:
            stop_info.setdefault("stop_reason", "duration elapsed")
    finally:
        stop_info.setdefault("stop_reason", "interrupted (cancelled / KeyboardInterrupt)")
        stop.set()
        _done, pending = await asyncio.wait(tasks, timeout=10)
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.wait(pending, timeout=5)
        for sig in installed:
            loop.remove_signal_handler(sig)
        _write_final_meta(store, rec, health, stop_info, args.record_trades, trade_counts,
                          sorted(t.get_name() for t in pending))
        try:
            store.close()
        except sqlite3.Error:
            logging.exception("store close / WAL checkpoint failed (copy the -wal/-shm files with the DB)")
    logging.info("done: %s ticks -> %s", rec.ticks, args.db)
    return 0


def _write_final_meta(store: Store, rec: Recorder, health: dict[str, TaskHealth], stop_info: dict[str, str],
                      record_trades: bool, trade_counts: dict[str, int], pending: list[str]) -> None:
    """End-of-run meta. Each key is written independently (one failing write never blocks ``ended_ms``)."""
    items: list[tuple[str, str]] = [("ended_ms", str(now_ms()))]
    for p in rec.pairs:
        for f in (p.arcus, p.hl):
            st = f.stats
            items.append((f"stats:{f.book.venue}:{p.symbol}",
                          f"frames={st.frames} reconnects={st.reconnects} gaps={st.gaps} "
                          f"integrity_errors={st.integrity_errors} hb_confirmed={st.hb_confirmed} "
                          f"hb_mismatch={st.hb_mismatch} l2Book_checks_ok={st.checks_ok} "
                          f"l2Book_checks_bad={st.checks_bad} "
                          + " ".join(f"{k}={v}" for k, v in sorted(st.extra.items()))))
    if record_trades:
        items.append(("trades_recorded", f"received={trade_counts['received']} new_rows={trade_counts['new']}"))
    for name, h in sorted(health.items()):
        items.append((f"task_crashes:{name}", h.meta()))
    items.append(("task_crashes_total", str(sum(h.crashes for h in health.values()))))
    items.append(("db_commit_errors", str(rec.commit_errors)))
    items.append(("stop_reason", stop_info.get("stop_reason", "-")))
    items.append(("tasks_not_finished", ",".join(pending) or "-"))
    for k, v in items:
        try:
            store.put_meta(k, v)
        except sqlite3.Error:
            logging.exception("meta %s not written", k)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
