> ## Documentation Index
> Fetch the complete documentation index at: https://docs.arcus.xyz/llms.txt
> Use this file to discover all available pages before exploring further.

# Rate limits

> How requests are weighted and throttled across REST, WebSocket, and the trading path

Arcus throttles traffic in two independent layers. Both can reject the same request, and a request must pass both to succeed:

* **Per-IP weight limits** — every REST request costs a *weight*. Each source IP gets a token budget that refills over time; expensive endpoints drain it faster. WebSocket messages do not draw from this budget; they have their own [per-IP limits](#websocket-limits).
* **Per-subaccount trading limits** — order placement and cancellation draw from two pools keyed to your subaccount, independent of IP. These scale with your realized trading volume.

> [!NOTE]
>
> Limits are enforced globally across all gateway nodes (state lives in a shared store), so spreading requests across connections or hitting different nodes does not raise your effective budget. The read budget is keyed on the **source IP**, not on the address or API key: every account queried from one IP shares that IP's bucket, and REST requests from different IPs draw from separate buckets.

## Per-IP weight limits

Every IP gets a token bucket holding **1,500 weight**, refilling continuously at **1,500 weight per minute** (25 weight/second). Each request deducts its weight before the handler runs. When the bucket can't cover a request's weight, the request is rejected.

### Rejection contract

A throttled request returns:

```http theme={null}
HTTP/1.1 429 Too Many Requests
Retry-After: 2
Content-Type: application/json

{"error":"rate limited"}
```

`Retry-After` is the whole number of seconds to wait before the bucket holds enough tokens to retry (minimum `1`). Arcus does **not** return `X-RateLimit-*` headers — the budget and per-endpoint weights are published here instead, so you can account for cost client-side rather than discovering it per response.

### Which limit did I hit?

The response **body tells you which bucket rejected the request**, so you never have to guess which layer to tune:

| Body | Bucket that rejected you | What to change |
| - | - | - |
| `{"error":"rate limited"}` — no `reason` field | **Per-IP weight**, on a read endpoint | Lower read frequency, move to a WebSocket subscription, or use a cheaper endpoint |
| `{"error":"rate limited","reason":"ip",...}` | **Per-IP weight**, on an order write | Reduce non-write traffic from this IP — the write itself is free, so something else drained the bucket |
| `{"error":"rate limited","reason":"account_empty",...}` | **Per-subaccount pool** is exhausted; you are on the drip | Slow the order/cancel loop, or build lifetime volume to raise the cap |
| `{"error":"rate limited","reason":"account_partial",...}` | **Per-subaccount pool** can't cover this charge in full (typically an oversized batch) | Send a smaller batch |

Order-write rejections carry two extra fields: `retryAfterMs`, the precise millisecond wait (the `Retry-After` header is the same value rounded up to whole seconds, so it is never shorter), and the `clientId` / `clientIds` you submitted, echoed back so a rejection can be correlated to a specific order:

```json theme={null}
{
  "error": "rate limited",
  "reason": "account_empty",
  "retryAfterMs": 850,
  "clientId": "my-order-1"
}
```

> [!NOTE]
>
> There is **no maker-specific or taker-specific throttle**. The only limits that exist are the per-IP weight bucket, the two per-subaccount trading pools, and the [WebSocket connection limits](#websocket-limits) below. If a `429` is not attributable to one of those, it is not a rate limit.

### Working out which limit binds first

Because the IP bucket refills at **25 weight/second**, the sustainable request rate depends entirely on endpoint weight:

| Endpoint weight | Sustained rate from one IP | Example endpoints |
| - | - | - |
| 2 | **12.5 req/s** | `bbo`, `mids`, `account`, `positions`, `order`, `feetiers` |
| 20 | **1.25 req/s** | `prices`, `markets`, `orders`, `fills`, `openOrders`, `portfolio`, `candles` |
| 125 | **0.2 req/s** | `setLeverage`, `withdraw`, `transfer` |
| 0 | unbounded on this layer | order writes (pool-governed), `health` |

A polling loop at, say, 4 req/s against weight-20 endpoints costs 80 weight/s against a 25/s refill — it drains the 1,500 bucket in roughly 25 seconds and then throttles continuously, **even though the order path is completely idle**. Order writes cost 0 IP weight, so a `429` seen while placing orders at a modest rate is usually the read traffic sharing that IP, not the trading path. Check the `reason` field before rate-limiting your own order flow.

### Weight tiers

Endpoints fall into a handful of tiers by how much work they cost the backend. With a 1,500/min budget that's roughly **750 cheap reads**, **75 standard list calls**, or **12 `setLeverage`/`withdraw` calls** per minute from a single IP.

| Weight | Endpoints |
| - | - |
| **0** | `health` — never touches the limiter (use it for liveness probes). **Order writes** — `placeOrder`, `modifyOrder`, `cancelOrder`, and `cancelAllOrders` — are also **free on the IP layer**; they're governed entirely by the per-subaccount trading pools below (`cancelAllOrders` charges the cancel pool a flat 1,000). `scheduleCancel` is free on the IP layer too and charges the cancel pool. |
| **1** | `/` (root), `time` |
| **2** | Cheap single-object reads — `bbo`, `mids`, `account`, `positions`, `spotPositions`, `order`, `fill`, `feetiers`, `commissionrates`, `markets/feeSchedules`, `corporateActions` (all markets or one), `leverages`, `accountStats`, `rateLimit`, `affiliate/code` |
| **5** | `lendingAttributes` |
| **20** | Standard data, lists, and management — `prices`, `markets`, `spotAssets`, `trade`, `trades`, `candles`, `portfolio`, `openOrders`, `orders`, `fills`, `spotFills`, `funding`, `fundingRates`, `interest`, `accountTransferUpdates`, `leaderboard`, `apiKeys`, `createApiKey`, `revokeApiKey`, and every other [referral endpoint](https://docs.arcus.xyz/api-reference/referral/get-affiliate-info.md) (`/v1/affiliate/*` reads and writes) |
| **125** | Heavyweight writes — `setLeverage`, `adjustIsolatedMargin`, `settleLoan`, `withdraw`, `transfer` |

**Batch order writes** (`batchPlaceOrders`, `batchCancelOrders`, `batchModifyOrders`) are also free on the IP base; they incur only a post-flight per-item charge of `floor(N/40)` weight for a batch of `N` — so a batch of up to 39 orders costs **0** IP weight. As with single writes, the real limit is the per-subaccount trading pool (each element charges the pool 1).

**List endpoints add a per-item charge** on top of their base weight, computed from the rows actually returned: `weight = base + floor(items / N)`, where `N` is `20` for most lists — `60` for `candles` and `50` for `openOrders`. Page sizes are capped at **1,000 rows** for most lists — `1,500` for `candles` — so the worst-case add-on is bounded: a full 1,000-row page of `fills` costs `20 + 50 = 70`, and a full 1,500-bar `candles` page costs `20 + 25 = 45`. `l2OrderBook` works the same way on order-book depth, charging on the depth you request rather than the rows returned: `2 + floor(nLevels/20)`, maxing at weight 7 for a 100-level book. Because the row count isn't known until the query runs, this charge is applied after the response is sent, so a single large page can briefly drive your bucket negative; requests arriving before it refills are rejected with `429` and a `Retry-After` hint, as above.

## Per-subaccount trading limits

Order placement and cancellation draw from two pools scoped to your **subaccount** (address + account index), enforced on both the REST and WebSocket order paths. This is the address-based analogue to the per-IP layer: it bounds how fast a single account can act, regardless of how many IPs or connections it spreads across.

| Pool | Starting cap | Charged by |
| - | - | - |
| **Order** | 20,000 | `placeOrder` / `modifyOrder` — 1 per order (N for a batch of N) |
| **Cancel** | 40,000 | `cancelOrder` — 1 per cancel (N for a batch of N); `cancelAllOrders` — flat **1,000** |

The pools are independent: a cancel-heavy strategy can drain the cancel pool while the order pool sits nearly full, or vice versa.

Both pools are keyed **strictly** on `(address, accountIndex)` — there is no per-market component. Orders across every market share one order pool, so spreading flow over more markets does not buy extra headroom; moving it to another **subaccount** does, since each index carries its own pools (and its own volume credit).

### Volume-based replenishment

Each pool's effective cap grows with your **lifetime realized notional** — the more you trade, the more headroom you get:

```
effective cap = starting cap + lifetime_notional_usd / 0.10
```

Every **\$0.10** of realized fill notional adds **1** unit of pool headroom (so \$1 of volume buys **10**). Roughly **\$100K** of cumulative volume buys **+1,000,000** headroom on each pool, and high-volume market makers (≥ \$1M lifetime) are effectively unconstrained. The counter is cumulative and never decays, so caps only ever rise.

### When a pool is empty

Past the effective cap, a slow **drip** takes over: **1 action per 10 seconds** per pool. This keeps a depleted account alive at a trickle rather than hard-failing, while still throttling abuse. Charges that exceed the remaining pool are rejected the same way as the IP layer (with a retry hint).

> [!NOTE]
>
> Charges are refunded automatically if an accepted order fails to publish downstream (a transient internal error). Engine rejections do **not** refund — the matching-engine work was already consumed.

### Checking your remaining budget

`GET /v1/rateLimit?address=<0x...>&accountIndex=<n>` returns a live snapshot of both pools. It covers only the per-subaccount trading pools: there is no endpoint that reports how much of your [per-IP weight budget](#per-ip-weight-limits) is left, so track that client-side from the published weights. The call itself costs weight 2.

Example response:

```json theme={null}
{
  "address": "0x...",
  "accountIndex": 0,
  "order":  { "used": 1200, "cap": 21200, "nextAvailableMs": 0 },
  "cancel": { "used": 0,    "cap": 41200, "nextAvailableMs": 0 }
}
```

* `used` — units consumed since your last reseed.
* `cap` — current effective cap (starting cap plus volume replenishment).
* `nextAvailableMs` — `0` when you have headroom; otherwise the milliseconds until the next drip token frees up.

The subaccount parameter is spelled `accountIndex` (camelCase), the same as everywhere else in the API. An **unrecognised** parameter name is not an error — it is ignored, and the request silently resolves to index `0`. Because the response echoes back the `accountIndex` it actually served, compare that field against the index you asked for to catch a misspelling. An out-of-range `accountIndex` (above `9`) returns `400`.

### Dead man's switch quotas

The [dead man's switch](https://docs.arcus.xyz/api-reference/websocket.md#dead-mans-switch-schedulecancel) (`scheduleCancel`) draws from the **cancel** pool on every arm/refresh like other cancels, and adds two quotas of its own:

* **Auto-fires** — capped at **10 per UTC day per subaccount**, shared across all of that subaccount's switches (account-wide and per-market). A fire counts even when there are no open orders to cancel. After the 10th fire, every arm or refresh on that subaccount, account-wide or per-market, returns `429` with `schedule cancel trigger limit reached (10 per UTC day)` until the next UTC day, so the subaccount has no switch for the rest of the day. Disarming (`time: null`) still works.
* **Live switches** — a wallet may hold at most **50 switches armed at once**, across all its subaccounts and markets. Arming a new switch past the cap returns `429`; refreshing an already-armed switch is exempt.

## WebSocket limits

WebSocket traffic is bounded by its own per-IP limits. WebSocket messages do **not** draw from the REST weight bucket above:

| Limit | Value | Scope |
| - | - | - |
| Simultaneous connections | 50 | per IP |
| New connections | 50 / min | per IP |
| Subscriptions per connection | 100 | per socket |
| Subscriptions | 1,000 | per IP (across all connections) |
| Outbound messages | 1,000 / min | per IP |
| In-flight `post` messages | 50 | per connection |
| Connection lifetime | 24 hours | per connection (auto-closed after) |

Only **client→server** `subscribe` / `unsubscribe` messages, JSON `ping` messages, and malformed frames count against the outbound-message rate. Well-formed `post` / `get` RPCs are **exempt** — they're bounded by the per-subaccount trading pools and the in-flight `post` cap instead. Server-pushed `channel_data` updates are free. A rejected new connection still consumes a new-connection token, so a client hammering the connection cap burns its own budget faster.

## Handling rate limits

* **Read `Retry-After`** on a `429` and back off for at least that long — or `retryAfterMs` on an order write, which is precise to the millisecond. A blind retry loop will keep losing.
* **Check the `reason` field** before you throttle yourself. It names [which bucket rejected you](#which-limit-did-i-hit); tuning the wrong layer costs throughput for nothing.
* **Prefer WebSocket subscriptions over REST polling** for anything that changes frequently (order book, fills, account state). One subscription replaces a stream of weighted REST calls.
* **Batch order operations.** A batch of `N` costs only `floor(N/40)` IP weight (free on the IP base, like single writes) — far cheaper than `N` separate calls — though it still charges per item against the trading pool. You also save the per-request network round trips.
* **Poll `GET /v1/rateLimit`** if you run an aggressive order/cancel loop, and slow down as `used` approaches `cap`.
* **Request smaller pages** on list endpoints — a large page adds per-item weight after the fact.

If your use case legitimately needs higher limits (e.g. a high-volume market maker), reach out about IP allowlisting for your egress addresses.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.