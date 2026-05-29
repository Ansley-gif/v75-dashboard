# Strategy Test Report — Every Pattern, Every Symbol

> ## ⚠️ STALE — DO NOT RELY ON THE NUMBERS BELOW
>
> Every expectancy figure in this document was produced by `PatternScanner.py`
> running with **no broker friction modelled** (spread=0, stops_level=0,
> slippage=0). After the 2026-05-22 EA blowup we discovered two bugs that
> invalidated these results:
>
> 1. **Broker stops_level widens SL** from 500 → 707 ticks, making R:R worse than designed
> 2. **Scanner `eff_tp` was wrong direction**: spread *added* to TP distance, not subtracted
>
> Once both fixes were applied, **Pattern 9's honest expectancy collapsed
> from +0.841R/trade → −0.406R/trade**. Every pattern in this document is now
> negative under broker reality, EXCEPT the surviving config:
>
> **Pattern 9 with SL=2000 / TP=6000 + 13:00 UTC hour filter** = +0.122R/trade
> backtest, 4 of 4 non-overlapping 2-month windows positive.
>
> ### Where to find current numbers:
> - **`MODEL_FINDINGS_2026-05-26.md`** — winning model spec, cross-window data, $-frame forecast
> - **`DIAGNOSIS_2026-05-22.md`** — how the original +0.841R fell apart
> - **`CHANGELOG.md`** — Phase 9 entry summarises the rewrite
>
> The body of this file is preserved as a historical record of what the
> original (buggy) scanner reported. **Do not deploy any strategy whose
> numbers come from this file alone.**

---

## TL;DR — what to trade

| Symbol | Best Strategy | Expectancy | Verdict |
|---|---|---|---|
| **V25 (R_25)** | **Pattern 9 — OC + ICT sessions, M5 trigger** | **+0.841R / trade** | ✅ **Trade this** |
| V10 (R_10) | Pattern 7B (needs re-verify at broker scale) | +0.811R native | 🔄 Re-test required |
| V50 (R_50) | None | All negative | ❌ Skip |
| V75 (R_75) | None | broker stops too wide | ❌ Skip |

---

## The 10 patterns tested

### Pattern 1 — Session H/L Breakout
**Logic:** First 12 bars of a session define a frozen H/L range. After that, any close beyond the range = entry.

**V25 result:** 62.2% WR, +0.793R/trade, 1,070 trades. Positive but lower trade count than OC patterns.

### Pattern 2 — London Breakout of Asian Range
**Logic:** Asian session forms a range. At London open (08:00–10:00 UTC) the first close OUTSIDE that range = entry. SL on opposite side of Asian range.

**V25 result:** 97.8% WR but only +0.007R/trade. High win rate but R:R is tiny (~0.03R per win). Not enough edge to be tradeable.

### Pattern 3 — NY Open Reversal (Judas Swing)
**Logic:** Track London's directional bias by 12:00 UTC. At NY open (13:00–15:00 UTC) look for price to REVERSE the London bias (the "Judas swing"). SL on London H/L.

**V25 result:** 80.7% WR, +0.236R/trade, 238 trades. Positive but limited signals (only 1 trade window per day).

### Pattern 4 — Opening Range Breakout (30-min ORB)
**Logic:** First 6 M5 candles of each session = the ORB. Trade the first close outside the ORB range.

**V25 result:** 89.3% WR but −0.009R/trade. High WR but partial-R wins don't cover full-R losses. Skip.

### Pattern 5 — Consolidation Squeeze Breakout
**Logic:** 8-bar tight range (range < 0.45 × ATR14) gets broken explosively.

**V25 result:** No trades produced — V25's volatility profile doesn't generate these squeezes often enough to register.

### Pattern 6 — Previous Session Level Run
**Logic:** Enter when current price tags a PREVIOUS session's H or L within 0.15×ATR. Continuation play on liquidity grab.

**V25 result:** 61.6% WR, +0.774R/trade, 633 trades. Decent edge, could be layered with Pattern 9.

### Pattern 7A — OC Candle Breakout, candle-extreme SL
**Logic:** Mark the 6 OC/CC candles per day. Trade breakouts of their H/L. SL at breakout candle's opposite extreme.

**V25 result:** 74.1% WR but only +0.001R/trade. Variable wide SL kills R-multiples on big bars.

### Pattern 7B — OC Candle Breakout, FIXED SL
**Logic:** Same as 7A but SL is fixed at the configured tick distance.

**V25 result:** 61.2% WR, +0.762R/trade, 2,672 trades. **Robust, simple, profitable.** This was the V25 baseline before ICT session times came in.

### Pattern 7C — OC Candle Breakout, tighter of (candle, fixed)
**Logic:** Whichever of (candle extreme, fixed-tick distance) is closer to entry.

**V25 result:** Identical to 7B in practice (+0.762R). On V25 the candle extreme is almost always further than 500 ticks, so the fixed-tick limit dominates.

### Pattern 8 — OC Box Flip
**Logic:** Each session candle defines a box. Trade flips: close above H → BUY (or flip from SELL), close below L → SELL (or flip from BUY). Hard SL at 1 box-height beyond.

**V25 result:** 93.0% WR but −0.013R/trade across 87,877 trades. Tons of tiny wins eaten by 1R losses. **Not tradeable.**

### Pattern 9 — OC + ICT Sessions, M5 trigger ⭐ THE WINNER
**Logic:** Same as 7B but with the ICT KillZone session times (Asia 22→9, London 7→16, NY 13→22 UTC). M5 close triggers entry. Fixed 500-tick SL, 940-tick TP.

**V25 result:** **63.9% WR, +0.841R/trade, 2,656 trades. All 9 months tested were profitable.** Highest expectancy in the entire scan. This is what `ICTSessionsEA.mq5` runs.

### Pattern 10 — OC + ICT Sessions, H1 trigger
**Logic:** Same as Pattern 9 but only enters when an H1 candle closes past the level (not just any M5 close).

**V25 result:** 61.9% WR, +0.783R/trade, 2,450 trades. Worse than Pattern 9 — waiting for H1 close loses more good signals than it filters bad ones. **Reject.**

---

## Detailed Pattern 9 breakdown (the winner)

### Monthly performance (R_25 M5)
| Month | Trades | WR | Net R |
|---|---|---|---|
| 2025-09 | 160 | 63.1% | +130.88 |
| 2025-10 | 338 | 61.5% | +261.04 |
| 2025-11 | 337 | 61.4% | +259.16 |
| 2025-12 | 349 | 59.6% | +250.04 |
| 2026-01 | 341 | 64.5% | +292.60 |
| 2026-02 | 312 | 63.5% | +258.24 |
| 2026-03 | 340 | 67.6% | +322.40 |
| 2026-04 | 344 | 68.9% | +338.56 |
| 2026-05 (partial) | 135 | 65.9% | +121.32 |

**Every single month positive.** No 30-day drawdown periods in 9 months of data.

### By session
| Session | Win % |
|---|---|
| Asia (22:00–09:00 UTC) | 64.6% |
| London (07:00–16:00 UTC) | 61.9% |
| NY (13:00–22:00 UTC) | 65.3% |

All sessions tradeable.

### By day of week
| Day | Win % |
|---|---|
| Mon | 64.9% |
| Tue | 65.5% |
| Wed | 66.8% |
| Thu | 62.4% |
| Fri | 62.3% |
| Sat | 61.9% |
| Sun | 63.9% |

V25 trades 24/7. Every day profitable.

### Best hours UTC (≥10 trades, sorted by WR)
| Hour | Win % | Count |
|---|---|---|
| 05:00 | 90.9% | 11 |
| 06:00 | 88.9% | 9 |
| 03:00 | 78.3% | 23 |
| 23:00 | 73.3% | 90 |
| 20:00 | 72.7% | 22 |
| 10:00 | 70.8% | 65 |
| 00:00 | 68.2% | 44 |
| 13:00 | 67.9% | 346 |

If you want to filter for a higher WR (at the cost of fewer trades), enable `InpUseHourFilter = true` with `InpHoursAllowed = "0,3,5,6,10,13,20,23"`. **Currently OFF by default** — the state machine handles fresh-signal filtering already.

---

## Cross-symbol summary

### V25 (R_25) — production
Run `ICTSessionsEA.mq5` with default settings.
- Pattern 9: +0.841R/trade, 2,656 trades over 8 months
- Broker stops_level: 423 (manageable)
- Min lot: 0.5
- Tick value: $0.001
- Min margin per trade: ~$0.50

### V10 (R_10) — secondary, needs verification
Earlier scan with original 40:75 ticks showed +0.811R/trade. But:
- Broker stops_level not yet verified for V10
- Re-scan needed with `--point 0.001` and ICT sessions (Pattern 9)

**Action item:** before trading V10 live, run:
```
py PatternScanner.py --symbol R_10 --years 1 --point 0.001 --sl 500 --tp 940
```
and check Pattern 9 expectancy.

### V50 (R_50) — skip
- All OC patterns at native scale: −0.028 to −0.013R
- Volatility profile doesn't fit the 500:940 R:R framework
- No tweak has produced positive expectancy

### V75 (R_75) — skip permanently
- Broker stops_level = 10,770 points (= 107.7 price units minimum SL)
- That's ~270× wider than what the strategy needs
- Scaling TP/SL up by 270× makes Pattern 7B break-even at best
- Any other Deriv broker with smaller V75 stops_level: re-test, but Deriv's is too wide

### 1HZ variants (untested)
1HZ10V, 1HZ25V, 1HZ50V, 1HZ75V, 1HZ100V — same family as R_* but with 1-second tick rates. M5 candles still M5, so strategy applies the same way. Often have tighter spreads and smaller stops_level than the R_* counterparts.

**Action item:** scan these as the next instrument expansion:
```
py PatternScanner.py --symbol 1HZ25V --years 1 --point 0.001 --sl 500 --tp 940
py PatternScanner.py --symbol 1HZ10V --years 1 --point 0.001 --sl 500 --tp 940
```

---

## Methodology notes

### Scanner data source
Deriv websocket API (`wss://ws.derivws.com`). M5 OHLC candles fetched in batches of ~5,000, deduplicated, sorted oldest→newest. Maximum ~8 months of history per symbol due to API retention limits.

### Simulator assumptions
- Each trade walks forward up to 200 bars looking for TP or SL hit
- If a single M5 bar's high crosses TP AND its low crosses SL, the simulator counts WIN (optimistic). Real fills could go either way.
- No slippage modelled
- No spread modelled (entry at theoretical bar close)
- No commissions (Deriv synthetic indices have no commission)

### Expected live retention
Backtest expectancy × 60–80% = realistic live expectancy. So Pattern 9's +0.841R likely lands at +0.5R to +0.65R per trade in live conditions on a quality broker.

### Statistical confidence
Pattern 9: 2,656 trades over 9 months. Standard error on expectancy ≈ 0.04R. So the true expectancy is very likely between +0.76R and +0.92R. Even the lower bound is a strong edge.

---

_Run your own scan any time with `PatternScanner.py` if you want to update these numbers or test a new symbol._

---

## Updated as of 2026-05-29: current production numbers

After fixing the scanner (broker preset auto-load + corrected `eff_tp` direction), the only surviving config across cross-window stress tests is:

| | Honest backtest | After 0.7 live retention |
|---|---:|---:|
| **Pattern 9, SL=2000/TP=6000, 13:00 UTC only** | +0.122R/trade | +0.087R/trade |
| Trades per year (8-month sample × 1.5) | ~504 | ~504 |
| Annual $ on $100 acct @ 0.5 lot | ~+$62 | ~**+$44** |
| Worst 2-month DD in backtest | $25 | — |
| Cross-window positive | **4/4** | — |

See `MODEL_FINDINGS_2026-05-26.md` for the cross-window data, drawdown profile, and full hour-filter analysis.
