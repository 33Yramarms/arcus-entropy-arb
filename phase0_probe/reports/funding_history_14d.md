# Funding history back-test (PR #1.5, read-only) — 14 days

Window requested: epoch ms 1794506460000 → 1795716060000. Hourly, aligned by payment hour. Carry = funding received per hour as a fraction of notional (positive = you receive). Fees = round trip (open + close, both legs, tier 0). Funding only — no basis/price PnL, slippage or buffer.

| Symbol | Direction | hours | mean bps/h | daily bps | annualized % | % hours > 0 | longest + run h | avg + run h | sign flips | total carry bps |
|---|---|---|---|---|---|---|---|---|---|---|
| BTC | SHORT_ARCUS_LONG_HL | 336 | 0.0343 | 0.822 | 3.001 | 50.0 | 10 | 4.67 | 30 | 11.510 |
| BTC | LONG_ARCUS_SHORT_HL | 336 | -0.0343 | -0.822 | -3.001 | 14.0 | 19 | 2.76 | 30 | -11.510 |
| ETH | SHORT_ARCUS_LONG_HL | 336 | 0.0671 | 1.609 | 5.874 | 70.5 | 30 | 7.18 | 46 | 22.531 |
| ETH | LONG_ARCUS_SHORT_HL | 336 | -0.0671 | -1.609 | -5.874 | 21.4 | 12 | 3.00 | 46 | -22.531 |
| SOL | SHORT_ARCUS_LONG_HL | 336 | 0.0720 | 1.729 | 6.309 | 69.3 | 30 | 7.77 | 30 | 24.200 |
| SOL | LONG_ARCUS_SHORT_HL | 336 | -0.0720 | -1.729 | -6.309 | 20.8 | 22 | 4.67 | 30 | -24.200 |

## Break-even after round-trip fees

| Symbol | Direction | Fee mode | RT fee bps | expected BE h (fee/mean) | BE h entering at window start | rolling entries breaking even | median BE h (those) | net PnL holding whole window bps |
|---|---|---|---|---|---|---|---|---|
| BTC | SHORT_ARCUS_LONG_HL | DUAL_TAKER | 18.00 | 525.4 | never | 0/336 | n/a | -6.490 |
| BTC | SHORT_ARCUS_LONG_HL | MAKER_ARCUS_TAKER_HL | 12.00 | 350.3 | 229 | 12/336 | 224 | -0.490 |
| BTC | SHORT_ARCUS_LONG_HL | MAKER_HL_TAKER_ARCUS | 12.00 | 350.3 | 229 | 12/336 | 224 | -0.490 |
| BTC | LONG_ARCUS_SHORT_HL | DUAL_TAKER | 18.00 | never (mean ≤ 0) | never | 0/336 | n/a | -29.510 |
| BTC | LONG_ARCUS_SHORT_HL | MAKER_ARCUS_TAKER_HL | 12.00 | never (mean ≤ 0) | never | 0/336 | n/a | -23.510 |
| BTC | LONG_ARCUS_SHORT_HL | MAKER_HL_TAKER_ARCUS | 12.00 | never (mean ≤ 0) | never | 0/336 | n/a | -23.510 |
| ETH | SHORT_ARCUS_LONG_HL | DUAL_TAKER | 18.00 | 268.4 | 220 | 47/336 | 214 | 4.531 |
| ETH | SHORT_ARCUS_LONG_HL | MAKER_ARCUS_TAKER_HL | 12.00 | 179.0 | 180 | 148/336 | 170 | 10.531 |
| ETH | SHORT_ARCUS_LONG_HL | MAKER_HL_TAKER_ARCUS | 12.00 | 179.0 | 180 | 148/336 | 170 | 10.531 |
| ETH | LONG_ARCUS_SHORT_HL | DUAL_TAKER | 18.00 | never (mean ≤ 0) | never | 0/336 | n/a | -40.531 |
| ETH | LONG_ARCUS_SHORT_HL | MAKER_ARCUS_TAKER_HL | 12.00 | never (mean ≤ 0) | never | 0/336 | n/a | -34.531 |
| ETH | LONG_ARCUS_SHORT_HL | MAKER_HL_TAKER_ARCUS | 12.00 | never (mean ≤ 0) | never | 0/336 | n/a | -34.531 |
| SOL | SHORT_ARCUS_LONG_HL | DUAL_TAKER | 18.00 | 249.9 | 199 | 118/336 | 155 | 6.200 |
| SOL | SHORT_ARCUS_LONG_HL | MAKER_ARCUS_TAKER_HL | 12.00 | 166.6 | 147 | 177/336 | 101 | 12.200 |
| SOL | SHORT_ARCUS_LONG_HL | MAKER_HL_TAKER_ARCUS | 12.00 | 166.6 | 147 | 177/336 | 101 | 12.200 |
| SOL | LONG_ARCUS_SHORT_HL | DUAL_TAKER | 18.00 | never (mean ≤ 0) | never | 0/336 | n/a | -42.200 |
| SOL | LONG_ARCUS_SHORT_HL | MAKER_ARCUS_TAKER_HL | 12.00 | never (mean ≤ 0) | never | 0/336 | n/a | -36.200 |
| SOL | LONG_ARCUS_SHORT_HL | MAKER_HL_TAKER_ARCUS | 12.00 | never (mean ≤ 0) | never | 0/336 | n/a | -36.200 |

## Coverage

* BTC: Arcus rows 336 (first 1794510000000), HL rows 336 (first 1794510000035), aligned hours 336, Arcus distinct rate values 72, Arcus hours at exactly 0.0000125 (crypto base): 265
* ETH: Arcus rows 336 (first 1794510000000), HL rows 336 (first 1794510000035), aligned hours 336, Arcus distinct rate values 136, Arcus hours at exactly 0.0000125 (crypto base): 201
* SOL: Arcus rows 336 (first 1794510000000), HL rows 336 (first 1794510000035), aligned hours 336, Arcus distinct rate values 110, Arcus hours at exactly 0.0000125 (crypto base): 227
