# Opportunity summary (read-only) — BTC/ETH/SOL re-run with PR #1.5 gating + residual

Window: 1795718524000 → 1795719123000 epoch ms (600 s). Per second the better direction is taken. **net_resid** = open VWAP spread − close slippage − open+close fees − 2 bps buffer − the rolling median basis (exit assumed at the rolling median of HL−Arcus mid basis, not at 0). Gating: `not_ready` (either book unproven / resyncing) and `stale` (network latency > threshold or silent connection); book idleness never gates.

| Symbol | Q $ | Mode | % s net_resid>0 | runs | avg dur s | max run s | max net_resid bps | median net_resid bps | % s net>0 (zero-conv., Phase 0) | median open spread bps | median basis bps | median abs residual bps | stale % | not_ready % | warm-up s | insuff. depth s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC | 100 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -16.076 | -19.755 | 0.00 | -6.608 | 7.655 | 0.520 | 0.83 | 0.17 | 30 | 0 |
| BTC | 100 | MAKER_ARCUS_TAKER_HL | 0.00 | 0 | n/a | 0 | -10.043 | -13.648 | 0.00 | -6.561 | 7.655 | 0.520 | 0.83 | 0.17 | 30 | 0 |
| BTC | 100 | MAKER_HL_TAKER_ARCUS | 0.00 | 0 | n/a | 0 | -9.746 | -13.407 | 0.00 | -6.442 | 7.655 | 0.520 | 0.83 | 0.17 | 30 | 0 |
| BTC | 500 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -16.076 | -19.853 | 0.00 | -6.750 | 7.655 | 0.520 | 0.83 | 0.17 | 30 | 0 |
| BTC | 500 | MAKER_ARCUS_TAKER_HL | 0.00 | 0 | n/a | 0 | -10.043 | -13.667 | 0.00 | -6.568 | 7.655 | 0.520 | 0.83 | 0.17 | 30 | 0 |
| BTC | 500 | MAKER_HL_TAKER_ARCUS | 0.00 | 0 | n/a | 0 | -9.746 | -13.499 | 0.00 | -6.583 | 7.655 | 0.520 | 0.83 | 0.17 | 30 | 0 |
| BTC | 2000 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -16.076 | -19.942 | 0.00 | -6.822 | 7.655 | 0.520 | 0.83 | 0.17 | 30 | 0 |
| BTC | 2000 | MAKER_ARCUS_TAKER_HL | 0.00 | 0 | n/a | 0 | -10.043 | -13.678 | 0.00 | -6.569 | 7.655 | 0.520 | 0.83 | 0.17 | 30 | 0 |
| BTC | 2000 | MAKER_HL_TAKER_ARCUS | 0.00 | 0 | n/a | 0 | -9.746 | -13.588 | 0.00 | -6.601 | 7.655 | 0.520 | 0.83 | 0.17 | 30 | 0 |
| ETH | 100 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -14.290 | -20.179 | 0.00 | -7.120 | 9.194 | 0.585 | 2.17 | 0.17 | 30 | 0 |
| ETH | 100 | MAKER_ARCUS_TAKER_HL | 0.00 | 0 | n/a | 0 | -8.173 | -13.939 | 0.17 | -6.822 | 9.194 | 0.585 | 2.17 | 0.17 | 30 | 0 |
| ETH | 100 | MAKER_HL_TAKER_ARCUS | 0.00 | 0 | n/a | 0 | -7.115 | -12.970 | 0.33 | -6.204 | 9.194 | 0.585 | 2.17 | 0.17 | 30 | 0 |
| ETH | 500 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -14.290 | -20.237 | 0.00 | -7.328 | 9.194 | 0.585 | 2.17 | 0.17 | 30 | 0 |
| ETH | 500 | MAKER_ARCUS_TAKER_HL | 0.00 | 0 | n/a | 0 | -8.173 | -13.999 | 0.17 | -6.942 | 9.194 | 0.585 | 2.17 | 0.17 | 30 | 0 |
| ETH | 500 | MAKER_HL_TAKER_ARCUS | 0.00 | 0 | n/a | 0 | -7.115 | -13.001 | 0.33 | -6.216 | 9.194 | 0.585 | 2.17 | 0.17 | 30 | 0 |
| ETH | 2000 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -14.732 | -20.445 | 0.00 | -7.650 | 9.194 | 0.585 | 2.17 | 0.17 | 30 | 0 |
| ETH | 2000 | MAKER_ARCUS_TAKER_HL | 0.00 | 0 | n/a | 0 | -8.173 | -14.021 | 0.17 | -6.942 | 9.194 | 0.585 | 2.17 | 0.17 | 30 | 0 |
| ETH | 2000 | MAKER_HL_TAKER_ARCUS | 0.00 | 0 | n/a | 0 | -7.557 | -13.191 | 0.33 | -6.568 | 9.194 | 0.585 | 2.17 | 0.17 | 30 | 0 |
| SOL | 100 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -15.465 | -19.860 | 0.00 | 12.081 | 12.336 | 0.545 | 3.00 | 0.17 | 30 | 0 |
| SOL | 100 | MAKER_ARCUS_TAKER_HL | 0.00 | 0 | n/a | 0 | -9.086 | -13.435 | 4.17 | 12.347 | 12.336 | 0.545 | 3.00 | 0.17 | 30 | 0 |
| SOL | 100 | MAKER_HL_TAKER_ARCUS | 0.00 | 0 | n/a | 0 | -9.185 | -13.514 | 5.50 | 12.225 | 12.336 | 0.545 | 3.00 | 0.17 | 30 | 0 |
| SOL | 500 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -15.498 | -20.000 | 0.00 | 12.081 | 12.336 | 0.545 | 3.00 | 0.17 | 30 | 0 |
| SOL | 500 | MAKER_ARCUS_TAKER_HL | 0.00 | 0 | n/a | 0 | -9.086 | -13.474 | 4.00 | 12.341 | 12.336 | 0.545 | 3.00 | 0.17 | 30 | 0 |
| SOL | 500 | MAKER_HL_TAKER_ARCUS | 0.00 | 0 | n/a | 0 | -9.218 | -13.615 | 5.33 | 12.225 | 12.336 | 0.545 | 3.00 | 0.17 | 30 | 0 |
| SOL | 2000 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -15.616 | -20.172 | 0.00 | 11.987 | 12.336 | 0.545 | 3.00 | 0.17 | 30 | 0 |
| SOL | 2000 | MAKER_ARCUS_TAKER_HL | 0.00 | 0 | n/a | 0 | -9.086 | -13.538 | 3.67 | 12.222 | 12.336 | 0.545 | 3.00 | 0.17 | 30 | 0 |
| SOL | 2000 | MAKER_HL_TAKER_ARCUS | 0.00 | 0 | n/a | 0 | -9.335 | -13.717 | 4.33 | 12.206 | 12.336 | 0.545 | 3.00 | 0.17 | 30 | 0 |

## Funding (hourly rates, window means; predicted if available else current)

| Symbol | Arcus 1h | HL 1h | Arcus ann. | HL ann. | Δ ann. (HL−Arcus) | samples |
|---|---|---|---|---|---|---|
| BTC | 0.00001250 | 0.00000178 | 0.1095 | 0.0156 | -0.0939 | 119 |
| ETH | 0.00001250 | -0.00000273 | 0.1095 | -0.0239 | -0.1334 | 119 |
| SOL | 0.00000962 | 0.00000040 | 0.0843 | 0.0035 | -0.0807 | 119 |

Δ = HL − Arcus. Positive: long Arcus / short HL receives carry; negative: short Arcus / long HL receives.

## Book / connection health (per 1 s sample)

| book | samples | not_ready % | latency p50 / p90 / max ms | % latency > 500 ms | book_idle p50 / p90 / max ms | conn silence p50 / max ms |
|---|---|---|---|---|---|---|
| BTC/arcus | 600 | 0.17 | 82 / 158 / 284 | 0.00 | 41 / 224 / 1147 | 41 / 408 |
| BTC/hyperliquid | 600 | 0.00 | 313 / 354 / 538 | 0.83 | 267 / 499 / 746 | 207 / 727 |
| ETH/arcus | 600 | 0.17 | 98 / 189 / 303 | 0.00 | 26 / 227 / 1148 | 23 / 923 |
| ETH/hyperliquid | 600 | 0.00 | 341 / 402 / 638 | 2.17 | 268 / 498 / 841 | 202 / 802 |
| SOL/arcus | 600 | 0.17 | 81 / 174 / 291 | 0.00 | 31 / 436 / 1677 | 31 / 1023 |
| SOL/hyperliquid | 600 | 0.17 | 347 / 416 / 767 | 3.01 | 264 / 510 / 1407 | 204 / 1030 |

## Meta / feed stats

* `arcus_clock_offset_ms`: -10 (rtt 200 ms; GET /v1/time; hyperliquid: no documented server-time endpoint -> uncorrected)
* `args`: --duration-s 600 --db reports/spreads_v15.sqlite --log reports/record_spreads_v15.log
* `ended_ms`: 1795719124717
* `spec:BTC`: arcus step=1E-8 min=5 maker=0.00015 taker=0.00045 | hl coin=BTC step=0.00001 min=10 maker=0.00015 taker=0.00045
* `spec:ETH`: arcus step=1E-7 min=5 maker=0.00015 taker=0.00045 | hl coin=ETH step=0.0001 min=10 maker=0.00015 taker=0.00045
* `spec:SOL`: arcus step=0.000001 min=5 maker=0.00015 taker=0.00045 | hl coin=SOL step=0.01 min=10 maker=0.00015 taker=0.00045
* `started_ms`: 1795718523600
* `stats:arcus:BTC`: frames=50521 reconnects=0 gaps=0 integrity_errors=0 hb_confirmed=942 hb_mismatch=0 l2Book_checks_ok=0 l2Book_checks_bad=0 baseline_gap_resync=1
* `stats:arcus:ETH`: frames=93957 reconnects=0 gaps=0 integrity_errors=0 hb_confirmed=807 hb_mismatch=0 l2Book_checks_ok=0 l2Book_checks_bad=0 baseline_gap_resync=1
* `stats:arcus:SOL`: frames=69767 reconnects=0 gaps=0 integrity_errors=0 hb_confirmed=1013 hb_mismatch=0 l2Book_checks_ok=0 l2Book_checks_bad=0 baseline_gap_resync=1
* `stats:hyperliquid:BTC`: frames=1862 reconnects=0 gaps=0 integrity_errors=0 hb_confirmed=0 hb_mismatch=0 l2Book_checks_ok=1 l2Book_checks_bad=0 
* `stats:hyperliquid:ETH`: frames=1863 reconnects=0 gaps=0 integrity_errors=0 hb_confirmed=0 hb_mismatch=0 l2Book_checks_ok=1 l2Book_checks_bad=0 
* `stats:hyperliquid:SOL`: frames=1845 reconnects=0 gaps=0 integrity_errors=0 hb_confirmed=0 hb_mismatch=0 l2Book_checks_ok=1 l2Book_checks_bad=0 

| venue | symbol | event | count |
|---|---|---|---|
| arcus | BTC-USD | baseline | 2 |
| arcus | BTC-USD | baseline_gap_resync | 1 |
| arcus | BTC-USD | connected | 1 |
| arcus | ETH-USD | baseline | 2 |
| arcus | ETH-USD | baseline_gap_resync | 1 |
| arcus | ETH-USD | connected | 1 |
| arcus | SOL-USD | baseline | 2 |
| arcus | SOL-USD | baseline_gap_resync | 1 |
| arcus | SOL-USD | connected | 1 |
| hyperliquid | BTC | connected | 1 |
| hyperliquid | BTC | snapshot | 1 |
| hyperliquid | ETH | connected | 1 |
| hyperliquid | ETH | snapshot | 1 |
| hyperliquid | SOL | connected | 1 |
| hyperliquid | SOL | snapshot | 1 |
