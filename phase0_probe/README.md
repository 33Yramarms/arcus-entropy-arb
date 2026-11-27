# phase0_probe — Arcus × Hyperliquid (core + Entropy HIP-3 dex `io`) Phase 0 READ-ONLY validation

**Scope:** public market data only. There is **no** order-entry, signature, private-key or account code in this
directory (a static test enforces it). Every financial value is a `decimal.Decimal`; JSON is parsed with
`parse_float=Decimal`; another static test fails on any float literal, `float(...)` or float clock call.

## Run

```bash
uv sync                                                   # Python 3.12+, aiohttp, websockets, pytest
uv run python scripts/discover_markets.py                 # -> reports/overlap_markets.{json,md} + reports/raw/
uv run python scripts/record_spreads.py --duration-s 600  # -> reports/spreads.sqlite + reports/record_spreads.log
uv run python scripts/analyze_opportunity.py --window-h 24  # -> reports/opportunity_summary.{json,md}
# PR #1.5 validation
uv run python scripts/verify_basis_and_funding.py         # -> reports/basis_funding_check.{json,md} (+ raw JSON on stdout)
uv run python scripts/analyze_funding_history.py --days 30 # -> reports/funding_history.{json,md} (--days 14 also)
uv run python scripts/probe_rwa_overlap.py --top 5        # -> reports/rwa_overlap_probe.{json,md} + --pair list
uv run python scripts/probe_hl_ws_cadence.py --secs 30    # HL l2Book / l2 / bbo push cadence + latency
# PR #1.6 RWA prep
uv run python scripts/analyze_rwa_funding_and_basis.py    # -> reports/rwa_funding_basis.{json,md} (10 equities)
uv run python scripts/analyze_rwa_funding_and_basis.py --skip-history --samples 24 --every-s 300  # oracle only (RTH)
uv run python scripts/record_spreads.py --record-trades ... # + both venues' public trades -> `trades` table
uv run python scripts/analyze_opportunity.py --db X.sqlite --fill-window-s 5 [--fill-through]  # + Maker realism
uv run pytest -q
```

### Tonight: RTH recording Fri 2026-11-27, 22:30 → 00:30 MYT (NYSE half day) — run it yourself (VPS / laptop)

NYSE Fri 2026-11-27 is an early-close day: 09:30–13:00 ET = **22:30 Fri – 02:00 Sat MYT** (regular days 09:30–16:00 ET
= 22:30–05:00 MYT in US standard time). The window below (09:30–11:30 ET) is fully inside RTH. Nothing is scheduled
in the cloud: paste this once on your own machine (GNU `date`; on macOS use `gdate` from coreutils). It waits until
22:30 MYT if started early, records until 00:30 MYT (5 pairs → 5 Arcus + 1 Arcus `markets` + 5 HL sockets; trades ride
on the same sockets, so HL stays at 5 of its 10 connections per IP), samples the oracle / mark / mid of all 10
overlaps every 5 min in parallel, then runs the analysis (touch and strictly-through variants):

```bash
cd arcus-entropy-arb/phase0_probe && git checkout main && git pull && uv sync && \
OUT=reports/rth_20261127 && mkdir -p $OUT && \
START=$(date -d "2026-11-27 22:30:00 +0800" +%s) && END=$(date -d "2026-11-28 00:30:00 +0800" +%s) && \
sleep $(( START > $(date +%s) ? START - $(date +%s) : 0 )) && \
DUR=$((END - $(date +%s))) && [ "$DUR" -gt 0 ] && echo "recording ${DUR}s -> $OUT" && \
( uv run python scripts/analyze_rwa_funding_and_basis.py --skip-history --samples 24 --every-s 300 \
    --out $OUT --name rwa_oracle_rth > $OUT/rwa_oracle_rth_stdout.txt 2>&1 & ) && \
uv run python scripts/record_spreads.py --duration-s $DUR --record-trades \
    --pair NVDA=io:NVDA --pair SNDK=io:SNDK --pair DRAM=io:DRAM --pair MU=io:MU --pair NBIS=io:NBIS \
    --db $OUT/rwa_rth_20261127.sqlite --log $OUT/rwa_rth_20261127.log && \
uv run python scripts/analyze_opportunity.py --db $OUT/rwa_rth_20261127.sqlite --out $OUT \
    --name rwa_rth_20261127_summary --fill-window-s 5 \
    --title "RTH Fri 2026-11-27 22:30-00:30 MYT (NYSE half day), touch" && \
uv run python scripts/analyze_opportunity.py --db $OUT/rwa_rth_20261127.sqlite --out $OUT \
    --name rwa_rth_20261127_summary_through --fill-window-s 5 --fill-through \
    --title "RTH Fri 2026-11-27 22:30-00:30 MYT (NYSE half day), strictly through"
```

Outputs in `reports/rth_20261127/`: `rwa_rth_20261127.sqlite` (opportunities, book_health, funding, events, **trades**),
`.log`, `rwa_rth_20261127_summary{,_through}.{md,json}` (incl. Maker realism + adverse selection + trade side check),
`rwa_oracle_rth.{md,json}` (Pyth-vs-HL oracle gap in RTH). To survive an SSH drop, wrap the whole line in
`nohup bash -c '…' > reports/rth_20261127.nohup 2>&1 &` or run it inside `tmux`.

Hyperliquid allows at most 10 WebSocket connections per IP (rate-limits-and-user-limits.md); the recorder opens one
HL connection per pair (`--record-trades` adds none), so do not run more than ~9 pairs at once.

`record_spreads.py` options: `--pair SYM=HLCOIN` (default `BTC=BTC ETH=ETH SOL=SOL`; e.g. `--pair NVDA=io:NVDA` for
the Entropy dex), `--q 100 --q 500 --q 2000`, `--stale-ms 500`, `--buffer-bps 2`, `--db`, `--log`, `--record-trades`.

## Layout

| Path | What |
|---|---|
| `src/phase0_probe/dec.py` | Decimal helpers (`loads` with `parse_float=Decimal`, strict `D()` refusing floats) |
| `src/phase0_probe/book.py` | L2 books; Arcus `lastSequenceId` +1 enforcement + documented resync; HL `l2` diffs |
| `src/phase0_probe/model.py` | VWAP + net-profit model (pure functions) |
| `src/phase0_probe/feeds.py` | Read-only WS feeds (Arcus books + `markets` funding; HL `l2`/`l2Book`/`activeAssetCtx`) |
| `src/phase0_probe/discovery.py`, `venues.py` | REST discovery, fee math, endpoints / doc constants |
| `src/phase0_probe/recorder.py`, `store.py`, `analysis.py` | 1 Hz sampler, SQLite, statistics |
| `src/phase0_probe/sessions.py` | PR #1.6 NYSE calendar (holidays, early closes, DST) + Arcus 04–20 ET window |
| `src/phase0_probe/trades.py`, `realism.py` | PR #1.6 trade-tape parsing; Maker fill-through filter, adverse selection |
| `scripts/*.py` | entry points |
| `docs_snapshot/` | the documentation pages these facts were taken from (fetched 2026-11-27 MYT) |
| `reports/` | outputs of the live run |

## Model (per symbol × Q × direction × mode, every second)

* `base = floor(Q / ref_mid, max(lot_A, lot_B))`, `ref_mid = (mid_Arcus + mid_HL)/2`; mids from the L2 books only
  (**the last trade price is never used**).
* Taker legs: VWAP through the visible L2 levels; if the book cannot fill `base` → `insufficient_depth` (no opportunity).
* Maker legs (Maker-Taker modes): priced at the own-side touch (buy at best bid, sell at best ask) — an upper bound:
  queue position / fill probability are not modelled (Phase 0).
* Directions: `BUY_ARCUS_SELL_HL`, `BUY_HL_SELL_ARCUS`. Modes: `DUAL_TAKER`, `MAKER_ARCUS_TAKER_HL`,
  `MAKER_HL_TAKER_ARCUS` (the two Maker-Taker variants).
* `open_spread_bps = (sell_px − buy_px)/ref_mid`; `open_slip_bps` and `close_slip_bps` = cost vs each venue's own mid
  for the open and (current-book) close trades; `fees_bps = 2 × (fee_buy_leg + fee_sell_leg)` (open + close).
* `net_bps = open_spread_bps − close_slip_bps − fees_bps − 2 bps buffer` — assumes the inter-venue basis converges to 0
  by the exit. A persistent structural basis (e.g. HL oracle in USDT vs Arcus in USD) breaks that assumption: read the
  `median basis` column before trusting a "persistent" opportunity.
* `not_ready` if either book is not valid / still provisional; `stale` (since PR #1.5, see below) if either book's
  `network_latency_ms` > `--max-latency-ms` (500) or its connection has been silent > `--conn-timeout-ms` (5000).
  Book idleness / proven age are recorded in `book_health` but never gate. Sprint 2: while Arcus `l2Orderbook`
  heartbeats show a newer `lastSequenceId` than the delta-built book, its latency is measured from the first such
  heartbeat (a stalled delta stream therefore turns `stale`), and after 5 s of that the book is rebuilt.
* Funding differential: (HL − Arcus) hourly rate × 8760 (positive = long Arcus / short HL receives carry).

## Documented facts used (URLs)

Arcus (docs.arcus.xyz, OpenAPI version `openapi-2026.11.23`):
* Markets: `GET /v1/markets` — https://docs.arcus.xyz/api-reference/public/get-markets.md (stepSize, minOrderNotional,
  effectiveMaker/TakerFeePpm, fundingRate, nextFundingRate "forecast for the next funding rate", initialMarginFraction).
* Per-market fee schedules: `GET /v1/markets/feeSchedules` — https://docs.arcus.xyz/api-reference/public/get-market-fee-schedules.md
  ("full effective per-tier fee schedule each market charges").
* Exchange-wide fee tier table: `GET /v1/feetiers` — https://docs.arcus.xyz/api-reference/public/get-fee-tier-table.md
* Fees concept — https://docs.arcus.xyz/concepts/perpetuals/fees.md
* Funding is **charged once an hour**; rate = hourly — https://docs.arcus.xyz/concepts/perpetuals/funding.md
* WS endpoint `wss://api.arcus.xyz/v1/ws`; subscribe envelope; `nLevels` 1–100;
  order-book sequence contiguity ("every delta is previous + 1, including the first after a snapshot"; gap → rebuild);
  resync procedure (buffer, snapshot, apply higher deltas) — https://docs.arcus.xyz/api-reference/websocket.md
* Channels `l2OrderbookUpdates` (snapshot + deltas, size "0" removes), `l2Orderbook` (full snapshot ~200 ms),
  `markets` (full MarketInfo per market) — https://docs.arcus.xyz/api-reference/channels.md

Hyperliquid (hyperliquid.gitbook.io/hyperliquid-docs):
* Info endpoint `POST https://api.hyperliquid.xyz/info` — https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint.md
* `perpDexs`, `meta`/`metaAndAssetCtxs` with `dex` (default "" = first perp dex), `szDecimals`, `maxLeverage`,
  `onlyIsolated` (deprecated), `marginMode` (`strictIsolated` / `noCross`), `growthMode`, `predictedFundings` —
  https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals.md
* Fees: perps base tier taker 0.045 % / maker 0.015 %; HIP-3 fee formula (`deployerFeeScale`, growth mode ×0.1) —
  https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees.md
* HIP-3 (independent margining / order books per dex) — https://hyperliquid.gitbook.io/hyperliquid-docs/hyperliquid-improvement-proposals-hips/hip-3-builder-deployed-perpetuals.md
* Funding paid every hour at 1/8 of the 8 h rate — https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding.md
* Lot size = `szDecimals` — https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/tick-and-lot-size.md
* Oracle in USDT, collateral USDC — https://hyperliquid.gitbook.io/hyperliquid-docs/trading/contract-specifications.md
* WS `wss://api.hyperliquid.xyz/ws`; `l2Book`, `l2` (snapshot + diffs, raw-DEFLATE `c`), `activeAssetCtx` —
  https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions.md ; ping every <60 s —
  https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/timeouts-and-heartbeats.md

## Discrepancies / observations

* Fee endpoint: both exist. `/v1/markets/feeSchedules` = per-market effective schedule (used here, tier 0);
  `/v1/feetiers` = exchange-wide default table (earlier sessions used this one). Markets with `hasCustomSchedule`
  (equities) differ from the default (observed 0 / 2.25 bps maker/taker vs 1.5 / 4.5 bps).
* Arcus `l2OrderbookUpdates`: the docs say the first delta after the snapshot is snapshot+1, but live the first delta
  sometimes skipped 1–4 ids (seen on BTC and SOL, 2026-11-27). Handled with the documented resync (rebuild from the next
  `l2Orderbook` frame + buffered deltas); mid-stream gaps after a baseline still log + reconnect.
* A 20-level local Arcus book diverged from `l2Orderbook` (levels re-entering the top 20 are not re-sent): the book is
  kept 100 deep (`nLevels=100`) and checked against the top 20.
* Hyperliquid `l2Book` arrived only every ~12 s on 2026-11-27 (subscription ack shows `"fast": false`, undocumented);
  the `l2` snapshot+diff stream arrives ~2/s and is used for the book; `l2Book` is only a checksum when `time` matches.
* Entropy dex `io` lists no BTC/ETH/SOL → those use HL core. `io` overlaps with Arcus are equities (NVDA, AAPL, …).

## PR #1.5 — validation changes and findings

* **Staleness redefined.** `stale` now means *network* staleness: `network_latency_ms` (local receive + measured clock
  offset − exchange timestamp of the latest timestamped frame; Arcus offset from `GET /v1/time`
  https://docs.arcus.xyz/api-reference/public/get-current-server-time.md, HL uncorrected — no documented time endpoint)
  > `--max-latency-ms` (500), or the connection silent > `--conn-timeout-ms` (5000; HL pings every 5 s so a pong proves
  liveness). `book_idle_ms` (no book change) is recorded in `book_health` but never gates.
* **NOT_READY.** A book is `ready` only after a snapshot AND the first contiguous delta (Arcus) / snapshot (HL). During
  the documented resync after a first-delta skip the Arcus book is invalid → rows are `not_ready` and no arbitrage
  maths runs. A matching `l2Orderbook` frame does **not** end the provisional state (live, the skip happened after a
  matching heartbeat; clearing it there turned the skip into reconnect loops — caught in this PR's first live run).
* **Residual spread.** Each second the recorder keeps a rolling median (`--resid-window-s` 300, ≥ 30 samples, previous
  window only) of the HL − Arcus mid basis; `net_resid_bps` assumes the exit at that median instead of 0 and is the
  primary opportunity metric (`net_bps` kept for comparison).
* **Hyperliquid `l2` is documented** (websocket/subscriptions.md item 23, `WsL2` = `{s: WsBook} | {u: WsL2Diff} | {c}`),
  so it stays. `l2Book` arrives every ~12.1–12.5 s with default params and with `nSigFigs: 5` (not a precision issue);
  the subscription ack echoes an UNDOCUMENTED `"fast": false`; subscribing with `"fast": true` gives ~540 ms (matching
  the documented "pushed on each block that is at least 0.5 since last push"). Not used (undocumented) —
  TODO: VERIFY_FROM_DOCS. Rate limits (10 connections, 1000 subscriptions, 2000 msgs/min) are not the cause.
  https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/rate-limits-and-user-limits.md
* **Basis source (item 1).** HL oracles are USDT-denominated (contract-specifications.md) while Arcus oracles are Pyth
  USD (https://docs.arcus.xyz/concepts/perpetuals/prices.md): the HL − Arcus oracle gap (~12.2–12.8 bps) equals the
  USDT/USD premium (third-party Kraken ticker 0.99873 → 12.77 bps). The HL book trades ~5 bps *below* its oracle.
* **Funding (item 1/2).** Both venues: hourly decimal fractions, positive ⇒ longs pay shorts. HL `fundingHistory`
  `fundingRate` = (P + clamp(0.0001 − P, ±0.0005)) / 8 to the printed 10 decimals for the last 30 days (rows from
  Nov 2023 differ by a constant 0.000025/h for large positive premiums → older parameters).
* **Hardening:** `parse_predicted` divides by `fundingIntervalHours` (HlPerp was 1 h in every observed response, so
  Phase 0 numbers are unaffected).

## PR #1.6 — RWA prep (US equities, Arcus ∩ io)

* **`analyze_rwa_funding_and_basis.py`** (all 10 non-delisted overlaps): live oracle / mark / book-mid on both venues
  (median of samples, bps of the Arcus oracle), real fees (Arcus `feeSchedules` tier 0: maker 0 / taker 2.25 bps on
  every equity; io growth mode 0.30 / 0.90 bps), Arcus RTH vs off-hours margin (`initialMarginFraction` →
  `offHoursInitialMarginFraction`, ×1.5 on every equity; maintenance not uplifted), and a 14 / 30-day hourly funding
  back-test split RTH / OFF_HOURS (and RTH / EXT / CLOSED) with both directions, flips, longest runs, break-even and
  net after each market's real round-trip fees (DUAL_TAKER 6.30, MAKER_ARCUS_TAKER_HL 1.80, MAKER_HL_TAKER_ARCUS
  5.10 bps), holding through vs paying a round trip per session block.
* **Sessions.** Payment at H is labelled by its accrual midpoint H − 30 min: 7 RTH payments on a full day (10:00…16:00
  ET), 4 on an early-close day; Thanksgiving none. Arcus' own window is 04:00–20:00 ET (`regularTradingHours`
  14400→72000): live data show Arcus funding is book-driven in RTH **and** EXT and pinned (SOFR + 0.5 %/yr, a handful
  of changes in 30 days) only in CLOSED hours. Off-hours (outside that window) the Arcus *oracle* is its own mark
  (prices.md) — an oracle gap measured then is not oracle-vs-oracle.
* **`--record-trades`.** Arcus `trades` (channels.md) and HL `trades` (subscriptions.md item 8) on the existing per-pair
  sockets; rows (venue, symbol, exchange µs, recv ms, price, size, side, raw side, id) as Decimal TEXT, de-duplicated
  (HL replays the last 30 trades on subscribe — observed live). Side semantics are undocumented on both venues; the
  live check shows both are the aggressor side (Arcus BUY ≥ mid 96.7 %, SELL 0 %; HL "B" 98.0 %, "A" 5.4 %).
* **Maker realism** (`analyze_opportunity.py`): (a) fill-through filter — a Maker-Taker second counts only with a
  maker-venue trade at/through the maker price or the opposite top of book reaching it within `--fill-window-s`;
  (b) adverse selection of the hedge leg at +1/+3/+5 s. On the Thanksgiving MU sample (no trades recorded → book
  criterion only) the 516-second MU MAKER_HL_TAKER_ARCUS "opportunity" is suppressed to 0 (5 s window; 1 s with 30 s).
* Static guard: trades may only be touched by `trades.py`, `feeds.py`, `store.py`, `realism.py`, `record_spreads.py`,
  `analyze_opportunity.py`; pricing modules (`model.py`, `book.py`, …) are scanned and never import them.

## PR #1.7 — dynamic funding-differential back-test (offline, read-only)

```bash
uv run python scripts/backtest_dynamic_funding.py               # live fetch (public endpoints) -> reports/backtest_funding_cache.json
uv run python scripts/backtest_dynamic_funding.py --from-cache  # fully offline, reproducible
uv run python scripts/backtest_dynamic_funding.py --from-pr16-report reports/rwa_funding_basis.json  # PR #1.6 dataset
```

* Logic: `src/phase0_probe/backtest.py` (pure, Decimal only). Output: `reports/backtest_dynamic_funding.{json,md}`.
* No look-ahead: the decision for hourly payment *i* only receives realized diffs `0..i−1` (`decide()` asserts it);
  a position opened at *i* earns payment *i* onward, a close at *i* forfeits payment *i*; tested by perturbing future rates.
* Strategy A (all hours) / B (Arcus off-hours window: 20:00–04:00 ET + weekends + NYSE holidays, PR #1.6 calendar),
  K ∈ {1, 3}, entry_apr ∈ {12, 18, 25, 35} %, exit_apr ∈ {0, 4} % (direction-aware: `dir × rolling ≤ exit_apr`),
  2-hour reversal exit, data-gap / window-end / end-of-data forced closes; costs 2.8 / 8.3 bps per round trip
  (half at open, half at close).
* Capital per $1 notional per leg = 1.5 × Arcus off-hours IMF + 1.5 × (1 / io maxLeverage); portfolio = equal capital,
  always allocated. Best parameters are in-sample — see the 50/50 out-of-sample table in the report.

## TODO: VERIFY_FROM_DOCS

* HL minimum order value ($10 used) — not on the fees / tick-and-lot-size / contract-spec pages.
* HL asset ctx `funding` = rate for the current hour (inferred from the funding page; not stated on the ctx schema).
* HL `predictedFundings` interval per venue (example shows HlPerp 1 h vs CEX 8 h).
* Whether HL "aligned quote token" discounts apply to dex `io` collateral (worst case assumed: no discount).
* Account-specific fee tiers (HL `userFees`, Arcus account tier) — Phase 0 uses tier 0 on both.
* Arcus `l2OrderbookUpdates` behaviour for levels moving in/out of `nLevels` (empirically: not re-sent).
* HL `l2` diff stream has no sequence number: integrity can only be cross-checked against `l2Book` at equal `time`.
* HL `l2Book` `fast` flag (echoed in the subscription ack, not documented) and the ~12 s default cadence.
* HL has no documented server-time endpoint → HL latency includes the local-vs-exchange clock offset.
* Arcus `l2OrderbookUpdates`: why the first delta after a snapshot skips sequence ids (contradicts websocket.md).
* HL `fundingHistory` parameters for 2023 (constant 0.000025/h offset on large positive premiums).
* PR #1.6: Arcus `trades.side` and HL `WsTrade.side` meaning (aggressor assumed; live check consistent, undocumented).
* PR #1.6: HL replays the most recent 30 trades on `trades` subscribe (observed, undocumented).
* PR #1.6: whether Arcus shortens its 20:00 ET window on NYSE early-close days ([待实测确认] tonight: watch
  `isOutsideRth` after 13:00 ET).
* PR #1.6: HIP-3 io has no session-dependent margin field in `metaAndAssetCtxs` ([待实测确认]).
* PR #1.6: io MU listed ~2026-11-20 (148 aligned hours), GOOGL / META / INTC also shorter than 30 days on io.

## Sprint 2 — P0/P1 hardening (recording only; no CLI / table change)

* **Supervised tasks** (`scripts/record_spreads.py::_supervise`): every feed / sampler / poll task restarts after an
  unexpected exception with backoff; each crash writes a `task_crash` event and invalidates the related book(s)
  immediately. End-of-run meta: `task_crashes:<task>`, `task_crashes_total`, `db_commit_errors`, `stop_reason`,
  `tasks_not_finished`. SIGTERM / SIGHUP (tmux closed, `kill`) stop the run cleanly: `ended_ms`, stats, checkpoint.
* **SQLite** (`store.py`): `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=30000`; analysing the DB while it
  is being recorded no longer locks the recorder. A failed write/commit skips the second (`db_commit_error` event),
  the sampler keeps running. Copy a DB that is still open together with its `-wal` / `-shm` files.
* **Reconnects** (`feeds.py::Backoff`): exponential 1 s → 30 s with jitter, reset after a 60 s stable session;
  malformed payloads (`ValueError`, `KeyError`, `TypeError`, `IndexError`, `InvalidOperation`, `zlib.error`) log a
  `payload_error` event and reconnect instead of killing the task. HL: 15 s no-frame watchdog (`watchdog_reconnect`).
  Arcus: delta-stall guard (`delta_stall_rebuild` in the stats meta).
* **Books**: a duplicate delta no longer ends the provisional state; an HL diff level with price ≤ 0 or size < 0
  invalidates the book (`BookIntegrityError`, same rule as Arcus).
* **Realism**: `trades_table` is true only if trades were actually recorded (`meta.record_trades`, else a non-empty
  table); adverse selection uses the hedge VWAP only — a missing t + k VWAP is counted in `missing_hedge_vwap` and
  excluded (no top-of-book substitute; `top_of_book_fallback` is always 0).
* Monday 7-symbol run: same command as above on `main`, with
  `--pair NVDA=io:NVDA --pair SNDK=io:SNDK --pair DRAM=io:DRAM --pair MU=io:MU --pair NBIS=io:NBIS
  --pair CRCL=io:CRCL --pair INTC=io:INTC` (7 HL + 8 Arcus sockets) and a new `OUT` directory / dates.
