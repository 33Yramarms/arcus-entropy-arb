> ## Documentation Index
> Fetch the complete documentation index at: https://docs.arcus.xyz/llms.txt
> Use this file to discover all available pages before exploring further.

# Prices

> The prices an Arcus perp market tracks — the mark price that drives all risk, the oracle price that anchors it, and the order-book inputs that feed it

An Arcus perp references a few different prices, and it helps to know which does what:

* **[Mark price](#mark-price)** — the exchange's fair-value estimate for the perp. It's the number your position is marked at and the **sole reference for margin, PnL, and [liquidations](https://docs.arcus.xyz/concepts/perpetuals/liquidations.md)**. Start here.
* **[Oracle price](#oracle-price)** — an external view of the underlying's fair value. It's an *input* to the mark price and drives the [funding](https://docs.arcus.xyz/concepts/perpetuals/funding.md) basis; it does not value your position directly.
* **Order-book prices** — the last trade price, the best bid and ask, and the *impact mid* (the average price to fill a fixed reference size on each side). These feed the mark price.

> [!NOTE]
>
> This page is conceptual. Live prices are available from [`GET /v1/prices`](https://docs.arcus.xyz/api-reference/public/get-live-prices-for-all-markets) and the market-data [WebSocket channels](https://docs.arcus.xyz/api-reference/channels).

## Mark price

The **mark price** is the exchange's fair-value estimate for a perp, and it is the **sole valuation reference** for risk: margin, unrealized PnL, and [liquidations](https://docs.arcus.xyz/concepts/perpetuals/liquidations.md) are all computed from it — there is no oracle fallback. It's also the number the off-hours [price bands](https://docs.arcus.xyz/concepts/perpetuals/real-world-assets.md#trading-when-the-underlying-is-closed) constrain. It blends the oracle price with the perp's own order book, so it tracks where the contract is actually trading without drifting far from fair value.

Two inputs feed the calculation:

* **Impact mid** — the midpoint of the *impact bid* and *impact ask*: the average price to fill a fixed reference size on each side of the book. Using impact prices rather than the top of book keeps the mark robust to a single thin quote.
* **Oracle price** — the external reference described [below](#oracle-price), available for crypto around the clock and for RWA perps during the underlying's [regular trading hours (RTH)](https://docs.arcus.xyz/concepts/perpetuals/real-world-assets.md#regular-trading-hours-rth).

### Markets with a live oracle

Crypto perps (24/7) and RWA perps **during RTH**. The mark price is the **average of two components**, then clamped to a tight band around the oracle:

1. **Order-book price** — the **median** of the last trade price, the best bid, and the best ask.
2. **Oracle-anchored price** — the oracle price plus a **2.5-minute EWMA** of (impact mid − oracle price). This tilts the mark toward where the perp is actually trading.

The average of the two is then **clamped to within ±min(10 ÷ leverage, 1)% of the oracle price** — at most ±1%, and tighter for higher-leverage markets. The clamp bounds the published mark's total deviation from the oracle; it is *not* applied to the EWMA term on its own. (If there's no recent trade, component 1 drops out and the mark is component 2 alone, still clamped.)

### Markets with no live oracle

RWA perps **outside RTH**, when the underlying is closed and no reliable external quote exists. The mark price then comes from the order book, without the oracle clamp, bounded by the off-hours price bands — see [Trading when the underlying is closed](https://docs.arcus.xyz/concepts/perpetuals/real-world-assets.md#trading-when-the-underlying-is-closed).

> [!NOTE]
>
> The reference size behind the impact mid, and the exact band parameters, are per-market risk settings read from the API. Treat the API's published prices as the source of truth rather than recomputing the mark yourself.

## Oracle price

The **oracle price** represents the fair value of the *underlying*. It anchors the mark price (above) and drives the [funding](https://docs.arcus.xyz/concepts/perpetuals/funding.md) basis. How it's sourced depends on whether a reliable external price is available right now.

| Situation | Oracle price source |
| - | - |
| **Underlying market open** (or a 24/7 crypto market) | Derived from external market data for the underlying. |
| **Underlying market closed** (RWA off-hours) | Derived from the exchange's own mark price, since no reliable external quote exists. |

For crypto, a market is effectively always "open," so the oracle tracks external crypto pricing continuously.

### Price sources

External prices come from **Pyth**, the primary source. If Pyth stops updating a market for longer than a staleness threshold while that market is in its [regular trading hours](https://docs.arcus.xyz/concepts/perpetuals/real-world-assets.md#regular-trading-hours-rth) (always, for 24/7 crypto), the oracle switches that market to a secondary source, **Stork**. It switches back to Pyth on the next Pyth update. The switch is automatic and per market, and the API's price fields keep the same shape whichever source is live.

Outside RTH the fallback never engages: a frozen Pyth quote is expected while the underlying is closed, and the oracle comes from the exchange's own mark price, as described above.

### External pricing for real-world assets

For equities, commodity ETFs, and index ETFs, Arcus references external market data for the underlying while that market is trading. Because cash instruments settle on a delay in traditional markets, the external price is adjusted to a consistent same-day basis so the perp tracks the economics a trader actually experiences. This adjustment is small in normal conditions.

Cash dividends are reflected in the oracle price itself. A stock split instead re-denominates the market, positions included; see [Stock splits](https://docs.arcus.xyz/concepts/perpetuals/stock-splits.md). For other corporate actions, see [Corporate actions](https://docs.arcus.xyz/concepts/perpetuals/real-world-assets.md#corporate-actions).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.