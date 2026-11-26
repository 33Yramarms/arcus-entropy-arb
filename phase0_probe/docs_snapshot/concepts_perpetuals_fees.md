> ## Documentation Index
> Fetch the complete documentation index at: https://docs.arcus.xyz/llms.txt
> Use this file to discover all available pages before exploring further.

# Fees

> How perpetuals trading fees work on Arcus — maker/taker fee tiers, per-market fee schedules, how fees are calculated, how volume counts toward your tier, maker-share tiers, and referral discounts and commissions

Trading fees on Arcus follow a **maker/taker fee-tier model**: the rate you pay depends on whether your order adds liquidity (maker) or removes it (taker), on your tier, which is set by your trailing 30-day trading volume or, for makers, your 30-day share of maker volume, and on the market you trade, since each market has its own fee schedule.

> [!NOTE]
>
> This page explains the model and does not quote rates. The rates each market charges are on [`GET /v1/markets/feeSchedules`](https://docs.arcus.xyz/api-reference/public/get-market-fee-schedules); to read your own tier, see [Your tier](#your-tier). Rates can change without a release, so always read them from the API rather than hard-coding them. You can also see your current tier on the [Arcus portfolio page](https://app.arcus.xyz/portfolio).

## The model

* **Maker** orders rest on the book and provide liquidity; **taker** orders execute against resting liquidity and remove it. Makers are charged less than takers, and higher tiers can earn **maker rebates**.
* **Tiers** are determined by your trading volume (see [How volume counts](#how-volume-counts)) or, for makers, your share of maker volume (see [Maker-share tiers](#maker-share-tiers)). The volume thresholds and the default maker/taker rate for each tier are in [`GET /v1/feetiers`](https://docs.arcus.xyz/api-reference/public/get-fee-tier-table). It lists volume thresholds only, so a maker-share tier does not appear there.
* **Per-market schedules:** your tier picks a row in the fee schedule of the market you trade. A market charges the default table unless it has its own schedule.
* Liquidations carry a separate liquidation fee, charged only on some liquidation outcomes. See [Liquidations](https://docs.arcus.xyz/concepts/perpetuals/liquidations.md#what-happens-to-the-position) for when it applies.
* Funding payments are **not** a fee — they are transfers between traders. See [Funding](https://docs.arcus.xyz/concepts/perpetuals/funding.md).

## Your tier

`GET /v1/feetiers` returns the exchange-wide default table only. To read the tier that applies to you, call [`GET /v1/account/stats`](https://docs.arcus.xyz/api-reference/public/get-account-stats) with `address=<your address>&include=feeTier`. The response carries `tradingFeeTier`, with your `level` and, when you have a referral discount, `feeDiscountPpm`. It carries no rates: the rate you pay is your level's rate in that market's fee schedule, less `feeDiscountPpm`. `level` reflects the tier applied to you, whether it comes from volume or maker share.

## Per-market fee schedules

Each market charges its own maker/taker rate for every tier:

* [`GET /v1/markets/feeSchedules`](https://docs.arcus.xyz/api-reference/public/get-market-fee-schedules) lists every market's full per-tier schedule (filter with `market`). `hasCustomSchedule` is `true` when the market has its own schedule rather than the default table.
* [`GET /v1/markets`](https://docs.arcus.xyz/api-reference/public/get-markets) carries the same schedule per market as `feeTiers`, plus `hasCustomFeeSchedule` and the market's base-tier rates (`effectiveMakerFeePpm` / `effectiveTakerFeePpm`, next to the default table's `baseMakerFeePpm` / `baseTakerFeePpm`).

RWA perpetuals (equities, commodities and indices) and crypto perpetuals use different fee schedules. Fills are charged at your tier's row of the market's schedule. Schedules can change without a release, so read them from the API before trading a market.

## How fees are calculated

* Rates are expressed in **ppm** (parts per million) of notional: `100` ppm = 0.01%.
* The fee on a fill is `fill notional × rate ppm / 1,000,000`.
* A **negative** maker rate is a rebate: it is credited to you instead of charged.
* A maker rebate on a fill is capped at the taker fee charged on that same fill.

## How volume counts

* Volume is your **filled notional** over a rolling 30-day window.
* Volume on RWA and crypto perpetuals counts toward a single tier, which applies in both schedules.
* It is tracked **per wallet address** and shared by all of that address's [subaccounts](https://docs.arcus.xyz/concepts/subaccounts.md). Every subaccount on the address trades at the same tier.
* Your tier is recalculated periodically, so it moves **up** shortly after your volume crosses the next threshold (not on the fill itself), and it can move **down** without any new trade as older volume leaves the 30-day window.

## Maker-share tiers

Makers can also reach Tier 5 and Tier 6 based on their 30-day share of maker volume. Volume tiers do not change.

* Your maker share is your maker volume over the last 30 days divided by total maker volume on Arcus perpetuals over the same period, across all crypto and RWA markets.
* It applies to every maker.

| Maker share (30 days) | Tier |
| - | - |
| Above 1.5% | Tier 5 |
| Above 4% | Tier 6 |

* You get whichever tier is higher: your volume tier or your maker-share tier.
* Maker share is calculated **per wallet address** and shared by its subaccounts, like volume. Maker volume is not combined across addresses.
* Eligibility is checked daily. A qualifying address is moved up, usually within one business day. If it no longer qualifies on maker share or volume, it goes back to its volume tier.
* A maker-share tier gets the full fee schedule for that tier, including the maker rebate.

For example, if total 30-day maker volume on Arcus is \$9B and your maker volume is \$150M, your share is 1.67%, which qualifies for Tier 5.

## Referrals

* If your address is registered under a referral code, you get a **5% discount** on positive maker and taker fees. Zero fees and maker rebates are not affected.
* Referrers earn a **commission** paid as a share of the referred trader's trading fee, not of their notional. The live commission rates per tier are at [`GET /v1/commissionrates`](https://docs.arcus.xyz/api-reference/public/get-referral-commission-rate-schedule). A tier not listed there earns the rate of the highest listed tier below it.
* Codes, referees, and commission claims are managed through the [referral endpoints](https://docs.arcus.xyz/api-reference/referral/get-affiliate-info.md).

## Account costs beyond trading fees

* **Deposits/withdrawals:** Arcus charges no fee of its own; USDG deposits and withdrawals carry zero fees. Third-party processing or conversion costs (for card/fiat or cross-chain routes) are shown upfront. See [Onboarding & deposits](https://docs.arcus.xyz/concepts/onboarding.md).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.