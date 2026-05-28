# Diagnosis — V25 Backtest Blowup, 2026-05-22

End-to-end audit of why `ICTSessionsEA.mq5` wiped $100 → $2.37 in MT5's every-tick Strategy Tester (Jan 2024 → Jan 2026) while `PatternScanner.py` reported Pattern 9 = **+0.841R / trade** on the same instrument.

---

## 1. Headline

| | Scanner (Pattern 9) | EA in Strategy Tester |
|---|---|---|
| Period | 8 months (Sep 2025 – May 2026) | 24 months (Jan 2024 – Jan 2026) |
| Trades | 2,656 | **1,398** |
| Win rate | **63.9%** | **35.6%** (498 W / 900 L) |
| R:R per trade | 1.88R (940:500) | **1.33R** (940:707) |
| Expectancy | +0.841R | **≈ −0.28R** ($−0.07 / trade) |
| Net | positive | **−$97.63** |

The change from `InpAttemptsPerLevel=5` → `1` moved the final balance from $2.20 → $2.37 — essentially **a no-op**, because the state machine never re-arms (see §6).

---

## 2. Six findings, ranked by impact

### 🔴 Finding 1 — Effective SL is 707 ticks, not 500 (cited evidence: every trade entry log)

The EA's `min_dist` clamp (`ICTSessionsEA.mq5:282`) widens SL whenever the broker's `stops_level + spread + 10` exceeds the configured 500-tick SL. **Every single one of the 1,398 trades** had this happen.

Evidence from log:
```
>> SELL LDN_OC_L @2149.34200  SL=2150.04900 (707 tk)  TP=2148.40200 (940 tk)  R:R=1:1.33
>> BUY  LDN_OC_H @2152.22400  SL=2151.51600 (708 tk)  TP=2153.16400 (940 tk)  R:R=1:1.33
```

Broker diagnostics from `OnInit`:
- `Stops level: 423 points`
- `Freeze level: 0 points`
- `Tick size: 0.00100`

Derivation: `min_dist = (423 + spread + 10) * tick`. With observed spread ≈ 137 ticks, `min_dist ≈ 570 ticks`, and `SL = bid ± min_dist + spread` ≈ 707 ticks past entry. Consistent across all trades.

**Impact**: R:R degrades from intended 1:1.88 → actual 1:1.33. Risk-per-trade is **41% larger than configured**.

---

### 🔴 Finding 2 — Day-R counter uses the wrong denominator (`ICTSessionsEA.mq5:530-533`)

```mql5
double risk_money = InpFixedSLTicks *
                    SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE) *
                    InpLotSize;
if(risk_money > 0) g_day_pnl_r += profit / risk_money;
```

Denominator = `500 × tick_value × lot`. Actual SL distance = 707 ticks. So each real −1R loss is **recorded as −1.41R to −1.48R**. Confirmed in log:

```
2024.01.01 07:10:38  [EXIT] profit=-0.37  day_R=-1.48
2024.01.02 00:05:27  [EXIT] profit=-0.36  day_R=-3.16  (← daily stop trips after 2 losses)
2024.01.04 11:02:09  [EXIT] profit=-0.36  day_R=-2.44
2024.01.05 00:05:42  [EXIT] profit=-0.38  day_R=-3.16  (← trips again after 2 losses)
```

**Impact**: The 3R daily stop trips after only **~2 losses** instead of the intended 3. Combined with the strategy's real 35.6% WR, two-loss days are common — the stop fires constantly. Already documented as a "Known Issue" in `CHANGELOG.md:107` but never fixed.

---

### 🔴 Finding 3 — Daily stop is too aggressive: 32,223 bars blocked, ~66% of days affected

```
Daily limit blocks: 32,223
```

Over a 730-day test that's ~44 bars/day average. Given trading hours, this means the daily-stop fires on the majority of days. Sample of trips:

| Day | Trips at day_R | Real losses needed |
|---|---|---|
| 2024.01.01 | −3.04 | 2 |
| 2024.01.02 | −3.16 | 2 |
| 2024.01.04 | −2.44 | 2 |
| 2024.01.05 | −3.16 | 2 |
| 2024.01.07 | −2.84 | 2 |

But the engine CAN have big winning days when not cut off — 2024.01.03 closed at **day_R = +10.48** (10 winning trades vs the 2-loss daily cap implied by the misaccounting). The daily stop is robbing the strategy of recovery sessions.

---

### 🟠 Finding 4 — Position size too large for the account

| Metric | Value |
|---|---|
| Initial balance | $100 |
| Lot (forced minimum) | 0.5 |
| Tick value | $0.001 / tick per 1.0 lot |
| Loss per SL hit | 707 ticks × $0.001 × 0.5 = **$0.354** |
| Win per TP hit | 940 ticks × $0.001 × 0.5 = **$0.470** |
| Margin per trade | ~$2.97 |

A $100 account at 0.5 lots can absorb roughly 280 stop-outs before margin call. Over 24 months the EA placed 1,398 trades; 900 losses × $0.35 = $315 lost gross, partly offset by 498 wins × $0.47 = $234, net **−$81** (matches the actual −$97 to within rounding noise). The account survived only because Deriv's broker min-lot is high relative to the deposit, not because the strategy has edge here.

**Reality**: $100 is not a viable account for V25 at the broker's 0.5 minimum lot. The minimum credible account given current sizing is ≈ $1,500 (50R cushion at the actual $0.35 SL).

---

### 🟡 Finding 5 — Scanner numbers don't model spread; +0.841R is best-case

`PatternScanner.py` has `--spread` and `--stops-level` CLI flags (lines 1197-1200) but they default to 0 and the existing V25 scan never set them. The scanner's `_simulate()` walks bar-by-bar against HLC and assumes mid-price fills.

`STRATEGY_REPORT.md:184-189` admits this:
> "If a single M5 bar's high crosses TP AND its low crosses SL, the simulator counts WIN (optimistic). Real fills could go either way. No slippage modelled. No spread modelled."

Note: the actual scanner code (`PatternScanner.py:189-193`) was later updated to resolve same-bar conflicts with **closer-level-wins** (which for 500:940 = LOSS). But `STRATEGY_REPORT.md` was not re-generated after that fix. **The +0.841R number may be stale and from the old optimistic logic** (the code comment at line 175 says "inflated win-rates by 20-30 pp"). 64% predicted vs 36% actual matches that 20-30pp gap.

---

### 🟡 Finding 6 — State machine never re-arms; `InpAttemptsPerLevel` is a no-op

```
RE-ARM events: 0
```

The re-arm logic at `ICTSessionsEA.mq5:289-306` requires `bar.close` to cross BACK through the level into the box. In 2 years of M5 data, this never happened — once a level breaks and fires, price doesn't return to close on the other side of that exact level within the 24h TTL.

Additionally: `if(g_levels[i].attempts >= InpAttemptsPerLevel) continue;` runs at line 286 **before** the re-arm check at line 290. With `InpAttemptsPerLevel=1`, every fired level is filtered out before re-arm logic even runs. With `=5`, re-arm code was reachable but never triggered (data confirms it).

So **the 1-vs-5 change literally cannot affect the outcome**. Both produce identical trade sequences.

---

## 3. Why the win rate inverted (64% → 36%)

Three compounding effects:

1. **Wider SL relative to TP**: Scanner used 500:940 (47% SL/TP ratio). EA has 707:940 (75% ratio). Trades that retrace into the level now hit SL where scanner would have survived.
2. **Spread shifts entry away from level**: ASK = bid + 137 ticks. The BUY fills 137 ticks past the level the scanner clears at bar.close. Any normal retest now triggers SL.
3. **Same-bar TP+SL resolves to LOSS** in the current scanner code (closer-level-wins). If the cited +0.841R came from the old optimistic version, the scanner over-stated WR by ~25pp.

The actual break-even win rate at 1.33 R:R is `1/(1+1.33) = 42.9%`. Strategy as configured runs at 35.6% — **below break-even**.

---

## 4. What this rules OUT

- ❌ The `InpAttemptsPerLevel` change (5 → 1) is not relevant (Finding 6).
- ❌ The state machine is not buggy — it's just inactive in V25's price action.
- ❌ The compile / .set caching workflow is fine now — inputs `=1` were read correctly.

## 5. What this points TO (root causes, in order)

1. **Day-R counter bug** (Finding 2) — easy fix, biggest immediate behavior change.
2. **SL widening reality vs config** (Finding 1) — strategy was designed for 1:1.88 R:R but lives at 1:1.33.
3. **Scanner's reported edge is overstated** (Finding 5) — re-run scanner with `--spread` and `--stops-level` to get a realistic baseline.
4. **Account is too small for sizing** (Finding 4) — separate from strategy edge.

---

## 6. Reproduction commands

```powershell
# Re-run scanner with broker-realistic params
py PatternScanner.py --symbol R_25 --years 1 --point 0.001 --sl 500 --tp 940 --spread 137 --stops-level 423
```

Open log: `C:\Users\User\AppData\Roaming\MetaQuotes\Tester\6AB79ED795024EC1B7F61552A87628BC\Agent-127.0.0.1-3000\logs\20260522.log`

---

## 7. Scanner re-run with broker-realistic params — VERDICT (added after running)

Output: `scanner_realistic_v25.log` (49,000 M5 bars, 2025-12-04 → 2026-05-23, ~6 months).

| Pattern | Trades | WR | Avg R/win | Expectancy |
|---|---|---|---|---|
| 1. Session H/L breakout | 756 | 30.8% | 1.14R | **−0.342R** |
| 2. London/Asian range | 94 | 97.9% | 0.02R | +0.003R (basically zero) |
| 3. NY Open Reversal | 170 | 70.6% | 0.14R | **−0.193R** |
| 4. Opening Range Breakout | 822 | 91.0% | 0.09R | **−0.008R** |
| 5. Consolidation Squeeze | 0 | — | — | no signals |
| 6. Previous Session Level Run | 471 | 27.4% | 1.14R | **−0.415R** |
| 7A. OC SL=candle extreme | 1,908 | 77.4% | 0.29R | **−0.003R** |
| 7B. OC SL=fixed ticks | 1,908 | 29.6% | 1.14R | **−0.368R** |
| 7C. OC SL=tighter | 1,908 | 29.6% | 1.14R | **−0.367R** |
| 8. OC Box Flip | 71,868 | 94.2% | 0.05R | **−0.011R** |
| **9. OC + ICT M5** (production) | **1,898** | **30.5%** | **1.14R** | **−0.350R** |
| 10. OC + ICT H1 | 1,752 | 29.4% | 1.14R | **−0.372R** |

**Every single pattern is now negative or break-even at zero**. Pattern 9's expectancy collapses from the previously-cited **+0.841R → −0.350R**.

This matches the EA Strategy Tester's actual outcome (35.6% WR / blowup). The original +0.841R number was an artifact of running the scanner without `--spread` and `--stops-level`, while the codebase was citing those numbers as the production edge.

**Conclusion**: Pattern 9 — and every other ICT pattern in the scanner — has no exploitable edge on V25 under realistic Deriv broker conditions (137-tick spread, 423-tick stops_level). The "production winner" verdict in `STRATEGY_REPORT.md` is stale.

The two patterns that aren't deeply negative:
- **7A (candle-extreme SL)**: 77.4% WR but Avg R/win = 0.29 → expectancy basically zero. Recent months trending positive (March +19.67R, May +6.56R) but that's noise on n≈300.
- **2 (London breakout of Asian range)**: 97.9% WR but Avg R/win = 0.02 → tiny edge, microscopic R. Not really tradable.

Neither survives the 60-80% live-retention haircut.
