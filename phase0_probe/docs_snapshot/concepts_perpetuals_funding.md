> ## Documentation Index
> Fetch the complete documentation index at: https://docs.arcus.xyz/llms.txt
> Use this file to discover all available pages before exploring further.

# Funding

> How funding payments keep Arcus perps anchored to the underlying, how real-world-asset events are handled, and the off-hours funding and price-band regime

**Funding** is the mechanism that keeps a perp's price tethered to its underlying. Periodically, the side of the market trading at a premium pays the side trading at a discount, in proportion to the gap between the perp price and the [oracle price](https://docs.arcus.xyz/concepts/perpetuals/prices.md#oracle-price). When the perp trades above the oracle, longs pay shorts; when it trades below, shorts pay longs. There is no fee taken by the exchange on funding — it is a transfer between traders.

> [!NOTE]
>
> This page is conceptual. Live and historical funding values are available from [`GET /v1/fundingRates`](https://docs.arcus.xyz/api-reference/public/get-market-funding-rates) and the [`funding` WebSocket channel](https://docs.arcus.xyz/api-reference/channels#funding).

## The basic model

The funding rate is driven by the **basis** — the gap between the perp's price and the oracle price. A persistent premium produces positive funding (longs pay), which incentivizes traders to close longs / open shorts and pulls the price back toward the oracle; a persistent discount does the reverse. This is the same convergence mechanism used across perp markets.

> [!NOTE]
>
> **Base rate.** With no premium, funding sits at a **base rate**: a small fixed interest rate for crypto perps, and **SOFR + 0.5% per year** for real-world-asset perps. The premium (below) moves the live rate above or below that base. The rate in effect is `fundingRate` (last applied) and `nextFundingRate` on [`GET /v1/markets`](https://docs.arcus.xyz/api-reference/public/get-markets).

## How the rate is calculated

Funding is **charged once an hour**, and each hour's rate is built from two pieces:

* a **base rate** — the baseline cost of holding the position, charged even when the perp trades right at fair value; and
* a **premium** — an adjustment that grows as the perp drifts above or below the oracle, nudging the price back.

The premium is **sampled at regular intervals through the hour**, and the rate for the hour is the **median** of that hour's samples, so one brief spike can't swing it. The next charge time is `nextFundingAt` on [`GET /v1/markets`](https://docs.arcus.xyz/api-reference/public/get-markets). Throughout, `clamp(x, ±y)` just means "keep `x` within the range −y to +y."

### Step 1 — adjust the oracle to "today" (real-world assets only)

Stocks settle a day or more after they trade (T+1), so a live stock price isn't directly comparable to a perp you hold continuously. For RWA markets the oracle is nudged to a **same-day** value before the premium is measured (crypto settles same-day, so this step does nothing):

```
oracle_sameday = oracle / (1 + sofr_rate_hourly × 24 × days_to_settle)
```

`days_to_settle` is the calendar days until the stock settles (usually 1), and `sofr_rate_hourly` is the RWA base rate expressed per hour:

```
sofr_rate_hourly = (SOFR + 0.5%) / 360 / 24
```

**SOFR** (Secured Overnight Financing Rate) is the standard benchmark for the cost of borrowing US dollars overnight, published daily by the [New York Federal Reserve](https://www.newyorkfed.org/markets/reference-rates/sofr) — the same reference traditional finance uses for short-term funding. `sofr_rate_hourly` is simply that annual rate plus 0.5%, divided down to a per-hour figure. The effect on the oracle is tiny.

*Example.* AAPL oracle = `$200`, base rate ≈ 5%/yr (so `sofr_rate_hourly ≈ 0.00000579`), T+1 settlement → `200 / (1 + 0.00000579 × 24 × 1)` ≈ `$199.97` — under 3 cents.

### Step 2 — measure the premium

The **premium** is how far the perp trades from the [oracle price](https://docs.arcus.xyz/concepts/perpetuals/prices.md#oracle-price), as a fraction of the oracle. It uses **impact prices** — the average price to buy or sell a fixed test size by walking the order book — instead of the best bid/ask, so one tiny quote can't distort it:

```
premium = ( max(impact_bid − oracle, 0) − max(oracle − impact_ask, 0) ) / oracle
```

* perp **above** the oracle (impact bid > oracle) → **positive** premium → longs pay shorts
* perp **below** the oracle (impact ask \< oracle) → **negative** premium → shorts pay longs
* oracle sitting **between** the impact bid and ask → premium is **zero**

*Example.* BTC oracle = `$100,000`, and buying the test size would cost `$100,050` on average → premium = (100,050 − 100,000) / 100,000 = **0.05%**.

### Step 3 — turn the premium into the hourly rate

By convention the full premium is paid off over **8 hours**, so each hour charges **one-eighth** of it on top of the base rate. The total is capped at a per-market maximum hourly rate, `max_rate`, which can never exceed the engine's hard limit of **±4% per hour**.

**Crypto** — a fixed base rate, `base_rate_8h`, quoted per 8 hours. A small **dead-band**, `dead_band_8h`, holds funding exactly at the base rate until the premium moves more than that far away from the base level, so trivial premiums don't add funding noise:

```
base_rate_hourly    = base_rate_8h / 8                   # the 8h base, spread over the hour
funding_rate_hourly = clamp( premium/8 + clamp(base_rate_hourly − premium/8, ±dead_band_8h/8), ±max_rate )
```

**Real-world assets** — base rate **SOFR + 0.5% per year** (`sofr_rate_hourly`, from Step 1), with **no dead-band**, so the premium always counts and the rate lands exactly on the base rate when the perp trades at the same-day oracle:

```
funding_rate_hourly = clamp( sofr_rate_hourly + premium/8, ±max_rate )
```

*Example (RWA).* With `sofr_rate_hourly ≈ 0.00000579` and a perp trading 0.08% above the same-day oracle (`premium = 0.0008`): `funding_rate_hourly ≈ 0.00000579 + 0.0008/8` ≈ **0.0106%** for the hour.

### Step 4 — the payment

```
payment = funding_rate_hourly × position_size × oracle_price
```

Funding values the position at the **oracle price** (unlike margin, PnL, and liquidations, which use the [mark price](https://docs.arcus.xyz/concepts/perpetuals/prices.md#mark-price)). A positive rate means **longs pay shorts**; a negative rate, the reverse.

*Example.* At **0.0106%/hr** on a `$10,000` position, a long pays about `$1.06` that hour.

### How funding is applied

Funding accrues on each position every hour and is tracked in the position's `cumulativeFunding.sinceChange`. It is settled into your collateral balance (`netQuoteBalance`) at the position's next fill that changes its size: an increase, a partial reduce, or a full close. Deposits, withdrawals, subaccount transfers, and placing or cancelling orders do not settle it.

Until it is settled, accrued funding is not included in `equity` or `freeCollateral` on [`GET /v1/account`](https://docs.arcus.xyz/api-reference/public/get-account), or in the [`account`](https://docs.arcus.xyz/api-reference/channels#account) WebSocket channel snapshot. Margin and liquidation checks do count it: they use equity net of the funding accrued since each position's last size change, so the equity the engine evaluates can differ from the API `equity` field by that unsettled funding.

Each hourly payment is computed from the position you hold when the funding run executes, normally within about a second after the hour. A fill in the first seconds after the hour is therefore usually not reflected in that hour's payment.

Funding is **not** included in a position's `unrealizedPnl`, which reflects only the move from entry price to [mark price](https://docs.arcus.xyz/concepts/perpetuals/prices.md#mark-price), or in a fill's `closedPnl`. Per-position funding totals are reported in the `cumulativeFunding` object (`allTime`, `sinceOpen`, `sinceChange`; positive = received, negative = paid) on [`GET /v1/positions`](https://docs.arcus.xyz/api-reference/public/get-positions), and the history of individual payments is available from [`GET /v1/funding`](https://docs.arcus.xyz/api-reference/public/get-funding-payments).

When an RWA market is outside its [regular trading hours](https://docs.arcus.xyz/concepts/perpetuals/real-world-assets.md#regular-trading-hours-rth), this calculation is replaced by a SOFR-based rate — see [Off-hours funding](#off-hours-funding) below.

## Real-world assets

For perps on equities, commodity ETFs, and index ETFs, funding works the same way during [regular trading hours](https://docs.arcus.xyz/concepts/perpetuals/real-world-assets.md#regular-trading-hours-rth). Cash dividends are reflected in the oracle price, not paid through funding — see [Corporate actions](https://docs.arcus.xyz/concepts/perpetuals/real-world-assets.md#corporate-actions). Stock splits re-denominate the market and its positions instead; see [Stock splits](https://docs.arcus.xyz/concepts/perpetuals/stock-splits.md).

## Off-hours funding

While an RWA market is outside its [regular trading hours](https://docs.arcus.xyz/concepts/perpetuals/real-world-assets.md#regular-trading-hours-rth), there's no reliable oracle to measure a premium against, so the calculation above is suspended. Funding is instead set to **SOFR + 0.5%** (annualized, converted to the hourly rate) and **recomputed every hour from the latest SOFR**. Within RTH — premarket and after-hours included — funding runs live.

The rest of the off-hours regime (higher initial margin, price bands, and which markets it applies to) is described in [Trading when the underlying is closed](https://docs.arcus.xyz/concepts/perpetuals/real-world-assets.md#trading-when-the-underlying-is-closed).

> [!NOTE]
>
> Regular-trading-hours calendars differ by market, and the exact premium sampling and clamp parameters are per-market config. Read live funding from the API rather than recomputing it.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.