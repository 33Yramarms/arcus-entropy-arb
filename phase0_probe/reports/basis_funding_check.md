# Basis & funding verification (PR #1.5, read-only)

Samples: 5, local epoch ms 1795718110636 → 1795718124867. All bps are relative to the Arcus oracle.

## a) Where does the HL − Arcus mid premium come from?

| Symbol | Arcus oracle | Arcus mid | HL oracle | HL mid | oracle diff bps (median) | book-premium diff bps (median) | mid diff bps (median) | HL mid−oracle bps | Arcus mid−oracle bps |
|---|---|---|---|---|---|---|---|---|---|
| BTC | 60546.1 | 60551.95 | 60620.0 | 60588.50 | 12.617 | -6.103 | 6.037 | -5.196 | 0.900 |
| ETH | 1697.52 | 1697.12 | 1699.6 | 1698.65 | 12.429 | -3.623 | 8.865 | -5.590 | -2.268 |
| SOL | 71.214 | 71.19 | 71.305 | 71.27 | 12.778 | -1.404 | 11.374 | -4.979 | -4.002 |

USDT/USD cross-check (Kraken public ticker, third-party): mid 0.99872500 → a USDT-quoted price sits **12.766 bps** above a USD-quoted one. HL oracles are USDT-denominated (contract-specifications.md); Arcus oracles are Pyth USD (prices.md).

## b) Funding conversion (step by step)

### BTC

* Arcus raw `nextFundingRate` = `0.0000125` (`fundingRate` last applied = `0.0000125`), decimal fraction per hour (schema: 'Hourly funding rate (decimal string)'); 1 h (charged once an hour) → 0.001250 %/h → ×8760 = **10.950 %/yr**. Sign: positive => longs pay shorts.
* HL raw ctx `funding` = `0.0000020404`, predictedFundings HlPerp = `{'fundingRate': '0.0000020749', 'nextFundingTime': 1795716000000, 'fundingIntervalHours': 1}` → hourly 0.0000020749; decimal fraction per hour; 1 h (8 h formula / 8) → 0.000207 %/h → ×8760 = **1.818 %/yr**. Sign: positive => longs pay shorts.
* HL − Arcus (forecast) = **-9.132 %/yr** ⇒ short Arcus + long HL carry = **9.132 %/yr**.
* HL formula check (fundingHistory, last hours): P=-0.0005514966 → -0.000006437075 vs -0.0000064371 (err 0.000000000025), P=-0.0005472825 → -0.0000059103125 vs -0.0000059103 (err 0.0000000000125), P=-0.0005093278 → -0.000001165975 vs -0.000001166 (err 0.000000000025)
* Realized (both venues, same hour): 1795716000000: A 0.0000125 / HL -0.000001166 → Δann -11.97 %, 1795712400000: A 0.0000125 / HL -0.0000059103 → Δann -16.13 %, 1795708800000: A 0.0000125 / HL -0.0000064371 → Δann -16.59 %, 1795705200000: A 0.0000125 / HL -0.0000099432 → Δann -19.66 %

### ETH

* Arcus raw `nextFundingRate` = `0.0000125` (`fundingRate` last applied = `0.0000125`), decimal fraction per hour (schema: 'Hourly funding rate (decimal string)'); 1 h (charged once an hour) → 0.001250 %/h → ×8760 = **10.950 %/yr**. Sign: positive => longs pay shorts.
* HL raw ctx `funding` = `-0.0000036169`, predictedFundings HlPerp = `{'fundingRate': '-0.0000035747', 'nextFundingTime': 1795716000000, 'fundingIntervalHours': 1}` → hourly -0.0000035747; decimal fraction per hour; 1 h (8 h formula / 8) → -0.000357 %/h → ×8760 = **-3.131 %/yr**. Sign: positive => longs pay shorts.
* HL − Arcus (forecast) = **-14.081 %/yr** ⇒ short Arcus + long HL carry = **14.081 %/yr**.
* HL formula check (fundingHistory, last hours): P=-0.0005246745 → -0.0000030843125 vs -0.0000030843 (err 0.0000000000125), P=-0.0005513625 → -0.0000064203125 vs -0.0000064203 (err 0.0000000000125), P=-0.0005135232 → -0.0000016904 vs -0.0000016904 (err 0.0000000000)
* Realized (both venues, same hour): 1795716000000: A 0.0000125 / HL -0.0000016904 → Δann -12.43 %, 1795712400000: A 0.0000125 / HL -0.0000064203 → Δann -16.57 %, 1795708800000: A 0.0000125 / HL -0.0000030843 → Δann -13.65 %, 1795705200000: A 0.0000125 / HL 0.0000081523 → Δann -3.81 %

### SOL

* Arcus raw `nextFundingRate` = `0.00000984965944949995` (`fundingRate` last applied = `0.000011168021060276`), decimal fraction per hour (schema: 'Hourly funding rate (decimal string)'); 1 h (charged once an hour) → 0.000985 %/h → ×8760 = **8.628 %/yr**. Sign: positive => longs pay shorts.
* HL raw ctx `funding` = `-0.0000001081`, predictedFundings HlPerp = `{'fundingRate': '-0.0000000932', 'nextFundingTime': 1795716000000, 'fundingIntervalHours': 1}` → hourly -0.0000000932; decimal fraction per hour; 1 h (8 h formula / 8) → -0.000009 %/h → ×8760 = **-0.082 %/yr**. Sign: positive => longs pay shorts.
* HL − Arcus (forecast) = **-8.710 %/yr** ⇒ short Arcus + long HL carry = **8.710 %/yr**.
* HL formula check (fundingHistory, last hours): P=-0.0004723063 → 0.0000034617125 vs 0.0000034617 (err 0.0000000000125), P=-0.0004491142 → 0.000006360725 vs 0.0000063607 (err 0.000000000025), P=-0.0005000617 → -0.0000000077125 vs -0.0000000077 (err 0.0000000000125)
* Realized (both venues, same hour): 1795716000000: A 0.000011168021060276 / HL -0.0000000077 → Δann -9.79 %, 1795712400000: A 0.0000125 / HL 0.0000063607 → Δann -5.38 %, 1795708800000: A 0.0000125 / HL 0.0000034617 → Δann -7.92 %, 1795705200000: A 0.0000125 / HL 0.0000058165 → Δann -5.85 %

## Docs

* arcus_markets: https://docs.arcus.xyz/api-reference/public/get-markets.md
* arcus_funding_rates: https://docs.arcus.xyz/api-reference/public/get-market-funding-rates.md
* arcus_funding_concept: https://docs.arcus.xyz/concepts/perpetuals/funding.md
* arcus_prices: https://docs.arcus.xyz/concepts/perpetuals/prices.md
* hl_funding: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/funding.md
* hl_perp_info: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals.md
* hl_contract_specs: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/contract-specifications.md
* hl_oracle: https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/oracle.md
* usdt_usd_cross_check (third-party, NOT a venue doc): https://api.kraken.com/0/public/Ticker?pair=USDTZUSD
