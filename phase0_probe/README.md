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
uv run pytest -q
```

### US-equity RTH recording (Arcus ∩ Entropy io top 5)

NYSE session Fri 2026-11-27 is a half day (09:30–13:00 ET = 22:30 Fri – 02:00 Sat MYT); regular days are
09:30–16:00 ET = 22:30–05:00 MYT (standard time). Refresh the top 5 first (`probe_rwa_overlap.py`), then:

```bash
cd /workspace/phase0_probe && nohup bash -c 'sleep $(( $(date -d "2026-11-27 22:30:00 +0800" +%s) - $(date +%s) )) \
  && uv run python scripts/record_spreads.py --duration-s 7200 \
       --pair NVDA=io:NVDA --pair SNDK=io:SNDK --pair DRAM=io:DRAM --pair MU=io:MU --pair NBIS=io:NBIS \
       --db reports/rwa_rth_20261127.sqlite --log reports/rwa_rth_20261127.log \
  && uv run python scripts/analyze_opportunity.py --db reports/rwa_rth_20261127.sqlite \
       --name rwa_rth_20261127_summary --title "RTH Fri 2026-11-27 22:30-00:30 MYT (NYSE half day)"' \
  > reports/rwa_rth_20261127.nohup 2>&1 &
```

Hyperliquid allows at most 10 WebSocket connections per IP (rate-limits-and-user-limits.md); the recorder opens one
HL connection per pair, so do not run more than ~9 pairs at once (multiplexing is a PR #2 item).

`record_spreads.py` options: `--pair SYM=HLCOIN` (default `BTC=BTC ETH=ETH SOL=SOL`; e.g. `--pair NVDA=io:NVDA` for
the Entropy dex), `--q 100 --q 500 --q 2000`, `--stale-ms 500`, `--buffer-bps 2`, `--db`, `--log`.

## Layout

| Path | What |
|---|---|
| `src/phase0_probe/dec.py` | Decimal helpers (`loads` with `parse_float=Decimal`, strict `D()` refusing floats) |
| `src/phase0_probe/book.py` | L2 books; Arcus `lastSequenceId` +1 enforcement + documented resync; HL `l2` diffs |
| `src/phase0_probe/model.py` | VWAP + net-profit model (pure functions) |
| `src/phase0_probe/feeds.py` | Read-only WS feeds (Arcus books + `markets` funding; HL `l2`/`l2Book`/`activeAssetCtx`) |
| `src/phase0_probe/discovery.py`, `venues.py` | REST discovery, fee math, endpoints / doc constants |
| `src/phase0_probe/recorder.py`, `store.py`, `analysis.py` | 1 Hz sampler, SQLite, statistics |
| `scripts/*.py` | the three entry points |
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
* `stale` if either book's age > 500 ms or it is not valid. Age = now − last time the local book was *proven* current:
  Arcus — last contiguous delta or an `l2Orderbook` snapshot with the same `lastSequenceId` and identical top-20 levels;
  HL — last `l2` message.
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
