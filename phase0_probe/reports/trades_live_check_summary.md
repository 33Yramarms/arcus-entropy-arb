# Opportunity summary (read-only) — PR #1.6 --record-trades live check (2 min, NYSE closed)

Window: 1795720293000 → 1795720412000 epoch ms (120 s). Per second the better direction is taken. **net_resid** = open VWAP spread − close slippage − open+close fees − 2 bps buffer − the rolling median basis (exit assumed at the rolling median of HL−Arcus mid basis, not at 0). Gating: `not_ready` (either book unproven / resyncing) and `stale` (network latency > threshold or silent connection); book idleness never gates.

| Symbol | Q $ | Mode | % s net_resid>0 | runs | avg dur s | max run s | max net_resid bps | median net_resid bps | % s net>0 (zero-conv., Phase 0) | median open spread bps | median basis bps | median abs residual bps | stale % | not_ready % | warm-up s | insuff. depth s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC | 100 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -18.594 | -19.836 | 0.00 | -7.240 | 7.563 | 0.345 | 0.00 | 0.83 | 30 | 0 |
| BTC | 100 | MAKER_ARCUS_TAKER_HL | 0.00 | 0 | n/a | 0 | -11.924 | -13.803 | 0.00 | -7.224 | 7.563 | 0.345 | 0.00 | 0.83 | 30 | 0 |
| BTC | 100 | MAKER_HL_TAKER_ARCUS | 0.00 | 0 | n/a | 0 | -11.900 | -13.506 | 0.00 | -7.075 | 7.563 | 0.345 | 0.00 | 0.83 | 30 | 0 |
| BTC | 500 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -18.594 | -19.849 | 0.00 | -7.240 | 7.563 | 0.345 | 0.00 | 0.83 | 30 | 0 |
| BTC | 500 | MAKER_ARCUS_TAKER_HL | 0.00 | 0 | n/a | 0 | -11.924 | -13.803 | 0.00 | -7.224 | 7.563 | 0.345 | 0.00 | 0.83 | 30 | 0 |
| BTC | 500 | MAKER_HL_TAKER_ARCUS | 0.00 | 0 | n/a | 0 | -11.900 | -13.506 | 0.00 | -7.075 | 7.563 | 0.345 | 0.00 | 0.83 | 30 | 0 |
| BTC | 2000 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -19.083 | -20.009 | 0.00 | -7.240 | 7.563 | 0.345 | 0.00 | 0.83 | 30 | 0 |
| BTC | 2000 | MAKER_ARCUS_TAKER_HL | 0.00 | 0 | n/a | 0 | -11.924 | -13.803 | 0.00 | -7.224 | 7.563 | 0.345 | 0.00 | 0.83 | 30 | 0 |
| BTC | 2000 | MAKER_HL_TAKER_ARCUS | 0.00 | 0 | n/a | 0 | -11.924 | -13.630 | 0.00 | -7.075 | 7.563 | 0.345 | 0.00 | 0.83 | 30 | 0 |
| MU | 100 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -14.778 | -15.927 | 0.00 | -15.916 | 12.183 | 0.411 | 0.83 | 0.83 | 30 | 0 |
| MU | 100 | MAKER_ARCUS_TAKER_HL | 0.00 | 0 | n/a | 0 | -9.868 | -11.098 | 45.00 | 7.547 | 12.183 | 0.411 | 0.83 | 0.83 | 30 | 0 |
| MU | 100 | MAKER_HL_TAKER_ARCUS | 67.50 | 3 | 27.00 | 60 | 3.479 | 2.314 | 98.33 | 15.752 | 12.183 | 0.411 | 0.83 | 0.83 | 30 | 0 |
| MU | 500 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -14.778 | -15.934 | 0.00 | -15.916 | 12.183 | 0.411 | 0.83 | 0.83 | 30 | 0 |
| MU | 500 | MAKER_ARCUS_TAKER_HL | 0.00 | 0 | n/a | 0 | -9.868 | -11.098 | 45.00 | 7.547 | 12.183 | 0.411 | 0.83 | 0.83 | 30 | 0 |
| MU | 500 | MAKER_HL_TAKER_ARCUS | 67.50 | 3 | 27.00 | 60 | 3.479 | 2.205 | 98.33 | 15.752 | 12.183 | 0.411 | 0.83 | 0.83 | 30 | 0 |
| MU | 2000 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -14.814 | -16.101 | 0.00 | -15.193 | 12.183 | 0.411 | 0.83 | 0.83 | 30 | 0 |
| MU | 2000 | MAKER_ARCUS_TAKER_HL | 0.00 | 0 | n/a | 0 | -9.978 | -11.098 | 45.00 | 7.547 | 12.183 | 0.411 | 0.83 | 0.83 | 30 | 0 |
| MU | 2000 | MAKER_HL_TAKER_ARCUS | 66.67 | 4 | 20.00 | 34 | 3.479 | 1.998 | 98.33 | 15.745 | 12.183 | 0.411 | 0.83 | 0.83 | 30 | 0 |
| NVDA | 100 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -6.970 | -9.628 | 96.67 | 13.028 | 13.941 | 0.660 | 1.67 | 0.83 | 30 | 0 |
| NVDA | 100 | MAKER_ARCUS_TAKER_HL | 0.00 | 0 | n/a | 0 | -1.142 | -3.565 | 97.50 | 13.941 | 13.941 | 0.660 | 1.67 | 0.83 | 30 | 0 |
| NVDA | 100 | MAKER_HL_TAKER_ARCUS | 0.00 | 0 | n/a | 0 | -3.451 | -5.781 | 97.50 | 13.943 | 13.941 | 0.660 | 1.67 | 0.83 | 30 | 0 |
| NVDA | 500 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -6.970 | -9.628 | 96.67 | 12.695 | 13.941 | 0.660 | 1.67 | 0.83 | 30 | 0 |
| NVDA | 500 | MAKER_ARCUS_TAKER_HL | 0.00 | 0 | n/a | 0 | -1.142 | -3.754 | 97.50 | 13.941 | 13.941 | 0.660 | 1.67 | 0.83 | 30 | 0 |
| NVDA | 500 | MAKER_HL_TAKER_ARCUS | 0.00 | 0 | n/a | 0 | -3.451 | -5.781 | 97.50 | 13.943 | 13.941 | 0.660 | 1.67 | 0.83 | 30 | 0 |
| NVDA | 2000 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -6.970 | -10.146 | 95.00 | 12.632 | 13.941 | 0.660 | 1.67 | 0.83 | 30 | 0 |
| NVDA | 2000 | MAKER_ARCUS_TAKER_HL | 0.00 | 0 | n/a | 0 | -1.142 | -3.799 | 97.50 | 13.941 | 13.941 | 0.660 | 1.67 | 0.83 | 30 | 0 |
| NVDA | 2000 | MAKER_HL_TAKER_ARCUS | 0.00 | 0 | n/a | 0 | -3.610 | -5.781 | 97.50 | 13.943 | 13.941 | 0.660 | 1.67 | 0.83 | 30 | 0 |

## Funding (hourly rates, window means; predicted if available else current)

| Symbol | Arcus 1h | HL 1h | Arcus ann. | HL ann. | Δ ann. (HL−Arcus) | samples |
|---|---|---|---|---|---|---|
| BTC | 0.00001250 | -0.00000022 | 0.1095 | -0.0019 | -0.1114 | 23 |
| MU | 0.00000475 | 0.00000625 | 0.0416 | 0.0548 | 0.0132 | 23 |
| NVDA | 0.00000475 | 0.00000625 | 0.0416 | 0.0548 | 0.0132 | 23 |

Δ = HL − Arcus. Positive: long Arcus / short HL receives carry; negative: short Arcus / long HL receives.

## Book / connection health (per 1 s sample)

| book | samples | not_ready % | latency p50 / p90 / max ms | % latency > 500 ms | book_idle p50 / p90 / max ms | conn silence p50 / max ms |
|---|---|---|---|---|---|---|
| BTC/arcus | 120 | 0.83 | 107 / 154 / 239 | 0.00 | 19 / 104 / 479 | 19 / 479 |
| BTC/hyperliquid | 120 | 0.00 | 299 / 349 / 741 | 0.83 | 257 / 487 / 590 | 177 / 590 |
| MU/arcus | 120 | 0.83 | 125 / 212 / 317 | 0.00 | 212 / 819 / 1734 | 76 / 975 |
| MU/hyperliquid | 120 | 0.83 | 318 / 351 / 543 | 0.84 | 2732 / 15754 / 23212 | 402 / 1194 |
| NVDA/arcus | 120 | 0.83 | 125 / 228 / 259 | 0.00 | 111 / 661 / 2534 | 28 / 673 |
| NVDA/hyperliquid | 120 | 0.83 | 316 / 375 / 527 | 1.68 | 326 / 749 / 1854 | 223 / 889 |

## Maker-Taker realism (PR #1.6) — fill-through window 5 s, touch or through

Trades table present: arcus/BTC 19, arcus/MU 5, arcus/NVDA 35, hyperliquid/BTC 217, hyperliquid/NVDA 31 trades.

| Symbol | Q $ | Mode | opp s raw | runs raw | max run raw | opp s filtered | runs filtered | max run filt. | suppressed % | evidence trade / book | adverse +1s / +3s / +5s bps (triggers, n) | adverse +1s / +3s / +5s bps (unfiltered triggers, n) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MU | 100 | MAKER_HL_TAKER_ARCUS | 81 | 3 | 60 | 0 | 0 | 0 | 100.0 | 0 / 0 | n/a / n/a / n/a (n=0) | 0.00 / -0.11 / -0.16 (n=3) |
| MU | 500 | MAKER_HL_TAKER_ARCUS | 81 | 3 | 60 | 0 | 0 | 0 | 100.0 | 0 / 0 | n/a / n/a / n/a (n=0) | 0.00 / -0.01 / -0.10 (n=3) |
| MU | 2000 | MAKER_HL_TAKER_ARCUS | 80 | 4 | 34 | 0 | 0 | 0 | 100.0 | 0 / 0 | n/a / n/a / n/a (n=0) | 0.04 / 0.19 / 0.40 (n=4) |

Adverse = move of the hedge (taker) leg's executable price against us after the signal (positive = worse). Triggers = first second of each run of valid seconds.

### Trade side consistency (TODO: VERIFY_FROM_DOCS side semantics)

| venue/raw side | trades | with 1 Hz mid | % at/above mid |
|---|---|---|---|
| arcus/BUY | 30 | 30 | 96.7 |
| arcus/SELL | 29 | 29 | 0.0 |
| hyperliquid/A | 148 | 148 | 5.4 |
| hyperliquid/B | 100 | 100 | 98.0 |

## Meta / feed stats

* `arcus_clock_offset_ms`: 4 (rtt 182 ms; GET /v1/time; hyperliquid: no documented server-time endpoint -> uncorrected)
* `args`: --duration-s 120 --pair NVDA=io:NVDA --pair MU=io:MU --pair BTC=BTC --record-trades --db reports/trades_live_check.sqlite --log reports/trades_live_check.log
* `ended_ms`: 1795720413728
* `record_trades`: 1
* `spec:BTC`: arcus step=1E-8 min=5 maker=0.00015 taker=0.00045 | hl coin=BTC step=0.00001 min=10 maker=0.00015 taker=0.00045
* `spec:MU`: arcus step=1E-7 min=5 maker=0 taker=0.000225 | hl coin=io:MU step=0.001 min=10 maker=0.0000300 taker=0.0000900
* `spec:NVDA`: arcus step=1E-7 min=5 maker=0 taker=0.000225 | hl coin=io:NVDA step=0.001 min=10 maker=0.0000300 taker=0.0000900
* `started_ms`: 1795720292614
* `stats:arcus:BTC`: frames=8165 reconnects=0 gaps=0 integrity_errors=0 hb_confirmed=212 hb_mismatch=0 l2Book_checks_ok=0 l2Book_checks_bad=0 baseline_gap_resync=1 baseline_retry=1 trades=19
* `stats:arcus:MU`: frames=4819 reconnects=0 gaps=0 integrity_errors=0 hb_confirmed=321 hb_mismatch=0 l2Book_checks_ok=0 l2Book_checks_bad=0 trades=5
* `stats:arcus:NVDA`: frames=6679 reconnects=0 gaps=0 integrity_errors=0 hb_confirmed=288 hb_mismatch=0 l2Book_checks_ok=0 l2Book_checks_bad=0 trades=35
* `stats:hyperliquid:BTC`: frames=502 reconnects=0 gaps=0 integrity_errors=0 hb_confirmed=0 hb_mismatch=0 l2Book_checks_ok=1 l2Book_checks_bad=0 trades=248
* `stats:hyperliquid:MU`: frames=205 reconnects=0 gaps=0 integrity_errors=0 hb_confirmed=0 hb_mismatch=0 l2Book_checks_ok=0 l2Book_checks_bad=0 trades=30
* `stats:hyperliquid:NVDA`: frames=372 reconnects=0 gaps=0 integrity_errors=0 hb_confirmed=0 hb_mismatch=0 l2Book_checks_ok=1 l2Book_checks_bad=0 trades=61
* `trades_recorded`: received=398 new_rows=398

| venue | symbol | event | count |
|---|---|---|---|
| arcus | BTC-USD | baseline | 2 |
| arcus | BTC-USD | baseline_gap_resync | 1 |
| arcus | BTC-USD | connected | 1 |
| arcus | MU-USD | baseline | 1 |
| arcus | MU-USD | connected | 1 |
| arcus | NVDA-USD | baseline | 2 |
| arcus | NVDA-USD | connected | 1 |
| hyperliquid | BTC | connected | 1 |
| hyperliquid | BTC | snapshot | 1 |
| hyperliquid | MU | connected | 1 |
| hyperliquid | MU | snapshot | 1 |
| hyperliquid | NVDA | connected | 1 |
| hyperliquid | NVDA | snapshot | 1 |
