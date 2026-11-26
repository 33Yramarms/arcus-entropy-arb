# Funding history back-test (PR #1.5, read-only) — 30 days

Window requested: epoch ms 1793124060000 → 1795716060000. Hourly, aligned by payment hour. Carry = funding received per hour as a fraction of notional (positive = you receive). Fees = round trip (open + close, both legs, tier 0). Funding only — no basis/price PnL, slippage or buffer.

| Symbol | Direction | hours | mean bps/h | daily bps | annualized % | % hours > 0 | longest + run h | avg + run h | sign flips | total carry bps |
|---|---|---|---|---|---|---|---|---|---|---|
| BTC | SHORT_ARCUS_LONG_HL | 720 | 0.0175 | 0.419 | 1.529 | 30.4 | 18 | 4.29 | 38 | 12.568 |
| BTC | LONG_ARCUS_SHORT_HL | 720 | -0.0175 | -0.419 | -1.529 | 10.1 | 19 | 2.61 | 38 | -12.568 |
| ETH | SHORT_ARCUS_LONG_HL | 720 | 0.0460 | 1.105 | 4.033 | 50.4 | 30 | 6.15 | 64 | 33.151 |
| ETH | LONG_ARCUS_SHORT_HL | 720 | -0.0460 | -1.105 | -4.033 | 15.0 | 14 | 2.92 | 64 | -33.151 |
| SOL | SHORT_ARCUS_LONG_HL | 720 | 0.0544 | 1.306 | 4.767 | 56.1 | 36 | 6.85 | 46 | 39.184 |
| SOL | LONG_ARCUS_SHORT_HL | 720 | -0.0544 | -1.306 | -4.767 | 14.6 | 22 | 4.20 | 46 | -39.184 |

## Break-even after round-trip fees

| Symbol | Direction | Fee mode | RT fee bps | expected BE h (fee/mean) | BE h entering at window start | rolling entries breaking even | median BE h (those) | net PnL holding whole window bps |
|---|---|---|---|---|---|---|---|---|
| BTC | SHORT_ARCUS_LONG_HL | DUAL_TAKER | 18.00 | 1031.2 | never | 0/720 | n/a | -5.432 |
| BTC | SHORT_ARCUS_LONG_HL | MAKER_ARCUS_TAKER_HL | 12.00 | 687.4 | 608 | 396/720 | 387 | 0.568 |
| BTC | SHORT_ARCUS_LONG_HL | MAKER_HL_TAKER_ARCUS | 12.00 | 687.4 | 608 | 396/720 | 387 | 0.568 |
| BTC | LONG_ARCUS_SHORT_HL | DUAL_TAKER | 18.00 | never (mean ≤ 0) | never | 0/720 | n/a | -30.568 |
| BTC | LONG_ARCUS_SHORT_HL | MAKER_ARCUS_TAKER_HL | 12.00 | never (mean ≤ 0) | never | 0/720 | n/a | -24.568 |
| BTC | LONG_ARCUS_SHORT_HL | MAKER_HL_TAKER_ARCUS | 12.00 | never (mean ≤ 0) | never | 0/720 | n/a | -24.568 |
| ETH | SHORT_ARCUS_LONG_HL | DUAL_TAKER | 18.00 | 390.9 | 468 | 431/720 | 333 | 15.151 |
| ETH | SHORT_ARCUS_LONG_HL | MAKER_ARCUS_TAKER_HL | 12.00 | 260.6 | 412 | 532/720 | 196 | 21.151 |
| ETH | SHORT_ARCUS_LONG_HL | MAKER_HL_TAKER_ARCUS | 12.00 | 260.6 | 412 | 532/720 | 196 | 21.151 |
| ETH | LONG_ARCUS_SHORT_HL | DUAL_TAKER | 18.00 | never (mean ≤ 0) | never | 0/720 | n/a | -51.151 |
| ETH | LONG_ARCUS_SHORT_HL | MAKER_ARCUS_TAKER_HL | 12.00 | never (mean ≤ 0) | never | 0/720 | n/a | -45.151 |
| ETH | LONG_ARCUS_SHORT_HL | MAKER_HL_TAKER_ARCUS | 12.00 | never (mean ≤ 0) | never | 0/720 | n/a | -45.151 |
| SOL | SHORT_ARCUS_LONG_HL | DUAL_TAKER | 18.00 | 330.7 | 464 | 502/720 | 244 | 21.184 |
| SOL | SHORT_ARCUS_LONG_HL | MAKER_ARCUS_TAKER_HL | 12.00 | 220.5 | 319 | 561/720 | 156 | 27.184 |
| SOL | SHORT_ARCUS_LONG_HL | MAKER_HL_TAKER_ARCUS | 12.00 | 220.5 | 319 | 561/720 | 156 | 27.184 |
| SOL | LONG_ARCUS_SHORT_HL | DUAL_TAKER | 18.00 | never (mean ≤ 0) | never | 0/720 | n/a | -57.184 |
| SOL | LONG_ARCUS_SHORT_HL | MAKER_ARCUS_TAKER_HL | 12.00 | never (mean ≤ 0) | never | 0/720 | n/a | -51.184 |
| SOL | LONG_ARCUS_SHORT_HL | MAKER_HL_TAKER_ARCUS | 12.00 | never (mean ≤ 0) | never | 0/720 | n/a | -51.184 |

## Coverage

* BTC: Arcus rows 720 (first 1793127600000), HL rows 720 (first 1793127600050), aligned hours 720, Arcus distinct rate values 109, Arcus hours at exactly 0.0000125 (crypto base): 612
* ETH: Arcus rows 720 (first 1793127600000), HL rows 720 (first 1793127600050), aligned hours 720, Arcus distinct rate values 181, Arcus hours at exactly 0.0000125 (crypto base): 540
* SOL: Arcus rows 720 (first 1793127600000), HL rows 720 (first 1793127600050), aligned hours 720, Arcus distinct rate values 162, Arcus hours at exactly 0.0000125 (crypto base): 559
