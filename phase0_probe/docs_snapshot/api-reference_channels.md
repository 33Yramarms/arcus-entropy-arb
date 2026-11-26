> ## Documentation Index
> Fetch the complete documentation index at: https://docs.arcus.xyz/llms.txt
> Use this file to discover all available pages before exploring further.

# Channels

> WebSocket channel reference for Arcus

| Channel | Auth | ID format | Notes |
| - | - | - | - |
| [`l2Orderbook`](#l2orderbook) | public | market (e.g. `BTC-USD`) | Full snapshot every \~200 ms. `nLevels` 1–100, default 20. |
| [`l2OrderbookUpdates`](#l2orderbookupdates) | public | market | Initial snapshot, then incremental updates. Same `nLevels` parameter. |
| [`trades`](#trades) | public | market | Live public trade stream; no snapshot on subscribe. |
| [`markets`](#markets) | public | *(global, no `id`)* | Full snapshot on subscribe and on every periodic update (snapshot-only; no diffs). |
| [`oraclePrices`](#oracleprices) | public | market ticker *(optional)* | Batched oracle + mark prices ([price sources](https://docs.arcus.xyz/concepts/perpetuals/prices.md#price-sources)). Global by default; pass an `id` to receive only that market. |
| [`bbo`](#bbo) | public | market | Best bid / offer (top of book). |
| [`exchangeAttributeUpdates`](#exchangeattributeupdates) | public | *(global, no `id`)* | Fee-tier table (and the legacy per-market RTH / trading-band entry variant). |
| [`marketAttributes`](#marketattributes) | public | *(global, no `id`)* | Per-market RTH / off-hours trading-band state; full snapshot on subscribe, then a per-market update on each RTH crossing and off-hours bound event. |
| [`marketUpdates`](#marketupdates) | public | *(global, no `id`)* | Stock-split and market-halt notices; pending splits and halted markets on subscribe, then one update per event. |
| [`predictedFunding`](#predictedfunding) | public | market | Predicted next-hour funding rate; a new payload each time the funder recomputes. |
| [`lendingRates`](#lendingrates) | public | *(global, no `id`)* | Exchange-wide borrow rate and cumulative borrow index; frames are pushed as the index accrues. |
| [`account`](#account) | public | Ethereum address | Snapshot of positions, balances, margin; re-snapshots every 5 s. |
| [`positions`](#positions) | public | Ethereum address | Open perpetual positions only. |
| [`spotPositions`](#spotpositions) | public | Ethereum address | Spot collateral holdings: snapshot keyed by spot asset id, then one changed holding per frame. |
| [`userFills`](#userfills) | public | Ethereum address | Snapshot then live fills. |
| [`spotFills`](#spotfills) | public | Ethereum address | Spot fills (seizure and loan-settle executions): snapshot then live fills. |
| [`settleLoanResults`](#settleloanresults) | public | Ethereum address | One `APPLIED` / `REJECTED` outcome per `POST /v1/settleLoan` request; stream-only, no snapshot. |
| [`orders`](#orders) | public | Ethereum address | Open and recently closed orders (up to 100 closed in the last 28 days in snapshot). |
| [`funding`](#funding) | public | Ethereum address | Funding payments: snapshot of up to 100 recent, then one event per payment. |
| [`accountAttributeUpdates`](#accountattributeupdates) | public | Ethereum address | Per-market leverage, account fee tier, and `leverageReject` events. |
| [`accountTransferUpdates`](#accounttransferupdates) | public | Ethereum address | Deposits, withdrawals, transfers; snapshot newest-first, then one event per processed transfer, applied or rejected. |
| [`candles`](#candles) | public | `<market>/<timeframe>` | Snapshot of up to 200 closed candles plus the current open one, then real-time updates. |

Trading operations (`placeOrder`, `cancelOrder`, …) run over the same socket as RPC calls rather than a subscription — see [WebSocket → Placing orders](https://docs.arcus.xyz/api-reference/websocket.md#placing-orders).

## l2Orderbook

Periodic full snapshots every \~200 ms.

```json theme={null}
{
  "type": "subscribe",
  "channel": "l2Orderbook",
  "id": "BTC-USD",
  "nLevels": 20
}
```

Parameters: `nLevels` (integer 1–100, default 20).

```json theme={null}
{
  "type": "channel_data",
  "channel": "l2Orderbook",
  "id": "BTC-USD",
  "contents": {
    "bids": [["64822.9", "0.85277863"]],
    "asks": [["64826.9", "0.85410755"]],
    "lastSequenceId": 62063,
    "globalSequenceId": 5367835,
    "timestamp": 1783750906942677
  }
}
```

## l2OrderbookUpdates

Initial snapshot followed by event-driven incremental updates with the same shape as `l2Orderbook`. On each delta, `timestamp` is the Unix **microseconds** when the matching engine processed the event that produced it.

```json theme={null}
{
  "type": "subscribe",
  "channel": "l2OrderbookUpdates",
  "id": "BTC-USD",
  "nLevels": 20
}
```

```json theme={null}
{
  "type": "channel_data",
  "channel": "l2OrderbookUpdates",
  "id": "BTC-USD",
  "contents": {
    "bids": [["64822.9", "0.90000000"]],
    "asks": [],
    "lastSequenceId": 62064,
    "globalSequenceId": 5367836,
    "timestamp": 1783750906951203
  }
}
```

## trades

Live public trade stream. No snapshot on subscribe.

`contents` is an **array of fills from a single taker order match** — all entries in one message share the same `takerOrderId`, `timestamp`, and `sequenceNumber`. `timestamp` is Unix **microseconds**.

```json theme={null}
{ "type": "subscribe", "channel": "trades", "id": "BTC-USD" }
```

```json theme={null}
{
  "type": "channel_data",
  "channel": "trades",
  "id": "BTC-USD",
  "contents": [
    {
      "marketDisplayName": "BTC-USD",
      "marketId": 1,
      "side": "BUY",
      "price": "94500.0",
      "size": "0.25",
      "tradeId": "18000809",
      "timestamp": 1712345679000000,
      "makerOrderId": "509198ca54b04ee8",
      "takerOrderId": "15cdceb34c4f400f",
      "makerAddress": "0xbbb...",
      "takerAddress": "0xaaa...",
      "sequenceNumber": 5001
    }
  ]
}
```

## markets

Global channel. Subscribe with no `id`.

```json theme={null}
{ "type": "subscribe", "channel": "markets" }
```

The `markets` map is keyed by `marketId` (as a string). Every emission is a full snapshot (`isSnapshot: true`); there are no partial diffs on this channel.

```json theme={null}
{
  "type": "channel_data",
  "channel": "markets",
  "contents": {
    "isSnapshot": true,
    "markets": {
      "1": {
        "marketDisplayName": "BTC-USD",
        "marketId": 1,
        "status": "ONLINE",
        "oraclePrice": "64176.9",
        "markPrice": "64337.3",
        "lastTradePrice": "64766.5",
        "fundingRate": "0.001194707932696903",
        "volume24h": "331.57",
        "trades24h": 523
      },
      "2": {
        "marketDisplayName": "ETH-USD",
        "marketId": 2,
        "status": "ONLINE",
        "oraclePrice": "1790.07",
        "markPrice": "1789.57",
        "lastTradePrice": "1788.90",
        "fundingRate": "0.0000125",
        "volume24h": "3.96",
        "trades24h": 7
      }
    }
  }
}
```

Each market entry carries the full `MarketInfo` shape (same as REST `GET /v1/markets`); the fields above are an abridged sample. See the **WebSocket** section in the sidebar for the complete schema.

## oraclePrices

Oracle and mark prices. Each update is a batch of the markets whose price changed in that epoch. For where the oracle price comes from, including the fallback source used when the primary feed goes stale, see [Price sources](https://docs.arcus.xyz/concepts/perpetuals/prices.md#price-sources).

Subscribe with no `id` for every market:

```json theme={null}
{ "type": "subscribe", "channel": "oraclePrices" }
```

Or pass a market ticker as `id` to receive only that market's entries:

```json theme={null}
{ "type": "subscribe", "channel": "oraclePrices", "id": "BTC-USD" }
```

Both forms are fed from the same publish pipeline: the `id` filters which entries reach you, not when they are published. Subscribing per market reduces bandwidth, not latency.

```json theme={null}
{
  "type": "channel_data",
  "channel": "oraclePrices",
  "id": "",
  "contents": {
    "epoch": 1783749605197180635,
    "prices": [
      {
        "marketDisplayName": "BTC-USD",
        "marketId": 1,
        "price": "64085.6",
        "markPrice": "64245.8",
        "oracleEpoch": 1783749605150000,
        "markEpochNanos": 1783749605197180635
      }
    ]
  }
}
```

`epoch` and `markEpochNanos` are Unix **nanoseconds**; `oracleEpoch` (the oracle observation time) is Unix **microseconds**. The subscribe reply (`type: subscribed`) carries the latest price for every market in scope with `epoch: 0` and without the per-row timestamps; later frames are the batches described below. `markPrice` of `"0"` means unavailable — do not fall back to `price`.

### Update cadence and measuring staleness

Frames are **change-triggered, not periodic**. A market is republished only when its oracle price or its mark price has moved since the last publish — an unchanged market may emit nothing at all. Do not rely on a periodic keepalive for any single market.

Cadence is therefore a property of market activity, not a rate this channel promises. An actively moving market republishes frequently; a quiet one can go seconds between frames while its price remains current. An upstream price source publishing sub-second for an asset does **not** imply sub-second frames here: if the aggregated price is unchanged, the dedupe gate suppresses it. Measure the cadence you actually receive rather than provisioning against an assumed rate. To cap the rate instead, subscribe with the opt-in [`throttleMs`](https://docs.arcus.xyz/api-reference/websocket#message-envelopes) field, which merges updates into at most one frame per window.

That distinction makes two separate things worth tracking, and conflating them is the most common source of false staleness alarms:

| | What it measures | What makes it grow |
| - | - | - |
| **Price age** — `now - markEpochNanos` on a frame you just received | How stale the data in that frame is | Real delay between pricing and delivery — worth alerting on |
| **Inter-frame gap** — time between consecutive frames for one market | How long that market went without a price change | Low volatility — an expected, healthy state |

**Sample age at receipt, not on a timer.** If you record "time since the last frame's `epoch`" on a fixed-interval metrics tick, you are measuring the inter-frame gap rather than staleness: a quiet market reports a growing apparent age even though every frame it sent was current when it arrived. Stamp the age as each frame arrives, and track the gap as its own separate series.

Two cautions when computing age. Compare against a clock disciplined by NTP — `markEpochNanos` is stamped server-side, so client clock offset lands directly in the result and can even produce negative ages. And alert against your own measured baseline: the pipeline's own staleness thresholds, past which a stale source is replaced by the [fallback source](https://docs.arcus.xyz/concepts/perpetuals/prices.md#price-sources) or dropped rather than published, are far looser than normal operation.

The `subscribed` acknowledgement carries a full snapshot of current prices with **`epoch: 0`** — a sentinel, not a timestamp. Do not compute an age from the snapshot frame; wait for the first `channel_data` frame.

## bbo

Best bid and offer (top of book). Its `lastSequenceId` jumps forward over suppressed depth-only updates — see [order-book sequence contiguity](https://docs.arcus.xyz/api-reference/websocket.md#order-book-sequence-contiguity) before gap-checking it. Subscribe with [`throttleMs`](https://docs.arcus.xyz/api-reference/websocket#message-envelopes) to receive at most one frame per window.

```json theme={null}
{ "type": "subscribe", "channel": "bbo", "id": "BTC-USD" }
```

```json theme={null}
{
  "type": "channel_data",
  "channel": "bbo",
  "id": "BTC-USD",
  "contents": {
    "bestBid": { "price": "64822.9", "size": "0.85277863" },
    "bestAsk": { "price": "64826.9", "size": "0.85410755" },
    "timestamp": 1783750906942677,
    "lastSequenceId": 62063,
    "globalSequenceId": 5367835
  }
}
```

## exchangeAttributeUpdates

Exchange-wide attribute state, discriminated by entry `type`. Global channel — subscribe with no `id`.

* `feeTierConfig` entries carry the full fee-tier table whenever an operator updates it. On subscribe you get a snapshot with the current table (`isSnapshot: true`).
* `marketAttributes` entries (streaming only) carry per-market Regular Trading Hours and off-hours trading-band events. Every entry names what fired in `boundEvent`: `exitRth` / `enterRth` on an RTH boundary crossing (the `exitRth` entry also carries the sealed settlement price, `sealedVwapSettlementPrice`), or `expansionZoneEntered`, `expansionZoneExited`, `tradingBoundExpanded` for a band event. Each carries a `timestamp` (Unix microseconds) and a per-market `marketSequenceNum`. **Superseded by the dedicated [`marketAttributes`](#marketattributes) channel** — prefer it for RTH / off-hours band state and events.

```json theme={null}
{ "type": "subscribe", "channel": "exchangeAttributeUpdates" }
```

```json theme={null}
{
  "type": "channel_data",
  "channel": "exchangeAttributeUpdates",
  "contents": {
    "isSnapshot": false,
    "entries": [
      {
        "type": "feeTierConfig",
        "tiers": [
          { "level": 0, "name": "Base", "volumeThreshold": 0, "makerFeePpm": 0, "takerFeePpm": 250 },
          { "level": 1, "name": "Bronze", "volumeThreshold": 5000000000000000, "makerFeePpm": 0, "takerFeePpm": 200 }
        ]
      }
    ]
  }
}
```

The tier values above are illustrative, not the current schedule — read the live table from the subscribe snapshot or [`GET /v1/feetiers`](https://docs.arcus.xyz/api-reference/public/get-fee-tier-table).

The equivalent REST reads are [`GET /v1/feetiers`](https://docs.arcus.xyz/api-reference/public/get-fee-tier-table) and [`GET /v1/markets`](https://docs.arcus.xyz/api-reference/public/get-markets).

## marketAttributes

Per-market Regular Trading Hours (RTH) and off-hours trading-band **state** for every online market. Global channel — subscribe with no `id`; all subscribers get the same stream. Supersedes the `marketAttributes` entry variant on [`exchangeAttributeUpdates`](#exchangeattributeupdates).

Every entry — snapshot and streaming alike — is the market's complete current attribute block: `marketId`, `marketDisplayName`, `offHoursInitialMarginFraction`, `isOutsideRth`, `currentSettlementPrice`, both trading-band edges (`upperTradingBound` / `lowerTradingBound`) and their next-level edges (`nextUpperTradingBound` / `nextLowerTradingBound`), and per-side expansion-zone state (`isUpperInExpansionZone` / `isLowerInExpansionZone` plus the `…ZoneEnteredAt` / `…ExpectedExpansionAt` clocks). Fields that don't currently apply are `null`, never omitted; field semantics match [`GET /v1/markets`](https://docs.arcus.xyz/api-reference/public/get-markets). 24/7 crypto markets are included with `isOutsideRth: false` and every band field `null`, and never produce streaming updates.

On subscribe you get one full block per online market (`isSnapshot: true`) — a complete bootstrap, no REST read needed. Streaming updates (`isSnapshot: false`) each carry one market's full post-event block on an RTH boundary crossing (the settlement anchor seals on the off-hours exit) or an off-hours bound event — replace your local entry for that `marketId` wholesale. Streaming entries add a `timestamp` (Unix microseconds), a per-market `marketSequenceNum`, and **`boundEvent`, which is present on every streaming entry**: `exitRth` / `enterRth` on an RTH boundary crossing, otherwise `expansionZoneEntered`, `expansionZoneExited`, or `tradingBoundExpanded`. `boundSide` (`upper` / `lower`) names the band edge on bound events and is `null` on RTH crossings and on snapshot entries.

```json theme={null}
{ "type": "subscribe", "channel": "marketAttributes" }
```

Subscribe snapshot — one entry per online market (off-hours market shown):

```json theme={null}
{
  "type": "subscribed",
  "channel": "marketAttributes",
  "contents": {
    "isSnapshot": true,
    "entries": [
      {
        "marketId": 9,
        "marketDisplayName": "AMD-USD",
        "offHoursInitialMarginFraction": "0.15",
        "isOutsideRth": true,
        "currentSettlementPrice": "432.01",
        "upperTradingBound": "453.61",
        "lowerTradingBound": "410.41",
        "nextUpperTradingBound": "475.21",
        "nextLowerTradingBound": "388.81",
        "isUpperInExpansionZone": true,
        "isLowerInExpansionZone": false,
        "upperZoneEnteredAt": 1785370771,
        "upperExpectedExpansionAt": 1785374371,
        "lowerZoneEnteredAt": null,
        "lowerExpectedExpansionAt": null,
        "boundSide": null
      }
    ]
  }
}
```

Streaming update at the RTH open (`boundEvent: "enterRth"`) — the market re-enters regular hours and every band field clears to `null`:

```json theme={null}
{
  "type": "channel_data",
  "channel": "marketAttributes",
  "contents": {
    "isSnapshot": false,
    "entries": [
      {
        "marketId": 9,
        "marketDisplayName": "AMD-USD",
        "offHoursInitialMarginFraction": "0.15",
        "isOutsideRth": false,
        "currentSettlementPrice": null,
        "upperTradingBound": null,
        "lowerTradingBound": null,
        "nextUpperTradingBound": null,
        "nextLowerTradingBound": null,
        "isUpperInExpansionZone": null,
        "isLowerInExpansionZone": null,
        "upperZoneEnteredAt": null,
        "upperExpectedExpansionAt": null,
        "lowerZoneEnteredAt": null,
        "lowerExpectedExpansionAt": null,
        "boundEvent": "enterRth",
        "boundSide": null,
        "timestamp": 1785398400073277,
        "marketSequenceNum": 3179316
      }
    ]
  }
}
```

The equivalent REST read is [`GET /v1/markets`](https://docs.arcus.xyz/api-reference/public/get-markets).

## marketUpdates

Global channel (no `id`) for each market's stock-split lifecycle: `MarketUpdateSplitUpcoming`, `MarketUpdateSplitCancelled`, `MarketUpdateStateChange` (`state` `HALTED` / `RESUMED`) and `MarketUpdateSplitEffective`. The `subscribed` reply lists every pending split and every market still halted; each later event arrives as one update. For the full sequence with example frames, see [Stock splits](https://docs.arcus.xyz/concepts/perpetuals/stock-splits.md#following-a-split-over-websocket).

```json theme={null}
{ "type": "subscribe", "channel": "marketUpdates" }
```

## predictedFunding

Predicted next-hour funding rate for a single market. A new payload is delivered each time the prediction is recomputed: `rate1h` is the predicted 1-hour rate, `sampleCount` the number of premium samples behind it, and `timestampMs` when it was computed (Unix **milliseconds**).

The initial response on subscribe carries the latest cached prediction; `contents` is empty when no prediction has been published yet. Unlike most channels, payloads are not wrapped in an `isSnapshot` envelope.

```json theme={null}
{ "type": "subscribe", "channel": "predictedFunding", "id": "BTC-USD" }
```

```json theme={null}
{
  "type": "channel_data",
  "channel": "predictedFunding",
  "id": "BTC-USD",
  "contents": {
    "market": "BTC-USD",
    "rate1h": "0.0000125",
    "sampleCount": 60,
    "timestampMs": 1712345678000
  }
}
```

## lendingRates

Global channel (no `id`) that streams the exchange-wide borrow rate and cumulative borrow index — the lending analog of [`oraclePrices`](#oracleprices). Frames are pushed as the borrow index accrues, carrying the current annual borrow rate (`ratePpm`, parts-per-million per year: `80000` = 8%), the global borrow index (`borrowIndex`, a stringified integer at 1e12 scale), and the exchange-wide lending utilization the rate was evaluated at (`utilizationPpm`, parts-per-million: `1000000` = 100%; `null` on a tick that predates the field).

A borrower's live accrued interest = `loanBalance` × (`borrowIndex` − the account's `lastBorrowIndex`) / 1e12, using the [`account`](#account) channel's lending fields. Settled interest is on REST [`GET /v1/interest`](https://docs.arcus.xyz/api-reference/public/get-interest-payments).

```json theme={null}
{ "type": "subscribe", "channel": "lendingRates" }
```

The `subscribed` reply replays the last observed tick with `isSnapshot: true` (empty `contents` — `{}` — when no tick has been observed since server start); each update then arrives as `channel_data`:

```json theme={null}
{
  "type": "channel_data",
  "channel": "lendingRates",
  "contents": {
    "isSnapshot": false,
    "ratePpm": 50000,
    "borrowIndex": "4600000000",
    "utilizationPpm": 85000,
    "timestamp": 1780414403123456800,
    "globalSequenceId": 9600000123
  }
}
```

## account

Account state snapshot and updates (positions, balances, margin). Re-snapshots every 5 seconds.

```json theme={null}
{ "type": "subscribe", "channel": "account", "id": "0xAbCd...1234" }
```

The `subscribed` reply carries the full snapshot in `contents`, and the same shape is re-broadcast as `channel_data` every 5 seconds with `isSnapshot: true`:

```json theme={null}
{
  "type": "subscribed",
  "channel": "account",
  "id": "0xabcd...1234",
  "accountIndex": 0,
  "contents": {
    "isSnapshot": true,
    "lastSequenceId": 7,
    "address": "0xabcd...1234",
    "accountIndex": 0,
    "netQuoteBalance": "10000.00",
    "freeCollateral": "9500.00",
    "accountEquity": "10250.00",
    "netDeposits": "10000.00",
    "positions": {
      "1": { "marketId": 1, "marketDisplayName": "BTC-USD", "side": "LONG", "size": "0.1", "averageEntryPrice": "64500.00" }
    }
  }
}
```

`positions` is an object keyed by `marketId` (see [`positions`](#positions) below) — `{}` when flat. Field semantics match REST [`GET /v1/account`](https://docs.arcus.xyz/api-reference/public/get-account), but two names differ: `accountEquity` here is REST's `equity`, and `lastSequenceId` is REST's `sequenceNumber` (REST-only `pendingDeposits` / `pendingWithdrawals` are not included). `accountEquity` and `freeCollateral` are recomputed against live mark prices on every 5-second re-snapshot. `netDeposits` and cumulative funding are served from a short-lived cache: `netDeposits` updates on every transfer, and cumulative funding can trail by one payment for up to about 15 seconds after each hourly funding payment.

An account the engine has never touched (no deposit or order yet — registering an API key does not count) gets a sentinel snapshot instead of misleading zeros: `{ "isSnapshot": true, "noActivity": true, "error": "this account has no activity yet", "address": "0x…", "accountIndex": 0 }`. The subscription stays open, and real snapshots begin once the account's first event lands — the same lifecycle state REST reports as `404` on [`GET /v1/account`](https://docs.arcus.xyz/api-reference/public/get-account).

Streaming updates are per-event and carry a different, order-centric shape:

```json theme={null}
{
  "type": "channel_data",
  "channel": "account",
  "id": "0xabcd...1234",
  "accountIndex": 0,
  "contents": {
    "type": "PLACED",
    "netQuoteBalance": "10000.00"
  }
}
```

Streaming `contents.type` is one of `PLACED`, `CANCELED`, `MARGIN_CANCELED`, `REJECTED`, `TPSL_PLACED`, `TPSL_CANCELED`, `TPSL_TRIGGERED`, `LIQUIDATION`, `ADL`, `BORROWER_LIQUIDATION` (the account entering wind-down: orders canceled, collateral frozen against the outstanding claim), and `ESTATE_RELEASED` (wind-down complete). `netQuoteBalance` is stamped on every frame; `avgFillPrice` is present whenever the order has any filled quantity.

Accounts that borrow or hold spot collateral carry a lending section in the snapshot (`loanBalance`, `unsettledInterest`, `marginState`, `borrowHeadroom`, `spotPositions`) and lending fields on streaming updates (`loanBalance`, `lastBorrowIndex`, `inWindDown`). All of them are omitted for an account with no loan history and no spot holdings.

## positions

Open perpetual positions only — spot collateral holdings stream on the [`spotPositions`](#spotpositions) channel.

```json theme={null}
{ "type": "subscribe", "channel": "positions", "id": "0xAbCd...1234" }
```

In the snapshot (the `subscribed` reply), `positions` is an **object keyed by `marketId`** — stringified integers, e.g. `"1"` = BTC-USD — **not an array**. The map has the same shape as `positions` in REST [`GET /v1/positions`](https://docs.arcus.xyz/api-reference/public/get-positions) and in the [`account`](#account) snapshot; the snapshot does not carry REST's `total` item count. An account with no open positions gets `"positions": {}` (an empty object).

```json theme={null}
{
  "type": "subscribed",
  "channel": "positions",
  "id": "0xabcd...1234",
  "accountIndex": 0,
  "contents": {
    "isSnapshot": true,
    "lastSequenceId": 7,
    "address": "0xabcd...1234",
    "accountIndex": 0,
    "positions": {
      "1": { "marketId": 1, "marketDisplayName": "BTC-USD", "side": "LONG", "size": "0.1", "averageEntryPrice": "64500.00" }
    }
  }
}
```

Streaming updates carry **one position per frame** (`isSnapshot: false`): `contents` holds `lastSequenceId` and a `positions` **array with a single row**, not the keyed object. Each row carries its own `sequenceNumber`; `cumulativeFunding` is omitted on streaming rows (read it from the snapshot, where it can trail by one funding payment for up to about 15 seconds after each hourly payment). A frame that confirms an [`adjustIsolatedMargin`](https://docs.arcus.xyz/api-reference/exchange/add-or-remove-margin-on-an-isolated-mode-position) request also carries that request's `requestId`. When a position closes it is emitted with `side: "FLAT"` and zeroed financials.

```json theme={null}
{
  "type": "channel_data",
  "channel": "positions",
  "id": "0xabcd...1234",
  "accountIndex": 0,
  "market": "BTC-USD",
  "contents": {
    "isSnapshot": false,
    "lastSequenceId": 8,
    "positions": [
      { "marketId": 1, "marketDisplayName": "BTC-USD", "side": "LONG", "size": "0.15", "averageEntryPrice": "64620.00", "marginMode": "CROSS", "sequenceNumber": 8 }
    ]
  }
}
```

## spotPositions

Spot collateral holdings for a single account, on a dedicated channel — follow collateral without subscribing to the full perp [`positions`](#positions) stream. The equivalent REST read is [`GET /v1/spotPositions`](https://docs.arcus.xyz/api-reference/public/get-spot-positions).

```json theme={null}
{ "type": "subscribe", "channel": "spotPositions", "id": "0xAbCd...1234" }
```

The snapshot (the `subscribed` reply) carries `spotPositions` as an **object keyed by spot asset id** (its own namespace, not a perp `marketId`), omitted when empty. Each entry carries `spotAssetId`, `spotAssetDisplayName` (e.g. `SPY-USD-SPOT`), `size` (in the asset's own units), `value`, and `oraclePrice`. Like the `positions` snapshot, it does not carry REST's `total` item count.

```json theme={null}
{
  "type": "subscribed",
  "channel": "spotPositions",
  "id": "0xAbCd1234",
  "contents": {
    "isSnapshot": true,
    "lastSequenceId": 12,
    "address": "0xAbCd1234",
    "accountIndex": 0,
    "spotPositions": {
      "1": { "spotAssetId": 1, "spotAssetDisplayName": "SPY-USD-SPOT", "size": "10", "value": "4200.00", "oraclePrice": "420.00" }
    }
  }
}
```

Streaming updates carry **one changed holding per frame** in a `spotPositions` array (`isSnapshot: false`): the post-event `size` in asset units (`"0"` closes the holding — remove it from local state), the event valuation `price`, and a `reason` — one of `DEPOSIT`, `WITHDRAWAL`, `SEIZURE`, `RELEASE`, `TRANSFER`, `UNKNOWN`. Merge by `spotAssetId`.

```json theme={null}
{
  "type": "channel_data",
  "channel": "spotPositions",
  "id": "0xAbCd1234",
  "contents": {
    "isSnapshot": false,
    "spotPositions": [
      { "address": "0xAbCd1234", "accountIndex": 0, "spotAssetId": 1, "spotAssetDisplayName": "SPY-USD-SPOT", "size": "10", "price": "420.00", "reason": "DEPOSIT" }
    ]
  }
}
```

## userFills

Per-user fill stream. Snapshot on subscribe, then live updates. Both wrap their rows in a `fills` array: the snapshot (`isSnapshot: true`) carries up to `nFills` rows newest-first, and each streaming frame (`isSnapshot: false`) carries the new fill. Field semantics match REST [`GET /v1/fills`](https://docs.arcus.xyz/api-reference/public/get-fills): `price` and `size` are this fill's execution price and quantity, while `originalSize` / `remainingSize` describe the order it belongs to.

```json theme={null}
{ "type": "subscribe", "channel": "userFills", "id": "0xAbCd...1234" }
```

```json theme={null}
{
  "type": "channel_data",
  "channel": "userFills",
  "id": "0xabcd...1234",
  "accountIndex": 0,
  "market": "BTC-USD",
  "contents": {
    "isSnapshot": false,
    "fills": [
      {
        "tradeId": "18001653",
        "orderId": "78ca798fe0ba44f6",
        "marketId": 1,
        "marketDisplayName": "BTC-USD",
        "clientId": "c1",
        "side": "SELL",
        "originalSize": "0.01",
        "size": "0.01",
        "price": "50000.0",
        "fee": "0",
        "closedPnl": "0",
        "role": "MAKER",
        "remainingSize": "0",
        "positionEffect": "OPEN_SHORT",
        "createdAt": 1712345679000000,
        "sequenceNumber": 5001
      }
    ]
  }
}
```

Parameters: `nFills` (optional) caps how many fills the snapshot includes — default **500**, and 500 is also the maximum. A larger value is clamped, not rejected.

### Forced closures appear on the closed account's own stream

**Every event that moves your position produces a fill row on your own `userFills`** — including a position closed out from under you. If your account is liquidated or auto-deleveraged, you receive your own forced-close leg here and as a row in [`GET /v1/fills`](https://docs.arcus.xyz/api-reference/public/get-fills); it is not delivered only to the counterparty. A position can therefore never move without a corresponding fill you can observe, which is what makes the fill stream sufficient on its own to reconstruct net position.

The forced leg carries a `liquidation` object — `method` (`LIQUIDATION` or `ADL`) and `liquidatedUser`. Note that `liquidatedUser` is **always the account that owns the row**, not a counterparty: on your own row it is your own account. Use the presence of the `liquidation` object, not its value, to classify a fill as forced. The voluntary side of the same match (a resting maker that got hit) receives an ordinary fill row with no marker. The marker is persisted, so snapshots and REST return it too.

### Recovering from a disconnect

The subscribe snapshot and a REST backfill together close any gap, provided you page:

* The snapshot replays the most recent **500** fills (`nFills`), newest-first.
* [`GET /v1/fills`](https://docs.arcus.xyz/api-reference/public/get-fills) returns up to **1,000** rows per request, newest-first. `limit` above 1,000 is silently clamped rather than rejected.
* Fill history is **not** trimmed to a retention window — there is no TTL on the store. The 1,000 rows are a per-request cap, not the depth available.

Because history is not expired, an outage of any length is fully recoverable: page backwards with `from` and `to` (epoch **microseconds**, matching `createdAt`): set `from` to the newest `createdAt` you already hold and each request's `to` to the oldest `createdAt` you have so far. Omitting `from` limits a request to the 30 days before `to`. Deduplicate on `tradeId`, which is stable across the snapshot and REST views — expect the snapshot and your backfill to overlap rather than abut exactly.

## spotFills

Per-user spot fill stream — the seizure and loan-settle executions of the lending system. Spot has no order book, so these are the only spot executions and there is no maker/taker role or fee. Snapshot of recent spot fills on subscribe, then live updates; subscribe with `snapshot: false` to skip the snapshot and receive only live fills. Use REST [`GET /v1/spotFills`](https://docs.arcus.xyz/api-reference/public/get-spot-fills) for history. For settleLoan request outcomes, including rejections (which produce no fill), see [`settleLoanResults`](#settleloanresults).

```json theme={null}
{ "type": "subscribe", "channel": "spotFills", "id": "0xAbCd...1234" }
```

Every frame — snapshot and update — carries a `spotFills` array (a live frame holds the new fill):

```json theme={null}
{
  "type": "channel_data",
  "channel": "spotFills",
  "id": "0xAbCd1234",
  "contents": {
    "isSnapshot": false,
    "spotFills": [
      {
        "spotAssetId": 1,
        "spotAssetDisplayName": "SPY-USD-SPOT",
        "side": "SELL",
        "size": "10",
        "price": "420.00",
        "quoteAmount": "4200.00",
        "reason": "LOAN_SETTLE",
        "createdAt": 1726660000000000
      }
    ]
  }
}
```

## settleLoanResults

Per-account outcomes of [`POST /v1/settleLoan`](https://docs.arcus.xyz/api-reference/exchange/sell-spot-collateral-to-settle-the-accounts-loan) requests — one frame per request, `APPLIED` or `REJECTED`. Each frame mirrors the REST response body and carries the `requestId` from the REST `202` ACK, so you can correlate the two. It is the only WebSocket surface for a rejected settlement, which moves no cash and produces no fill: on `REJECTED` the execution fields read `"0"`, `newLoanBalance` echoes the unchanged loan, and `rejectReason` is set. An applied settlement also appears on [`spotFills`](#spotfills) as a `LOAN_SETTLE` fill, but only this channel carries `repaidAmount` and `newLoanBalance`. Stream-only: there is no snapshot, the subscribe ack carries empty contents (`{}`), and frames flow from the moment you subscribe. Optional `accountIndex` (0–9) selects the subaccount, as on the other account channels.

```json theme={null}
{ "type": "subscribe", "channel": "settleLoanResults", "id": "0xAbCd...1234" }
```

## orders

Open and recently closed orders. The snapshot lists every open order, regardless of age, plus up to 100 orders closed in the last 28 days; use [`GET /v1/orders`](https://docs.arcus.xyz/api-reference/public/get-order-history) with an explicit `from` for older history.

```json theme={null}
{ "type": "subscribe", "channel": "orders", "id": "0xAbCd...1234", "nRecentClosed": 100 }
```

Parameters: `nRecentClosed` (optional) caps how many closed orders the snapshot includes (default 100). Open orders are never capped. `market` (optional) scopes both snapshot arrays and the live stream to one market — see [optional subscribe fields](https://docs.arcus.xyz/api-reference/websocket.md#message-envelopes).

```json theme={null}
{ "type": "subscribe", "channel": "orders", "id": "0xAbCd...1234", "market": "BTC-USD" }
```

To reconcile without re-subscribing, send a `get` request of type `orders` on the same socket (envelope and `id` rules in [WebSocket → Message envelopes](https://docs.arcus.xyz/api-reference/websocket.md#message-envelopes)). Its `result` carries `openOrders` / `recentClosedOrders` arrays of the same shape as the snapshot (`recentClosedOrders` covers the last 30 days unless you pass `from`); `payload` takes `address`, `accountIndex`, and optionally `market`, `from`, `to`, `limit`, and `nRecentClosed`:

```json theme={null}
{ "type": "get", "id": 3, "request": { "type": "orders", "payload": { "address": "0xAbCd...1234", "accountIndex": 0, "market": "BTC-USD" } } }
```

The snapshot (the `subscribed` reply) carries **two separate arrays**:

```json theme={null}
{
  "type": "subscribed",
  "channel": "orders",
  "id": "0xabcd...1234",
  "accountIndex": 0,
  "contents": {
    "isSnapshot": true,
    "openOrders": [
      { "orderId": "ord-1", "clientId": "c1", "marketId": 1, "marketDisplayName": "BTC-USD", "side": "BUY", "status": "OPEN", "price": "50000.00", "originalSize": "1.0", "remainingSize": "0.5" }
    ],
    "recentClosedOrders": [
      { "orderId": "ord-0", "marketId": 1, "marketDisplayName": "BTC-USD", "side": "SELL", "status": "FILLED", "price": "50500.00", "originalSize": "0.2", "remainingSize": "0.0" }
    ]
  }
}
```

Keep the two arrays separate in your order state. `recentClosedOrders` replays up to `nRecentClosed` **terminal** orders on every subscribe — concatenating it with `openOrders` into a single working-orders list resurrects closed orders as live on every reconnect.

Streaming updates deliver one order event per frame:

```json theme={null}
{
  "type": "channel_data",
  "channel": "orders",
  "id": "0xabcd...1234",
  "accountIndex": 0,
  "contents": {
    "orderId": "ord-1",
    "clientId": "c1",
    "marketId": 1,
    "marketDisplayName": "BTC-USD",
    "side": "BUY",
    "status": "OPEN",
    "price": "50000.00",
    "originalSize": "1.0",
    "remainingSize": "0.5",
    "createdAt": 1712345678000000,
    "updatedAt": 1712345679000000,
    "sequenceNumber": 5001
  }
}
```

`createdAt` / `updatedAt` are Unix **microseconds**.

Streaming `status` names the event that produced the frame: `OPEN` (placed, modified, or partially filled and still resting), `FILLED`, `CANCELED` (including an `IOC` that filled only partly, and the first of the two updates a modify produces — see [Modifying orders](https://docs.arcus.xyz/concepts/perpetuals/order-types.md#modifying-orders-and-queue-priority)), `MARGIN_CANCELED`, `REJECTED`, `TPSL_PLACED`, `TPSL_TRIGGERED`, `TPSL_CANCELED`, `LIQUIDATED` and `ADL` (forced closures). Snapshot rows report the stored status, with the same values as REST [`GET /v1/orders`](https://docs.arcus.xyz/api-reference/public/get-order-history) (`OPEN`, `UNTRIGGERED`, `FILLED`, `CANCELED`, `REJECTED`, `LIQUIDATED`, `ADL`). Resting orders submitted as `GTT` read back with `timeInForce: "GTC"`; treat the two as equivalent.

`REJECTED` events carry a machine-readable `rejectionReason` (see the `RejectionReason` enum); this channel is the source of truth for rejections. A resting order past its `goodTilTime` is removed only when incoming matching reaches it, and then arrives as `REJECTED` with `rejectionReason: EXPIRED`; an order already expired when placed ends `CANCELED`, and an untriggered TP/SL that expires ends `TPSL_CANCELED`.

## funding

Funding-payment stream for an account. The snapshot on subscribe contains up to 100 of the most recent funding payments from the last 30 days; for older history query [`GET /v1/funding`](https://docs.arcus.xyz/api-reference/public/get-funding-payments) with an explicit `from`. Live updates deliver one event per (market, account) at each funding payment time.

Sign convention on `payment`: **positive = received, negative = paid**. `time` is the Unix-**microsecond** funding payment time.

```json theme={null}
{ "type": "subscribe", "channel": "funding", "id": "0xAbCd...1234" }
```

```json theme={null}
{
  "type": "channel_data",
  "channel": "funding",
  "id": "0xabcd...1234",
  "accountIndex": 0,
  "contents": {
    "marketId": 1,
    "marketDisplayName": "BTC-USD",
    "fundingRate": "0.00001234",
    "size": "0.5",
    "payment": "-3.21",
    "time": 1700003600000000
  }
}
```

## accountAttributeUpdates

Per-account attribute state, discriminated by entry `type`:

* `leverage` entries carry effective leverage per market and that market's margin mode (`marginMode`: `CROSS` or `ISOLATED`, mirrored by the boolean `isolated`).
* `feeTier` entries carry account-level fee tier state.
* `leverageReject` entries (streaming only) report a `setLeverage` request the engine refused — the `REJECTED` half of the setLeverage lifecycle, carrying `rejectReason` (`UNDERCOLLATERALIZED`, `INVALID_LEVERAGE`, `UNKNOWN_MARKET`, or `HAS_OPEN_POSITION`) and the originating `requestId`; an applied change arrives as a `leverage` entry instead.

The snapshot returns one `leverage` entry per market plus, when available, one `feeTier` entry; streaming delivers one entry per changed attribute.

```json theme={null}
{ "type": "subscribe", "channel": "accountAttributeUpdates", "id": "0xAbCd...1234" }
```

```json theme={null}
{
  "type": "channel_data",
  "channel": "accountAttributeUpdates",
  "id": "0xabcd...1234",
  "accountIndex": 0,
  "contents": {
    "isSnapshot": false,
    "entries": [
      { "type": "leverage", "marketId": 1, "marketDisplayName": "BTC-USD", "leverage": 10, "isolated": false, "marginMode": "CROSS" }
    ]
  }
}
```

## accountTransferUpdates

Account transfer events — deposits, withdrawals, and transfers between accounts (`type`, for example `DEPOSIT`, `WITHDRAWAL`, or `INTERNAL_TRANSFER`; see the channel schema for every value). The snapshot on subscribe contains the most recent events newest-first (`isSnapshot: true`); each streaming update carries a single event (`isSnapshot: false`) as it is processed by the engine.

Amounts and balances are human-readable decimal strings in quote currency; `globalSequenceId` gives strict ordering across all engine events. `sourceAccountId` / `destinationAccountId` name where the funds came from and went to — internal account ids (not Ethereum addresses), or the chain on a deposit or withdrawal. The equivalent REST read is [`GET /v1/accountTransferUpdates`](https://docs.arcus.xyz/api-reference/public/get-account-transfer-updates).

Every event carries `status`: `APPLIED`, or `REJECTED` with the reason code in `rejectReason` (for example `INSUFFICIENT_COLLATERAL`). A rejected operation moved no funds, so its `netQuoteBalance` and `accountSequenceNum` are the pre-operation values. Rejections stream only to the account that initiated the operation.

```json theme={null}
{ "type": "subscribe", "channel": "accountTransferUpdates", "id": "0xAbCd...1234" }
```

```json theme={null}
{
  "type": "channel_data",
  "channel": "accountTransferUpdates",
  "id": "0xabcd...1234",
  "accountIndex": 0,
  "contents": {
    "isSnapshot": false,
    "accountTransferEvents": [
      {
        "type": "WITHDRAWAL",
        "eventId": "wdl-xyz789",
        "status": "APPLIED",
        "amount": "250.00",
        "netQuoteBalance": "984.56",
        "globalSequenceId": 9600000002,
        "accountSequenceNum": 43,
        "sourceAccountId": "AbCdEf0123456789AbCdEf0123GhIj",
        "destinationAccountId": "ROBINHOOD_CHAIN"
      }
    ]
  }
}
```

## candles

OHLCV candlesticks. The snapshot holds up to 200 closed candles plus the current, still-open candle (so up to 201 entries, newest first), followed by real-time updates. Subscription `id` is `<market>/<timeframe>`.

Available timeframes: `1m`, `3m`, `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `8h`, `12h`, `1d`, `3d`, `1w`.

```json theme={null}
{ "type": "subscribe", "channel": "candles", "id": "BTC-USD/1m" }
```

```json theme={null}
{
  "type": "channel_data",
  "channel": "candles",
  "id": "BTC-USD/1m",
  "contents": {
    "marketDisplayName": "BTC-USD",
    "marketId": 1,
    "timeframe": "1m",
    "openTime": 1712345640000000,
    "open": "94500.00",
    "high": "94510.00",
    "low": "94490.00",
    "close": "94505.00",
    "volume": "12.34",
    "takerBuyVolume": "7.50",
    "notionalVolume": "1166130.00",
    "takerBuyNotionalVolume": "708750.00",
    "tradeCount": 42,
    "isFinal": false
  }
}
```


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.