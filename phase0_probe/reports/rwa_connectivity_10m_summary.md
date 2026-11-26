# Opportunity summary (read-only) — RWA connectivity test, NYSE CLOSED (Thanksgiving), Fri 2026-11-27 02:41-02:52 MYT

Window: 1795718524000 → 1795719123000 epoch ms (600 s). Per second the better direction is taken. **net_resid** = open VWAP spread − close slippage − open+close fees − 2 bps buffer − the rolling median basis (exit assumed at the rolling median of HL−Arcus mid basis, not at 0). Gating: `not_ready` (either book unproven / resyncing) and `stale` (network latency > threshold or silent connection); book idleness never gates.

| Symbol | Q $ | Mode | % s net_resid>0 | runs | avg dur s | max run s | max net_resid bps | median net_resid bps | % s net>0 (zero-conv., Phase 0) | median open spread bps | median basis bps | median abs residual bps | stale % | not_ready % | warm-up s | insuff. depth s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DRAM | 100 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -8.586 | -13.989 | 0.00 | -2.281 | 2.419 | 0.750 | 2.83 | 0.50 | 30 | 0 |
| DRAM | 100 | MAKER_ARCUS_TAKER_HL | 16.00 | 9 | 10.67 | 36 | 2.602 | -3.277 | 27.67 | 0.570 | 2.419 | 0.750 | 2.83 | 0.50 | 30 | 0 |
| DRAM | 100 | MAKER_HL_TAKER_ARCUS | 0.00 | 0 | n/a | 0 | -0.970 | -5.785 | 2.67 | 1.424 | 2.419 | 0.750 | 2.83 | 0.50 | 30 | 0 |
| DRAM | 500 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -9.014 | -14.380 | 0.00 | -3.077 | 2.419 | 0.750 | 2.83 | 0.50 | 30 | 0 |
| DRAM | 500 | MAKER_ARCUS_TAKER_HL | 13.67 | 12 | 6.83 | 36 | 1.187 | -3.858 | 23.83 | 0.000 | 2.419 | 0.750 | 2.83 | 0.50 | 30 | 0 |
| DRAM | 500 | MAKER_HL_TAKER_ARCUS | 0.00 | 0 | n/a | 0 | -0.970 | -5.819 | 1.33 | 1.424 | 2.419 | 0.750 | 2.83 | 0.50 | 30 | 0 |
| DRAM | 2000 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -10.520 | -15.613 | 0.00 | -4.704 | 2.419 | 0.750 | 2.83 | 0.50 | 30 | 0 |
| DRAM | 2000 | MAKER_ARCUS_TAKER_HL | 0.83 | 5 | 1.00 | 1 | 1.033 | -4.914 | 17.33 | -1.261 | 2.419 | 0.750 | 2.83 | 0.50 | 30 | 0 |
| DRAM | 2000 | MAKER_HL_TAKER_ARCUS | 0.00 | 0 | n/a | 0 | -0.970 | -6.244 | 0.83 | 1.424 | 2.419 | 0.750 | 2.83 | 0.50 | 30 | 0 |
| MU | 100 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -11.851 | -15.944 | 0.00 | 8.055 | 12.267 | 0.658 | 4.83 | 0.17 | 30 | 0 |
| MU | 100 | MAKER_ARCUS_TAKER_HL | 0.00 | 0 | n/a | 0 | -7.022 | -11.112 | 61.33 | 8.231 | 12.267 | 0.658 | 4.83 | 0.17 | 30 | 0 |
| MU | 100 | MAKER_HL_TAKER_ARCUS | 86.00 | 12 | 43.00 | 125 | 39.319 | 1.713 | 94.17 | 15.942 | 12.267 | 0.658 | 4.83 | 0.17 | 30 | 0 |
| MU | 500 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -12.513 | -15.974 | 0.00 | 8.052 | 12.267 | 0.658 | 4.83 | 0.17 | 30 | 0 |
| MU | 500 | MAKER_ARCUS_TAKER_HL | 0.00 | 0 | n/a | 0 | -7.585 | -11.124 | 60.83 | 8.231 | 12.267 | 0.658 | 4.83 | 0.17 | 30 | 0 |
| MU | 500 | MAKER_HL_TAKER_ARCUS | 86.00 | 12 | 43.00 | 125 | 39.319 | 1.661 | 94.17 | 15.893 | 12.267 | 0.658 | 4.83 | 0.17 | 30 | 0 |
| MU | 2000 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -12.662 | -16.113 | 0.00 | 7.986 | 12.267 | 0.658 | 4.83 | 0.17 | 30 | 0 |
| MU | 2000 | MAKER_ARCUS_TAKER_HL | 0.00 | 0 | n/a | 0 | -7.602 | -11.126 | 60.00 | 8.231 | 12.267 | 0.658 | 4.83 | 0.17 | 30 | 0 |
| MU | 2000 | MAKER_HL_TAKER_ARCUS | 85.83 | 13 | 39.62 | 125 | 39.051 | 1.471 | 94.17 | 15.846 | 12.267 | 0.658 | 4.83 | 0.17 | 30 | 0 |
| NBIS | 100 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -0.519 | -14.643 | 16.50 | -10.153 | 12.258 | 0.608 | 2.50 | 0.33 | 30 | 0 |
| NBIS | 100 | MAKER_ARCUS_TAKER_HL | 1.00 | 4 | 1.50 | 2 | 6.262 | -7.718 | 95.33 | -8.022 | 12.258 | 0.608 | 2.50 | 0.33 | 30 | 0 |
| NBIS | 100 | MAKER_HL_TAKER_ARCUS | 5.17 | 21 | 1.48 | 4 | 8.088 | -2.638 | 96.83 | -4.684 | 12.258 | 0.608 | 2.50 | 0.33 | 30 | 0 |
| NBIS | 500 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -1.385 | -15.209 | 6.67 | -11.736 | 12.258 | 0.608 | 2.50 | 0.33 | 30 | 0 |
| NBIS | 500 | MAKER_ARCUS_TAKER_HL | 0.33 | 2 | 1.00 | 1 | 5.396 | -8.181 | 93.83 | -10.281 | 12.258 | 0.608 | 2.50 | 0.33 | 30 | 0 |
| NBIS | 500 | MAKER_HL_TAKER_ARCUS | 5.00 | 21 | 1.43 | 4 | 8.088 | -2.708 | 96.83 | -5.168 | 12.258 | 0.608 | 2.50 | 0.33 | 30 | 0 |
| NBIS | 2000 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -3.922 | -15.997 | 3.33 | -12.415 | 12.258 | 0.608 | 2.50 | 0.33 | 30 | 0 |
| NBIS | 2000 | MAKER_ARCUS_TAKER_HL | 0.33 | 2 | 1.00 | 1 | 3.224 | -8.512 | 92.00 | -10.393 | 12.258 | 0.608 | 2.50 | 0.33 | 30 | 0 |
| NBIS | 2000 | MAKER_HL_TAKER_ARCUS | 3.17 | 14 | 1.36 | 3 | 7.408 | -3.331 | 96.50 | -5.661 | 12.258 | 0.608 | 2.50 | 0.33 | 30 | 0 |
| NVDA | 100 | DUAL_TAKER | 0.17 | 1 | 1.00 | 1 | 0.016 | -9.618 | 97.67 | -12.914 | 13.940 | 0.659 | 1.17 | 0.17 | 30 | 0 |
| NVDA | 100 | MAKER_ARCUS_TAKER_HL | 0.33 | 2 | 1.00 | 1 | 5.845 | -3.788 | 98.67 | -12.249 | 13.940 | 0.659 | 1.17 | 0.17 | 30 | 0 |
| NVDA | 100 | MAKER_HL_TAKER_ARCUS | 0.17 | 1 | 1.00 | 1 | 2.545 | -6.421 | 98.50 | -11.945 | 13.940 | 0.659 | 1.17 | 0.17 | 30 | 0 |
| NVDA | 500 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -0.270 | -9.830 | 97.33 | -13.303 | 13.940 | 0.659 | 1.17 | 0.17 | 30 | 0 |
| NVDA | 500 | MAKER_ARCUS_TAKER_HL | 0.33 | 2 | 1.00 | 1 | 5.558 | -3.803 | 98.50 | -12.638 | 13.940 | 0.659 | 1.17 | 0.17 | 30 | 0 |
| NVDA | 500 | MAKER_HL_TAKER_ARCUS | 0.17 | 1 | 1.00 | 1 | 2.545 | -6.423 | 98.50 | -11.945 | 13.940 | 0.659 | 1.17 | 0.17 | 30 | 0 |
| NVDA | 2000 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -1.129 | -10.297 | 93.83 | -13.521 | 13.940 | 0.659 | 1.17 | 0.17 | 30 | 0 |
| NVDA | 2000 | MAKER_ARCUS_TAKER_HL | 0.33 | 2 | 1.00 | 1 | 4.699 | -4.370 | 98.50 | -12.856 | 13.940 | 0.659 | 1.17 | 0.17 | 30 | 0 |
| NVDA | 2000 | MAKER_HL_TAKER_ARCUS | 0.17 | 1 | 1.00 | 1 | 2.545 | -6.424 | 98.50 | -11.945 | 13.940 | 0.659 | 1.17 | 0.17 | 30 | 0 |
| SNDK | 100 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -5.370 | -10.407 | 47.33 | -11.956 | 11.963 | 1.316 | 1.17 | 0.33 | 30 | 0 |
| SNDK | 100 | MAKER_ARCUS_TAKER_HL | 1.17 | 7 | 1.00 | 1 | 1.787 | -3.250 | 98.50 | -10.628 | 11.963 | 1.316 | 1.17 | 0.33 | 30 | 0 |
| SNDK | 100 | MAKER_HL_TAKER_ARCUS | 0.00 | 0 | n/a | 0 | -0.445 | -5.769 | 98.00 | -10.622 | 11.963 | 1.316 | 1.17 | 0.33 | 30 | 0 |
| SNDK | 500 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -6.662 | -11.531 | 24.83 | -12.462 | 11.963 | 1.316 | 1.17 | 0.33 | 30 | 0 |
| SNDK | 500 | MAKER_ARCUS_TAKER_HL | 0.33 | 2 | 1.00 | 1 | 0.500 | -4.351 | 98.33 | -11.134 | 11.963 | 1.316 | 1.17 | 0.33 | 30 | 0 |
| SNDK | 500 | MAKER_HL_TAKER_ARCUS | 0.00 | 0 | n/a | 0 | -0.445 | -5.769 | 98.00 | -10.622 | 11.963 | 1.316 | 1.17 | 0.33 | 30 | 0 |
| SNDK | 2000 | DUAL_TAKER | 0.00 | 0 | n/a | 0 | -7.402 | -13.493 | 2.00 | -13.292 | 11.963 | 1.316 | 1.17 | 0.33 | 30 | 0 |
| SNDK | 2000 | MAKER_ARCUS_TAKER_HL | 0.00 | 0 | n/a | 0 | -0.240 | -6.282 | 97.83 | -11.963 | 11.963 | 1.316 | 1.17 | 0.33 | 30 | 0 |
| SNDK | 2000 | MAKER_HL_TAKER_ARCUS | 0.00 | 0 | n/a | 0 | -0.445 | -5.771 | 98.00 | -10.623 | 11.963 | 1.316 | 1.17 | 0.33 | 30 | 0 |

## Funding (hourly rates, window means; predicted if available else current)

| Symbol | Arcus 1h | HL 1h | Arcus ann. | HL ann. | Δ ann. (HL−Arcus) | samples |
|---|---|---|---|---|---|---|
| DRAM | 0.00000475 | -0.00002526 | 0.0416 | -0.2213 | -0.2629 | 119 |
| MU | 0.00000475 | 0.00000625 | 0.0416 | 0.0548 | 0.0132 | 119 |
| NBIS | 0.00000475 | 0.00000550 | 0.0416 | 0.0482 | 0.0066 | 119 |
| NVDA | 0.00000475 | 0.00000625 | 0.0416 | 0.0548 | 0.0132 | 119 |
| SNDK | 0.00000475 | -0.00002133 | 0.0416 | -0.1869 | -0.2284 | 119 |

Δ = HL − Arcus. Positive: long Arcus / short HL receives carry; negative: short Arcus / long HL receives.

## Book / connection health (per 1 s sample)

| book | samples | not_ready % | latency p50 / p90 / max ms | % latency > 500 ms | book_idle p50 / p90 / max ms | conn silence p50 / max ms |
|---|---|---|---|---|---|---|
| DRAM/arcus | 600 | 0.50 | 141 / 214 / 302 | 0.00 | 638 / 2831 / 4951 | 115 / 1397 |
| DRAM/hyperliquid | 600 | 0.17 | 320 / 398 / 711 | 2.84 | 445 / 1858 / 8482 | 282 / 1080 |
| MU/arcus | 600 | 0.17 | 135 / 218 / 309 | 0.00 | 285 / 1372 / 4638 | 45 / 1218 |
| MU/hyperliquid | 600 | 0.17 | 328 / 433 / 656 | 4.84 | 2861 / 24861 / 65861 | 416 / 1112 |
| NBIS/arcus | 600 | 0.33 | 131 / 214 / 304 | 0.00 | 235 / 1347 / 9382 | 60 / 1259 |
| NBIS/hyperliquid | 600 | 0.17 | 331 / 401 / 665 | 2.67 | 339 / 1041 / 3948 | 245 / 1024 |
| NVDA/arcus | 600 | 0.17 | 98 / 207 / 299 | 0.00 | 124 / 569 / 2835 | 89 / 1189 |
| NVDA/hyperliquid | 600 | 0.17 | 306 / 354 / 530 | 1.17 | 321 / 874 / 3193 | 247 / 985 |
| SNDK/arcus | 600 | 0.33 | 137 / 216 / 314 | 0.00 | 112 / 1047 / 4413 | 17 / 1202 |
| SNDK/hyperliquid | 600 | 0.17 | 308 / 365 / 543 | 1.17 | 338 / 1165 / 3548 | 248 / 1028 |

## Meta / feed stats

* `arcus_clock_offset_ms`: -3 (rtt 188 ms; GET /v1/time; hyperliquid: no documented server-time endpoint -> uncorrected)
* `args`: --duration-s 600 --pair NVDA=io:NVDA --pair SNDK=io:SNDK --pair DRAM=io:DRAM --pair MU=io:MU --pair NBIS=io:NBIS --db reports/rwa_connectivity_10m.sqlite --log reports/rwa_connectivity_10m.log
* `ended_ms`: 1795719124743
* `spec:DRAM`: arcus step=1E-7 min=5 maker=0 taker=0.000225 | hl coin=io:DRAM step=0.01 min=10 maker=0.0000300 taker=0.0000900
* `spec:MU`: arcus step=1E-7 min=5 maker=0 taker=0.000225 | hl coin=io:MU step=0.001 min=10 maker=0.0000300 taker=0.0000900
* `spec:NBIS`: arcus step=1E-7 min=5 maker=0 taker=0.000225 | hl coin=io:NBIS step=0.01 min=10 maker=0.0000300 taker=0.0000900
* `spec:NVDA`: arcus step=1E-7 min=5 maker=0 taker=0.000225 | hl coin=io:NVDA step=0.001 min=10 maker=0.0000300 taker=0.0000900
* `spec:SNDK`: arcus step=1E-7 min=5 maker=0 taker=0.000225 | hl coin=io:SNDK step=0.0001 min=10 maker=0.0000300 taker=0.0000900
* `started_ms`: 1795718523643
* `stats:arcus:DRAM`: frames=6226 reconnects=0 gaps=0 integrity_errors=0 hb_confirmed=2006 hb_mismatch=0 l2Book_checks_ok=0 l2Book_checks_bad=0 
* `stats:arcus:MU`: frames=26716 reconnects=0 gaps=0 integrity_errors=0 hb_confirmed=1672 hb_mismatch=0 l2Book_checks_ok=0 l2Book_checks_bad=0 
* `stats:arcus:NBIS`: frames=22086 reconnects=0 gaps=0 integrity_errors=0 hb_confirmed=1698 hb_mismatch=0 l2Book_checks_ok=0 l2Book_checks_bad=0 
* `stats:arcus:NVDA`: frames=29175 reconnects=0 gaps=0 integrity_errors=0 hb_confirmed=1441 hb_mismatch=0 l2Book_checks_ok=0 l2Book_checks_bad=0 
* `stats:arcus:SNDK`: frames=26114 reconnects=0 gaps=0 integrity_errors=0 hb_confirmed=1365 hb_mismatch=0 l2Book_checks_ok=0 l2Book_checks_bad=0 
* `stats:hyperliquid:DRAM`: frames=1448 reconnects=0 gaps=0 integrity_errors=0 hb_confirmed=0 hb_mismatch=0 l2Book_checks_ok=1 l2Book_checks_bad=0 
* `stats:hyperliquid:MU`: frames=983 reconnects=0 gaps=0 integrity_errors=0 hb_confirmed=0 hb_mismatch=0 l2Book_checks_ok=1 l2Book_checks_bad=0 
* `stats:hyperliquid:NBIS`: frames=1617 reconnects=0 gaps=0 integrity_errors=0 hb_confirmed=0 hb_mismatch=0 l2Book_checks_ok=1 l2Book_checks_bad=0 
* `stats:hyperliquid:NVDA`: frames=1666 reconnects=0 gaps=0 integrity_errors=0 hb_confirmed=0 hb_mismatch=0 l2Book_checks_ok=1 l2Book_checks_bad=0 
* `stats:hyperliquid:SNDK`: frames=1616 reconnects=0 gaps=0 integrity_errors=0 hb_confirmed=0 hb_mismatch=0 l2Book_checks_ok=1 l2Book_checks_bad=0 

| venue | symbol | event | count |
|---|---|---|---|
| arcus | DRAM-USD | baseline | 1 |
| arcus | DRAM-USD | connected | 1 |
| arcus | MU-USD | baseline | 1 |
| arcus | MU-USD | connected | 1 |
| arcus | NBIS-USD | baseline | 1 |
| arcus | NBIS-USD | connected | 1 |
| arcus | NVDA-USD | baseline | 1 |
| arcus | NVDA-USD | connected | 1 |
| arcus | SNDK-USD | baseline | 1 |
| arcus | SNDK-USD | connected | 1 |
| hyperliquid | DRAM | connected | 1 |
| hyperliquid | DRAM | snapshot | 1 |
| hyperliquid | MU | connected | 1 |
| hyperliquid | MU | snapshot | 1 |
| hyperliquid | NBIS | connected | 1 |
| hyperliquid | NBIS | snapshot | 1 |
| hyperliquid | NVDA | connected | 1 |
| hyperliquid | NVDA | snapshot | 1 |
| hyperliquid | SNDK | connected | 1 |
| hyperliquid | SNDK | snapshot | 1 |
