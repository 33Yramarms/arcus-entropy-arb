> ## Documentation Index
> Fetch the complete documentation index at: https://docs.arcus.xyz/llms.txt
> Use this file to discover all available pages before exploring further.

# WebSocket

> Real-time market data and order routing

Connect to `wss://api.arcus.xyz/v1/ws` on mainnet or `wss://api.testnet.arcus.xyz/v1/ws` on testnet. The connection multiplexes channel subscriptions and request/response (RPC) calls.

> [!NOTE]
>
> A client that cannot drain its socket promptly falls behind and can be disconnected. See [Latency → Receiving market data](https://docs.arcus.xyz/guides/latency.md#receiving-market-data) for recommended client resources.

## Compression (optional)

Mainnet only: testnet does not support compression yet and ignores the parameter.

To receive compressed frames, append `?compression=1` to the connection URL (`wss://api.arcus.xyz/v1/ws?compression=1`). The connection then uses permessage-deflate, provided your client offers it in the handshake. Browsers and mainstream WebSocket libraries offer it and inflate frames before handing them to you, so message contents are identical with or without compression. Without the parameter, the server may still compress some connections whose client offers the extension; pass `?compression=0` to opt out, which is always honoured.

To confirm it is on, check the handshake response for `Sec-WebSocket-Extensions: permessage-deflate; server_no_context_takeover; client_no_context_takeover`. Each message is compressed on its own, with no context carried over between messages in either direction. Without that header the connection is uncompressed. Small frames may be sent uncompressed even on a compressed connection.

```python Python (websockets) theme={null}
import websockets

async with websockets.connect(
    "wss://api.arcus.xyz/v1/ws?compression=1", compression="deflate"
) as ws:
    print(ws.response.headers.get("Sec-WebSocket-Extensions"))
```

```javascript Node.js (ws) theme={null}
import WebSocket from "ws";

const ws = new WebSocket("wss://api.arcus.xyz/v1/ws?compression=1", {
  perMessageDeflate: true,
});
ws.on("upgrade", (res) => console.log(res.headers["sec-websocket-extensions"]));
```

```javascript Browser theme={null}
// The browser offers permessage-deflate automatically.
const ws = new WebSocket("wss://api.arcus.xyz/v1/ws?compression=1");
ws.onopen = () => console.log(ws.extensions); // starts with "permessage-deflate" when on
```

## Message envelopes

**Subscribe / unsubscribe:**

```json theme={null}
{ "type": "subscribe",   "channel": "<channel_name>", "id": "<subscription_id>" }
{ "type": "unsubscribe", "channel": "<channel_name>", "id": "<subscription_id>" }
```

The server replies with `{ "type": "subscribed", ... }` whose `contents` **is the initial snapshot** for channels that deliver one — there is no separate bare acknowledgement frame. (A connection-health check should therefore count channels that delivered `contents`, not empty acks.) It then streams `{ "type": "channel_data", ... }` updates. Each update carries the `channel`, the subscription `id` (the market, or the lowercase master address on account-scoped channels; absent on global channels), and a `contents` payload. Timestamps are inside `contents` (e.g. `timestamp`, `epoch`, `markEpochNanos`); there is no top-level publish timestamp.

Some frames carry extra envelope fields so a connection holding several views can tell them apart:

* `accountIndex` — on **every** frame of an account-scoped channel (`subscribed`, `unsubscribed`, `degraded`, and `channel_data`), including when it is `0`. `id` is the master address and is identical across subaccounts, so demultiplex on `id` + `accountIndex`.
* `market` — on `positions`, `orders`, and `userFills`. On `channel_data` it is the ticker of the market the frame is about (present even on unfiltered subscriptions); on `subscribed` / `unsubscribed` it echoes the `market` filter, if any.
* `sigFigs` / `roundStep` — on `l2Orderbook` frames of an aggregated view (see the subscribe fields below).

**Degraded subscribe.** If the initial snapshot cannot be served (too stale to join the live stream, or the read failed), the server sends `{ "type": "degraded", "channel": …, "id": …, "reason": "snapshot_stale" | "snapshot_unavailable", "retryAfterMs": … }` instead of `subscribed` (plus `accountIndex` on account-scoped channels). The subscription stays pending and the server keeps retrying; it completes with a normal `subscribed` frame once a snapshot is available. No client action is needed — show the stream as stale until `subscribed` arrives.

Optional subscribe fields:

| Field | Applies to | Meaning |
| - | - | - |
| `snapshot` | channels that stream deltas | `false` suppresses the initial snapshot so only live updates flow. Default `true`. Ignored (always `true`) on snapshot-only channels such as `markets`. |
| `nLevels` | `l2Orderbook`, `l2OrderbookUpdates` | Price levels per side, 1–100 (default 20). |
| `sigFigs` | `l2Orderbook` | Aggregate price levels to `2`–`5` significant figures (bids round down, asks round up, sizes in a bucket are summed); omit for full precision. Applied before `nLevels`. |
| `roundStep` | `l2Orderbook` | `1`, `2`, or `5` — refines the finest bucket; only takes effect with `sigFigs: 5`. |
| `accountIndex` | account-scoped channels (`account`, `positions`, `spotPositions`, `orders`, `userFills`, `spotFills`, `funding`, `accountAttributeUpdates`, `accountTransferUpdates`, `settleLoanResults`) | Subaccount of the address in `id`, `0`–`9` (default `0`). Each subaccount is a separate subscription, so one connection can hold several. Sending it on any other channel, or outside `0`–`9`, is an error. |
| `nRecentClosed` | `orders` | Closed orders included in the snapshot (default 100). |
| `nFills` | `userFills` | Fills included in the snapshot (default 500, max 500). |
| `market` | `orders`, `positions`, `userFills` | Restricts the snapshot and the live stream to one market (ticker such as `BTC-USD`, or numeric market ID). Omit for all markets. An unknown market, or `market` on any other channel, is rejected with an `error` frame rather than ignored. A filtered and an unfiltered subscription to the same address can coexist on one connection; pass the same `market` on `unsubscribe` to remove a filtered one. |
| `throttleMs` | `bbo`, `oraclePrices` | Opt-in cadence: `100`, `250`, `500`, `1000`, or `2000`. Delivers at most one frame per window (`bbo`: latest top of book; `oraclePrices`: latest entry per market merged across the window); the first frame after an idle period is sent immediately. Omit for the unthrottled stream. Any other value, or the field on any other channel, is rejected with an `error` frame (e.g. `channel 'trades' does not support 'throttleMs'; supported: bbo, oraclePrices`). Echoed on the `subscribed` ack; not part of the subscription's identity. A throttled stream is not sequence-contiguous, so do not gap-check it. |

`accountIndex`, `market`, and `sigFigs` / `roundStep` are part of the subscription's identity: an `unsubscribe` must repeat the same values to remove that view. An `unsubscribe` without `accountIndex` removes only subaccount `0`; one without `market` removes only the unfiltered view. One connection may hold several `l2Orderbook` views of the same market as long as each uses a different `sigFigs` / `roundStep` pair.

**Request / response:** every `post` and `get` message must include a numeric `id` chosen by the client. The server echoes the same `id` in its response. IDs must be **strictly increasing per connection**: a `get` or `post` whose `id` is not greater than the previous one on that socket is rejected with an `error` frame. That `error` frame does **not** echo the `id`, so a client that matches replies by `id` will see the request as unanswered rather than failed. A counter that starts at 1 for each new connection satisfies this.

```json theme={null}
{
  "type": "get",
  "id": 2,
  "request": {
    "type": "l2orderbook",
    "payload": { "market": "BTC-USD" }
  }
}
```

See [Authentication](https://docs.arcus.xyz/api-reference/authentication.md) for the signing rules that apply to order methods.

## What authorizes a subscription

Nothing. **Subscribing is never authenticated** — not even on the account-scoped channels (`account`, `positions`, `orders`, `userFills`). A `subscribe` frame carries no signature, the socket is not bound to an API key, and there is no `authenticate` step to miss: any connection may subscribe to **any** address and will receive that address's balances, positions, open orders, and fills.

This is deliberate, not an oversight. These channels are the streaming form of the account-scoped REST reads (`GET /v1/fills`, `/v1/orders`, `/v1/positions`, `/v1/account`), which are themselves public and take `?address=` without an API key. Account state on Arcus is **readable by anyone who knows the address**; the API key authorizes *writes* only.

> [!WARNING]
>
> Your positions and fills are observable in real time by anyone who knows your address. If a strategy depends on that activity not being attributable, separate it by address — the API offers no per-address read restriction.

The WebSocket `authenticate` method exists, but it is **not** a prerequisite for subscribing or for signed order methods (each order carries its own signature). See [Authentication](https://docs.arcus.xyz/api-reference/authentication.md).

## Placing orders

Order methods are asynchronous. The server returns `202` with `status: "ACK"` (or `CANCEL_ACKNOWLEDGED`); subscribe to the [`orders`](https://docs.arcus.xyz/api-reference/channels#orders) or [`userFills`](https://docs.arcus.xyz/api-reference/channels#userfills) channels to observe the lifecycle.

```json theme={null}
{
  "type": "post",
  "id": 1,
  "request": {
    "type": "placeOrder",
    "payload": {
      "address": "0x...",
      "accountIndex": 0,
      "marketId": 1,
      "orderSide": "BUY",
      "orderType": "LIMIT",
      "timeInForce": "GTT",
      "goodTilTime": "4102444800000000",
      "quantity": "0.01",
      "price": "50000"
    },
    "apiKey": "<64-hex-public-key>",
    "timestamp": "1712345678000000000",
    "signature": "<128-hex-signature>"
  }
}
```

Server response:

```json theme={null}
{
  "method": "placeOrder",
  "id": 1,
  "status": 202,
  "result": { "orderId": "...", "status": "ACK" }
}
```

> [!WARNING]
>
> **No cancel-on-disconnect.** Dropping a WebSocket connection tears down your subscriptions but does **not** cancel your resting orders. An order rests until it fills, you explicitly cancel it, or its `goodTilTime` expires (an expired resting order is removed when matching reaches it and reported on the `orders` channel as `REJECTED` / `EXPIRED`); see [Order types](https://docs.arcus.xyz/concepts/perpetuals/order-types.md#time-in-force) for the `goodTilTime` rules. If you need orders pulled when your process dies, arm the [dead man's switch](#dead-mans-switch-schedulecancel) or run your own external kill-switch that cancels on disconnect.

## Dead man's switch (`scheduleCancel`)

`scheduleCancel` is a server-side dead man's switch: you arm a deadline, and if you don't refresh it before it elapses, the gateway automatically cancels your resting orders. Use it so a crashed or disconnected trading process doesn't leave stale quotes on the book.

It's a signed `post` method using the same envelope as other order methods, but it signs with Scheme 2 (see [Authentication → Sign protected requests](https://docs.arcus.xyz/api-reference/authentication.md#sign-protected-requests)), not the typed order payload. It is also available over REST as `POST /v1/scheduleCancel`.

* **Arm or refresh** — send `time`, an absolute epoch-**microsecond** deadline between **5 seconds and 5 minutes** in the future. Keep the switch alive by sending a new, later `time` before the current one elapses (typically `now + 60s` on a short refresh interval); reusing a past `time` does not extend it.
* **Disarm** — omit `time` (or send `null`).

**Scope.** Omit `marketId` for an account-wide switch (cancels every open order across all markets when it fires), or set it to scope the switch to a single market. Per-market switches are independent of the account-wide switch and of each other on the same subaccount — each keeps its own deadline and cancels only its own market — so you can run one process per market, each arming its own switch. `marketId` selects which switch a given arm/refresh/disarm targets.

```json theme={null}
{
  "type": "post",
  "id": 5,
  "request": {
    "type": "scheduleCancel",
    "payload": { "address": "0x...", "accountIndex": 0, "time": 1734567890123000 },
    "apiKey": "<64-hex-public-key>",
    "timestamp": "1712345678000000000",
    "signature": "<128-hex-signature>"
  }
}
```

Add `"marketId": 1` to the payload to scope the switch to a single market.

**Limits.** Every arm/refresh draws from the per-subaccount cancel pool, and the switch has its own quotas on auto-fires and on switches armed at once — see [Rate limits → Dead man's switch quotas](https://docs.arcus.xyz/api-reference/rate-limits.md#dead-mans-switch-quotas).

When a switch fires, the resulting cancellations stream over the [`orders`](https://docs.arcus.xyz/api-reference/channels#orders) channel like any other cancel.

## Channels

See the [Channels](https://docs.arcus.xyz/api-reference/channels) reference for the full list and per-channel payload schemas.

## Sequence numbers

Streamed messages carry sequence numbers so you can order events, detect dropped messages, and resync after a reconnect. Three scopes exist:

* **Global** — one monotonic counter across the whole exchange, incremented for every event the matching engine processes. Use it to order events across markets and to tell whether you've missed anything.
* **Per-market** — a counter local to a single market.
* **Per-account** — a counter local to a single account.

Which field carries the sequence depends on the message:

| Scope | Field | Appears on |
| - | - | - |
| Global | `globalSequenceId` | `l2Orderbook`, `l2OrderbookUpdates`, `bbo` |
| Global | `sequenceNumber` | `trades` |
| Per-market (order book) | `lastSequenceId` | `l2Orderbook`, `l2OrderbookUpdates`, `bbo` |
| Per-market (market attributes) | `marketSequenceNum` | `exchangeAttributeUpdates` (`marketAttributes` entries) |
| Per-account | `sequenceNumber` | `AccountUpdate` (`AccountTransferEvent` exposes the same value as `accountSequenceNum`) |
| Per-account | `lastSequenceId` | `account` and `positions` snapshots |

The `lastSequenceId` on `account` and `positions` snapshots is the per-account sequence at snapshot time — the same counter as `AccountUpdate.sequenceNumber` and `Order.sequenceNumber`. Streaming `positions` deltas carry this same per-account counter: each `PositionUpdate` envelope stamps `lastSequenceId` and each position row carries `sequenceNumber`, so a delta can be ordered directly against account updates and used to discard updates already contained in a snapshot. For account state, treat each snapshot as the reconciliation point: the `account` channel re-snapshots every 5 seconds, and a re-subscribe fetches a fresh snapshot on any other account-scoped channel.

### Resyncing the order book

`lastSequenceId` on `l2OrderbookUpdates` increases by exactly 1 per delta. Any gap, including between the subscribe snapshot and the first delta, is a missed update and does not repair itself: deltas carry absolute level sizes, and the snapshot can lag the live stream.

To (re)build the book, keep buffering deltas, take a fresh snapshot with the same `nLevels` (an `l2Orderbook` frame or [`GET /v1/l2OrderBook/{market}`](https://docs.arcus.xyz/api-reference/public/get-l2-orderbook-snapshot)), replace your book with it, and apply only buffered deltas with a higher `lastSequenceId`. If the snapshot's `lastSequenceId` is lower than your oldest buffered delta minus 1, take another snapshot. After that, also drop any later delta at or below the snapshot's `lastSequenceId`: the snapshot can arrive ahead of your buffer. Size `"0"` removes a level.

Don't need deltas? Subscribe to `l2Orderbook` instead: every frame is the full book (to `nLevels`), so there is nothing to reconcile.

Use `globalSequenceId` to order order-book events against other markets.

### Order-book sequence contiguity

The order-book channels share the same per-market `lastSequenceId`, but only `l2OrderbookUpdates` (and the `l2Orderbook` snapshot it baselines against) is **contiguous** — the only stream where a gap is meaningful. Treat each field by its guarantee:

| Field / channel | Contiguous per subscription? | Handling |
| - | - | - |
| `lastSequenceId` on `l2Orderbook` / `l2OrderbookUpdates` | Contiguous: every delta is previous + 1, including the first after a snapshot | Any gap (including snapshot → first delta) is a missed update: [rebuild the book](#resyncing-the-order-book). |
| `lastSequenceId` on `bbo` | No — advances past suppressed updates | `bbo` emits a frame only when the top of book changes, so the sequence legitimately **jumps forward** over depth-only updates. A forward jump is normal — do **not** treat it as a dropped frame or re-subscribe. |
| `globalSequenceId` (any channel) | No — cross-market counter | Other markets consume values, so it skips within a single market's stream. It's an ordering key only; never gap-check it. |

`bbo` is a snapshot channel: every frame carries the full current top of book and self-replaces the previous one, so a dropped frame self-heals on the next — there is no in-band gap detection and none is needed. If you need a contiguous, gap-detectable, replayable order-book stream, use `l2Orderbook` / `l2OrderbookUpdates`.

On every reconnect, [rebuild the book](#resyncing-the-order-book) the same way; don't assume `lastSequenceId` continuity across the gap.

## Errors

Responses include an HTTP-like `status` and either a `result` or an `error` object with `type`, `message`, and optional `field`, `errorType` / `errorSource` (machine-readable code and the layer that raised it; `errorType: Transmission` means the order never reached the matching engine and is safe to resend unchanged) and `retryAfterMs` (on `429`).

**Close codes.** After 100 consecutive failed API-key authentications on a connection, the server closes it with code `4401` and reason `too many consecutive authentication failures`; a successful authentication resets the count. Treat `4401` as a credentials problem: fix the API key or signature before connecting again rather than reconnecting in a loop.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.