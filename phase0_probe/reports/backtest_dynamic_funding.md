# PR #1.7 — dynamic funding-differential back-test (Arcus × io, 10 US-equity perps)

Data: live · generated 2026-11-26T15:20:24-05:00 · aligned hourly payments only. Read-only, zero keys, Decimal only.

**Timing (no look-ahead):** decision for payment *i* uses realized diffs up to *i−1* only; a position opened at decision *i* earns payment *i* onward; closing at *i* forfeits payment *i*. Costs: half the round trip at open, half at close; open positions force-closed (with cost) at data end. Re-entry earliest one hour after a close.

**Exit_apr semantics:** direction-aware — close when `dir × rolling_apr ≤ exit_apr` (0 % = rolling crossed zero / turned against us), or when the last 2 hourly diffs are both against the position, or (B) at the window boundary, or on a data gap.

**Capital per $1 notional per leg** = Arcus off-hours IMF × 1.5 + (1 / io maxLeverage) × 1.5. ROE (annualized) = net / capital × 8760 / own-sample hours; portfolio = equal capital, always allocated (mean of symbol ROEs).

## Sample & capital

| Sym | aligned h | first (ET) | gaps | Arcus off IMF | io maxLev | capital / $1 notional | lev on capital |
|---|---|---|---|---|---|---|---|
| NVDA | 720 | 2026-10-27T17:00 | 0h | 0.075 | 25 | 0.1725 | 5.80× |
| SNDK | 712 | 2026-10-27T17:00 | 8h | 0.150 | 15 | 0.3250 | 3.08× |
| MU | 149 | 2026-11-20T11:00 | 0h | 0.150 | 15 | 0.3250 | 3.08× |
| DRAM | 720 | 2026-10-27T17:00 | 0h | 0.150 | 25 | 0.2850 | 3.51× |
| NBIS | 720 | 2026-10-27T17:00 | 0h | 0.300 | 15 | 0.5500 | 1.82× |
| AAPL | 578 | 2026-11-02T14:00 | 0h | 0.075 | 25 | 0.1725 | 5.80× |
| CRCL | 556 | 2026-11-03T12:00 | 0h | 0.150 | 15 | 0.3250 | 3.08× |
| GOOGL | 53 | 2026-11-24T11:00 | 0h | 0.075 | 25 | 0.1725 | 5.80× |
| META | 197 | 2026-11-18T11:00 | 0h | 0.075 | 25 | 0.1725 | 5.80× |
| INTC | 221 | 2026-11-17T11:00 | 0h | 0.150 | 15 | 0.3250 | 3.08× |

Short history (annualized over own sample, high variance): MU 149h, GOOGL 53h, META 197h, INTC 221h

## Arcus pin check (is Arcus funding really pinned in the off-hours window?)

| Sym | off-window h | Arcus mean / min / max APR % | distinct | io mean APR % (off) | Arcus mean APR % (in RTH window) |
|---|---|---|---|---|---|
| NVDA | 380 | 4.95 / -22.62 / 148.53 | 13 | 10.82 | 16.78 |
| SNDK | 372 | 4.68 / -12.84 / 70.69 | 12 | 6.21 | 24.93 |
| MU | 91 | 5.09 / -5.84 / 70.63 | 5 | 3.17 | 20.66 |
| DRAM | 380 | 5.16 / -26.14 / 144.70 | 14 | 7.59 | 25.86 |
| NBIS | 380 | 4.73 / 4.44 / 63.21 | 12 | 11.75 | 18.43 |
| AAPL | 299 | 4.33 / -34.63 / 58.02 | 14 | 4.23 | -5.42 |
| CRCL | 291 | 4.59 / -3.77 / 45.50 | 11 | -14.30 | 15.69 |
| GOOGL | 27 | 4.50 / 4.48 / 4.50 | 2 | 7.69 | -3.49 |
| META | 107 | 4.37 / -6.57 / 4.50 | 5 | 6.40 | -9.37 |
| INTC | 115 | 4.49 / 4.46 / 6.09 | 6 | 11.17 | 3.87 |

## Portfolio grid — strategy A, optimistic_2.8bps

| K | entry | exit | opens | avg hold h | gross bps | cost bps | net bps | ROE ann % | +syms | worst trade bps |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 12% | 0% | 421 | 7.3 | 63.96 | 117.88 | -53.92 | -38.19 | 1/10 | -7.55 |
| 1 | 12% | 4% | 582 | 4.1 | 59.16 | 162.96 | -103.80 | -78.30 | 0/10 | -7.55 |
| 1 | 18% | 0% | 360 | 7.6 | 60.78 | 100.80 | -40.02 | -25.55 | 2/10 | -7.55 |
| 1 | 18% | 4% | 469 | 4.4 | 55.76 | 131.32 | -75.56 | -52.67 | 0/10 | -7.55 |
| 1 | 25% | 0% | 291 | 7.8 | 56.68 | 81.48 | -24.80 | -16.03 | 2/10 | -7.55 |
| 1 | 25% | 4% | 365 | 4.7 | 51.59 | 102.20 | -50.61 | -37.01 | 1/10 | -7.55 |
| 1 | 35% | 0% | 216 | 8.2 | 48.25 | 60.48 | -12.23 | -5.84 | 4/10 | -7.55 |
| 1 | 35% | 4% | 254 | 4.9 | 42.29 | 71.12 | -28.83 | -17.99 | 3/10 | -7.55 |
| 3 | 12% | 0% | 266 | 11.7 | 58.12 | 74.48 | -16.36 | -10.29 | 3/10 | -7.24 |
| 3 | 12% | 4% | 309 | 8.2 | 55.69 | 86.52 | -30.83 | -21.66 | 2/10 | -7.24 |
| 3 | 18% | 0% | 219 | 11.8 | 53.53 | 61.32 | -7.79 | -5.71 | 4/10 | -7.24 |
| 3 | 18% | 4% | 247 | 8.6 | 50.72 | 69.16 | -18.44 | -13.88 | 2/10 | -7.24 |
| 3 | 25% | 0% | 173 | 12.4 | 47.43 | 48.44 | -1.01 | 1.34 | 5/10 | -7.24 |
| 3 | 25% | 4% | 188 | 8.9 | 43.99 | 52.64 | -8.65 | -4.89 | 3/10 | -7.24 |
| 3 | 35% | 0% | 112 | 12.7 | 36.13 | 31.36 | 4.77 | 2.34 | 7/10 | -7.24 |
| 3 | 35% | 4% | 116 | 9.2 | 33.36 | 32.48 | 0.88 | -0.84 | 4/10 | -7.24 |

## Portfolio grid — strategy A, conservative_8.3bps

| K | entry | exit | opens | avg hold h | gross bps | cost bps | net bps | ROE ann % | +syms | worst trade bps |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 12% | 0% | 421 | 7.3 | 63.96 | 349.43 | -285.47 | -200.51 | 0/10 | -13.05 |
| 1 | 12% | 4% | 582 | 4.1 | 59.16 | 483.06 | -423.90 | -312.80 | 0/10 | -13.05 |
| 1 | 18% | 0% | 360 | 7.6 | 60.78 | 298.80 | -238.02 | -159.46 | 0/10 | -13.05 |
| 1 | 18% | 4% | 469 | 4.4 | 55.76 | 389.27 | -333.51 | -232.70 | 0/10 | -13.05 |
| 1 | 25% | 0% | 291 | 7.8 | 56.68 | 241.53 | -184.85 | -125.84 | 0/10 | -13.05 |
| 1 | 25% | 4% | 365 | 4.7 | 51.59 | 302.95 | -251.36 | -180.30 | 0/10 | -13.05 |
| 1 | 35% | 0% | 216 | 8.2 | 48.25 | 179.28 | -131.03 | -84.99 | 0/10 | -13.05 |
| 1 | 35% | 4% | 254 | 4.9 | 42.29 | 210.82 | -168.53 | -111.42 | 0/10 | -13.05 |
| 3 | 12% | 0% | 266 | 11.7 | 58.12 | 220.78 | -162.66 | -109.54 | 0/10 | -12.74 |
| 3 | 12% | 4% | 309 | 8.2 | 55.69 | 256.47 | -200.78 | -139.70 | 0/10 | -12.74 |
| 3 | 18% | 0% | 219 | 11.8 | 53.53 | 181.77 | -128.24 | -88.98 | 0/10 | -12.74 |
| 3 | 18% | 4% | 247 | 8.6 | 50.72 | 205.01 | -154.29 | -110.00 | 0/10 | -12.74 |
| 3 | 25% | 0% | 173 | 12.4 | 47.43 | 143.59 | -96.16 | -59.81 | 0/10 | -12.74 |
| 3 | 25% | 4% | 188 | 8.9 | 43.99 | 156.04 | -112.05 | -73.30 | 0/10 | -12.74 |
| 3 | 35% | 0% | 112 | 12.7 | 36.13 | 92.96 | -56.83 | -42.64 | 1/10 | -12.74 |
| 3 | 35% | 4% | 116 | 9.2 | 33.36 | 96.28 | -62.92 | -48.07 | 0/10 | -12.74 |

## Portfolio grid — strategy B, optimistic_2.8bps

| K | entry | exit | opens | avg hold h | gross bps | cost bps | net bps | ROE ann % | +syms | worst trade bps |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 12% | 0% | 203 | 6.5 | 29.30 | 56.84 | -27.54 | -25.10 | 1/10 | -4.37 |
| 1 | 12% | 4% | 261 | 3.6 | 26.93 | 73.08 | -46.15 | -41.47 | 1/10 | -4.37 |
| 1 | 18% | 0% | 172 | 6.0 | 26.75 | 48.16 | -21.41 | -19.39 | 1/10 | -4.37 |
| 1 | 18% | 4% | 198 | 3.7 | 24.72 | 55.44 | -30.72 | -27.73 | 1/10 | -4.37 |
| 1 | 25% | 0% | 140 | 6.0 | 24.84 | 39.20 | -14.36 | -14.06 | 1/10 | -4.37 |
| 1 | 25% | 4% | 157 | 3.9 | 23.08 | 43.96 | -20.88 | -20.32 | 1/10 | -4.37 |
| 1 | 35% | 0% | 106 | 5.6 | 21.07 | 29.68 | -8.61 | -7.05 | 1/10 | -4.37 |
| 1 | 35% | 4% | 110 | 4.0 | 19.80 | 30.80 | -11.00 | -8.23 | 1/10 | -4.37 |
| 3 | 12% | 0% | 169 | 8.1 | 27.90 | 47.32 | -19.42 | -19.89 | 1/10 | -4.37 |
| 3 | 12% | 4% | 182 | 5.8 | 26.29 | 50.96 | -24.67 | -23.34 | 1/10 | -4.37 |
| 3 | 18% | 0% | 139 | 7.8 | 25.34 | 38.92 | -13.58 | -15.65 | 1/10 | -4.37 |
| 3 | 18% | 4% | 145 | 5.8 | 23.97 | 40.60 | -16.63 | -17.19 | 1/10 | -4.37 |
| 3 | 25% | 0% | 102 | 7.8 | 21.90 | 28.56 | -6.66 | -5.31 | 1/10 | -4.37 |
| 3 | 25% | 4% | 105 | 5.7 | 20.50 | 29.40 | -8.90 | -6.91 | 1/10 | -4.37 |
| 3 | 35% | 0% | 57 | 7.9 | 17.05 | 15.96 | 1.09 | -1.19 | 2/10 | -3.72 |
| 3 | 35% | 4% | 57 | 6.0 | 16.38 | 15.96 | 0.42 | -1.27 | 2/10 | -3.72 |

## Portfolio grid — strategy B, conservative_8.3bps

| K | entry | exit | opens | avg hold h | gross bps | cost bps | net bps | ROE ann % | +syms | worst trade bps |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 12% | 0% | 203 | 6.5 | 29.30 | 168.49 | -139.19 | -107.40 | 0/10 | -9.87 |
| 1 | 12% | 4% | 261 | 3.6 | 26.93 | 216.63 | -189.70 | -153.41 | 0/10 | -9.87 |
| 1 | 18% | 0% | 172 | 6.0 | 26.75 | 142.76 | -116.01 | -86.23 | 0/10 | -9.87 |
| 1 | 18% | 4% | 198 | 3.7 | 24.72 | 164.34 | -139.62 | -108.34 | 0/10 | -9.87 |
| 1 | 25% | 0% | 140 | 6.0 | 24.84 | 116.20 | -91.36 | -68.13 | 0/10 | -9.87 |
| 1 | 25% | 4% | 157 | 3.9 | 23.08 | 130.31 | -107.23 | -84.55 | 0/10 | -9.87 |
| 1 | 35% | 0% | 106 | 5.6 | 21.07 | 87.98 | -66.91 | -42.88 | 0/10 | -9.87 |
| 1 | 35% | 4% | 110 | 4.0 | 19.80 | 91.30 | -71.50 | -45.07 | 0/10 | -9.87 |
| 3 | 12% | 0% | 169 | 8.1 | 27.90 | 140.27 | -112.37 | -90.98 | 0/10 | -9.87 |
| 3 | 12% | 4% | 182 | 5.8 | 26.29 | 151.06 | -124.77 | -99.29 | 0/10 | -9.87 |
| 3 | 18% | 0% | 139 | 7.8 | 25.34 | 115.37 | -90.03 | -74.86 | 0/10 | -9.87 |
| 3 | 18% | 4% | 145 | 5.8 | 23.97 | 120.35 | -96.38 | -78.76 | 0/10 | -9.87 |
| 3 | 25% | 0% | 102 | 7.8 | 21.90 | 84.66 | -62.76 | -38.84 | 0/10 | -9.87 |
| 3 | 25% | 4% | 105 | 5.7 | 20.50 | 87.15 | -66.65 | -42.22 | 0/10 | -9.87 |
| 3 | 35% | 0% | 57 | 7.9 | 17.05 | 47.31 | -30.26 | -20.71 | 1/10 | -9.22 |
| 3 | 35% | 4% | 57 | 6.0 | 16.38 | 47.31 | -30.93 | -20.78 | 1/10 | -9.22 |

## Best params (in-sample, by portfolio ROE)

* A|optimistic_2.8bps: A K=3 entry=35% exit=0% → ROE 2.34 %/yr, net 4.77 bps (mean per symbol)
* A|conservative_8.3bps: A K=3 entry=35% exit=0% → ROE -42.64 %/yr, net -56.83 bps (mean per symbol)
* B|optimistic_2.8bps: B K=3 entry=35% exit=0% → ROE -1.19 %/yr, net 1.09 bps (mean per symbol)
* B|conservative_8.3bps: B K=3 entry=35% exit=0% → ROE -20.71 %/yr, net -30.26 bps (mean per symbol)

## Per symbol — best A at conservative cost (A K=3 entry=35% exit=0%)

| Sym | h | opens | avg hold h | gross bps | cost bps | net bps | ROE ann % | ROE while deployed % | max loss bps | closes by reason |
|---|---|---|---|---|---|---|---|---|---|---|
| NVDA | 720 | 17 | 13.5 | 57.44 | 141.10 | -83.66 | -59.00 | -184.71 | -8.48 | reversal_2h:2, reverted:15 |
| SNDK | 712 | 17 | 13.9 | 51.55 | 141.10 | -89.55 | -33.90 | -102.27 | -9.22 | data_gap:1, end_of_data:1, reversal_2h:4, reverted:11 |
| MU | 149 | 5 | 12.4 | 8.25 | 41.50 | -33.25 | -60.15 | -144.56 | -8.40 | end_of_data:1, reversal_2h:1, reverted:3 |
| DRAM | 720 | 16 | 13.6 | 36.46 | 132.80 | -96.34 | -41.13 | -135.84 | -8.57 | end_of_data:1, reversal_2h:4, reverted:11 |
| NBIS | 720 | 17 | 12.7 | 49.74 | 141.10 | -91.36 | -20.21 | -67.37 | -8.58 | end_of_data:1, reversal_2h:6, reverted:10 |
| AAPL | 578 | 19 | 4.8 | 10.69 | 157.70 | -147.01 | -129.16 | -811.48 | -12.74 | end_of_data:1, reversal_2h:8, reverted:10 |
| CRCL | 556 | 15 | 13.8 | 114.36 | 124.50 | -10.14 | -4.92 | -13.20 | -9.33 | end_of_data:1, reversal_2h:3, reverted:11 |
| GOOGL | 53 | 1 | 23.0 | 3.78 | 8.30 | -4.52 | -43.34 | -99.88 | -4.52 | reverted:1 |
| META | 197 | 3 | 19.3 | 10.66 | 24.90 | -14.24 | -36.71 | -124.70 | -8.50 | reverted:3 |
| INTC | 221 | 2 | 41.0 | 18.37 | 16.60 | 1.77 | 2.16 | 5.82 | -6.64 | reverted:2 |

## Per symbol — best B at conservative cost (B K=3 entry=35% exit=0%)

| Sym | h | opens | avg hold h | gross bps | cost bps | net bps | ROE ann % | ROE while deployed % | max loss bps | closes by reason |
|---|---|---|---|---|---|---|---|---|---|---|
| NVDA | 720 | 9 | 6.0 | 18.26 | 74.70 | -56.44 | -39.80 | -530.73 | -8.32 | reversal_2h:1, reverted:2, window_end:6 |
| SNDK | 712 | 10 | 11.9 | 18.79 | 83.00 | -64.21 | -24.31 | -145.44 | -9.22 | end_of_data:1, reversal_2h:1, reverted:3, window_end:5 |
| MU | 149 | 4 | 4.0 | 1.57 | 33.20 | -31.63 | -57.21 | -532.79 | -8.84 | end_of_data:1, reversal_2h:1, reverted:1, window_end:1 |
| DRAM | 720 | 7 | 5.7 | 12.45 | 58.10 | -45.65 | -19.49 | -350.82 | -8.32 | end_of_data:1, reversal_2h:1, window_end:5 |
| NBIS | 720 | 12 | 8.0 | 25.19 | 99.60 | -74.41 | -16.46 | -123.46 | -8.42 | end_of_data:1, reversal_2h:2, reverted:2, window_end:7 |
| AAPL | 578 | 6 | 3.2 | 7.84 | 49.80 | -41.96 | -36.86 | -1121.42 | -8.35 | end_of_data:1, reversal_2h:3, reverted:1, window_end:1 |
| CRCL | 556 | 7 | 13.0 | 82.19 | 58.10 | 24.09 | 11.68 | 71.34 | -8.77 | end_of_data:1, reversal_2h:1, reverted:2, window_end:3 |
| GOOGL | 53 | 0 | n/a | 0.00 | 0.00 | 0.00 | 0.00 | n/a | 0.00 |  |
| META | 197 | 1 | 8.0 | 1.28 | 8.30 | -7.02 | -18.08 | -445.32 | -7.02 | window_end:1 |
| INTC | 221 | 1 | 8.0 | 2.97 | 8.30 | -5.33 | -6.51 | -179.72 | -5.33 | window_end:1 |

## Crude out-of-sample check (choose on first half, evaluate on second half, per symbol chronological 50/50)

| strategy / tier | chosen on 1st half | ROE 1st half % | same params ROE 2nd half % | best-in-hindsight 2nd half % |
|---|---|---|---|---|
| A / optimistic_2.8bps | A K=3 entry=35% exit=0% | 2.93 | 0.91 | 0.91 (A K=3 entry=35% exit=0%) |
| A / conservative_8.3bps | A K=3 entry=35% exit=0% | -47.56 | -39.51 | -39.51 (A K=3 entry=35% exit=0%) |
| B / optimistic_2.8bps | B K=3 entry=35% exit=0% | 3.98 | -7.01 | -7.01 (B K=3 entry=35% exit=0%) |
| B / conservative_8.3bps | B K=3 entry=35% exit=0% | -8.67 | -33.84 | -33.84 (B K=3 entry=35% exit=0%) |

## Caveats

* Best parameters are selected IN-SAMPLE on the same ≤30 days (16 combos × 2 strategies): expect the reported best ROE to be optimistic; see the 50/50 out-of-sample table.
* Short histories (GOOGL/MU/META/INTC) are annualized over their own few days — a handful of trades drives the number.
* Funding only: no price-basis P&L between the two legs (entry/exit basis, the ~10-17 bps oracle gap can move against you), no liquidation / ADL / margin-call risk, no funding of idle collateral.
* Costs are flat per-round-trip tiers (2.8 / 8.3 bps incl. slippage) — real slippage on io (thin books, $10 min notional TODO: VERIFY_FROM_DOCS) may exceed this at size.
* Arcus off-hours window = 20:00–04:00 ET + weekends + NYSE holidays (PR #1.6 calendar); whether Arcus shortens its window on early-close days is [待实测确认].
* HL hourly rate becomes known only at settlement; the strategy never uses the in-progress premium (conservative). Arcus' pinned off-hours rate is also NOT assumed known in advance.
* Break-even holding time at a constant differential = round trip / (APR / 8760): at 35 %/yr 20.8 h (8.3 bps) / 7.0 h (2.8 bps); at 12 %/yr 60.6 h / 20.4 h.
* Arcus pin check: inside the off-hours window Arcus is pinned at ~4.5 %/yr (SOFR + 0.5 %) on weekends, NYSE holidays and 21:00–03:00 ET stamps, but the weekday 04:00 ET stamp (accrual 03:00–04:00) is un-pinned in a minority of days (see pin table max/min) [待实测确认: Arcus stamp vs accrual convention].
* Data gaps (missing hour on either venue) force-close an open position with cost and are not credited.
