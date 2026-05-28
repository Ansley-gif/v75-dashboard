# V25 Strategy Findings — 2026-05-26

End of the multi-session diagnostic that started from the 2026-05-22 EA blowup. This document captures the **winning model**, the **diagnostic story**, and **everything needed to reproduce or revise** the work later.

---

## 🏆 The winning model (production candidate)

**Pattern 9 + Wide SL + 13:00 UTC hour filter**

| Parameter | Value | Why |
|---|---|---|
| Pattern | OC + ICT sessions, M5 trigger ("Pattern 9") | Only pattern surviving cross-window stability test (1 of 9 tested) |
| Symbol | V25 / R_25 | Only verified Deriv symbol with broker realism modeled |
| Configured SL | 2000 ticks | Wider SL is essential — V25's M5 noise eats SL<2000 |
| Configured TP | 6000 ticks | $R:R = 3.0 — break-even WR only 25%, less variance-sensitive |
| Broker SL (actual) | 2000 ticks | configured_sl >= stops_level + 2*spread + 10 = 707, so 2000 prevails |
| Hour filter | **13:00 UTC only** | Only hour that's 4/4 positive across windows |
| Lot size | 0.5 (broker minimum) | Forced by Deriv min lot |
| Daily stop | TBD — current 3R is buggy | See "Required EA changes" below |

**Expected performance** (after 0.7 live-retention haircut, $100 acct @ 0.5 lot):

| Period | Trades | Expected $ | 68% range (1σ) | 95% range (2σ) | P(profit) |
|---|---:|---:|---:|---:|---:|
| 1 week | ~10 | +$0.87 | −$5 to +$7 | −$10 to +$12 | 56% |
| 2 weeks | ~21 | +$1.83 | −$6 to +$10 | −$15 to +$18 | 59% |
| 1 month | ~42 | +$3.65 | −$8 to +$15 | −$20 to +$27 | 62% |
| 2 months | ~84 | +$7.31 | −$9 to +$24 | −$26 to +$40 | 67% |
| 3 months | ~126 | +$10.96 | −$9 to +$31 | −$29 to +$51 | 71% |
| 6 months | ~252 | +$21.92 | −$7 to +$50 | −$35 to +$79 | 78% |
| **1 year** | **~504** | **+$43.85** | +$3 to +$84 | −$37 to +$125 | **86%** |

Per-trade stats: WIN=28.1% pays +$3, LOSS=71.9% pays −$1, E[trade]=+$0.087, σ=$1.80.

Sensitivity to retention: annual $ at 0.5=$31, 0.6=$37, **0.7=$44**, 0.8=$50.

**Worst observed (backtest, 8 months 2025-09 → 2026-04):**
- Per 2-month window max DD: $25 (W2: Nov–Dec 2025)
- 8-month combined max DD: $26
- Longest losing streak: **12 trades** (~$12 = 12% of account)

---

## 📉 Why all prior numbers were wrong

The original `STRATEGY_REPORT.md` cited Pattern 9 = **+0.841R/trade** as "production winner". That number was an artefact of running `PatternScanner.py` with `--spread 0 --stops-level 0`, both of which default to zero. The 2026-05-22 diagnosis ([`DIAGNOSIS_2026-05-22.md`](./DIAGNOSIS_2026-05-22.md)) opened with broker-realistic params and the expectancy collapsed to −0.350R. Then this session found a further bug in the broker model itself.

### Scanner bug fixed in this session (2026-05-26)

`PatternScanner.py` line 1117 (before): `eff_tp = max(1, tp - args.spread)`

**This is wrong direction.** In MT5 bid-frame:
- BUY entry fills at ASK = bid + spread + slippage
- TP price = entry + configured_tp ticks
- For BUY TP to fire, BID must reach TP_price → bid must move `configured_tp + spread + slippage` ticks up

The scanner was *subtracting* spread when it should have been *adding*. After fixing, Pattern 9's 1-year expectancy moved from −0.350R → **−0.406R** — the headline got worse, but now matches actual MT5 Strategy Tester behaviour.

See `PatternScanner.py:1144-1167` for the corrected broker model.

---

## 🔬 The diagnostic story (chronological)

### Step 1: Fix the scanner so every run is broker-realistic

Changes shipped:
1. **`BROKER_PRESETS` dict** keyed by symbol — auto-loads spread/stops_level for R_25
2. **`recompute_r_multiple_dollar()`** — overwrites trade r_multiple to $-frame
3. **Loud warning** banner if a run has spread=0 and stops_level=0
4. **Enhanced header** showing broker_sl, sim distances, $R:R per run
5. **`--slippage` CLI arg** (default 2 ticks adverse fill)
6. **Fixed eff_tp direction bug** described above

Outcome: Pattern 9 honest baseline = **−0.406R/trade** under broker reality.

### Step 2: Restore the design R:R (SL=707, TP=1330)

Hypothesis: the EA's bug was R:R degradation from 1.88 → 1.33. If we restore it, does Pattern 9 work?

Outcome: Pattern 9 went from −0.406R → **−0.285R** (~60% of the gap closed). But still negative, still 0/4 positive across windows. **R:R restoration alone is not enough.**

### Step 3: Stress-test across non-overlapping 2-month windows

Tested 6 fixed-SL configs × 4 windows on Pattern 9:

| Config | $R:R | Pos | Avg Exp |
|---|---:|:---:|---:|
| SL=500/TP=940 (prod) | 1.33 | 0/4 | −0.391R ✗ |
| SL=500/TP=1330 (intent) | 1.88 | 0/4 | −0.268R ✗ |
| SL=500/TP=2000 | 2.83 | 1/4 | −0.117R ✗ |
| SL=500/TP=3000 (sweep best) | 4.24 | 2/4 | −0.022R ✗ |
| **SL=2000/TP=4000** | 2.00 | **3/4** | **+0.027R** ✓ |
| SL=1500/TP=3000 | 2.00 | 2/4 | −0.016R ✗ |

**First survivor found: SL=2000/TP=4000.** Wider SL was the unlock — V25's M5 noise eats SL<2000.

W2 (Nov–Dec 2025) was a regime-tough window where every config lost. Even the survivor lost −0.020R in W2. Flagged as a known weakness.

### Step 3 (extended): Push wider SL + session/hour filters + all patterns

Phase A — extended wide-SL configs on Pattern 9:

| Config | $R:R | Pos | Avg Exp |
|---|---:|:---:|---:|
| SL=2000/TP=4000 | 2.00 | 3/4 | +0.027R |
| SL=2500/TP=5000 | 2.00 | 3/4 | +0.014R |
| SL=3000/TP=6000 | 2.00 | 3/4 | +0.005R |
| **SL=2000/TP=6000** | **3.00** | **3/4** | **+0.027R** |
| SL=3000/TP=9000 | 3.00 | 3/4 | +0.006R |

`SL=2000/TP=6000` ties on raw expectancy but with $R:R=3.0 (break-even WR only 25%), much less variance-sensitive than R:R=2.0.

Phase B — hour breakdown on SL=2000/TP=6000:

| Hour UTC | Trades/win | Pos | Avg Exp |
|---|---:|:---:|---:|
| **13:00** (NY open) | 66–92 | **4/4** | **+0.122R** ✓✓ |
| 23:00 | 13–28 | 3/4 | +0.240R |
| Other hours | varies | 0–2/4 | mostly negative |

**THE FILTER FINDING: Restricting Pattern 9 entries to 13:00 UTC turns the marginal +0.027R into a robust +0.122R.**

Phase C — all 9 patterns × 4 configs × 4 windows = 144 backtests:

**Only one survivor: Pattern 9 with SL=2000/TP=4000.** Every other pattern (1, 3, 4, 6, 7A, 7B, 7C, 10) is uniformly negative across all tested configs and windows. **Step 4 (Pattern 7A) is moot** — 7A is 0/4 positive everywhere.

### Verification: 13:00 isn't a single-hour fluke

Tested hour-range expansions and 13+23 combo across 4 windows:

| Filter | Trades/2mo | Pos | Avg Exp | Combined 8-mo Net | Max DD |
|---|---:|:---:|---:|---:|---:|
| 13:00 only | 84 | 4/4 | +0.122R | +$42 | $26 |
| 12-13 | 87 | 4/4 | +0.120R | +$44 | $25 |
| 13-14 | 97 | 3/4 | +0.074R | — | — |
| 12-14 | 99 | 3/4 | +0.076R | — | — |
| 11-15 | 115 | 4/4 | +0.104R | — | — |
| 13 + 23 | 106 | 4/4 | +0.136R | +$55 | $36 |
| NY session 13-21 | 222 | 2/4 | −0.028R | — | — |
| No filter | 642 | 3/4 | +0.027R | — | — |

The edge is a broader NY-open phenomenon — 12-13 and 11-15 also hit 4/4 positive. After 15:00 UTC the edge disappears (NY session 13-21 drops to 2/4).

**Selected for deployment: 13:00 UTC only** — best DD-to-return ratio, simplest signal, shortest loss streak (12 vs 16 for 13+23 combo).

---

## 🛠 Required EA changes (Step 5, not yet implemented)

Three changes to `ICTSessionsEA.mq5`:

1. **Defaults**: `InpFixedSLTicks=2000`, `InpFixedTPTicks=6000`
2. **New input**: hour-filter window defaulting to 13:00 UTC only (need to clarify how this interacts with existing `InpHourFilterStart`/`InpHourFilterEnd`)
3. **Day-R fix**: line 530-533 currently uses `InpFixedSLTicks` as 1R denominator. With variable broker SL widening, this miscounts. Replace with actual SL distance from each trade. Already documented as known issue in `CHANGELOG.md:107`.

---

## 📂 Files produced this session

### Code changes
- `PatternScanner.py` — broker model rewrite, BROKER_PRESETS, slippage, recompute_r_multiple_dollar

### New scripts (kept — reusable)
- `stress_windows.py` — Pattern 9 cross-window stability (first version, 6 configs × 4 windows)
- `stress_full.py` — comprehensive test: Phase A wide-SL extension, Phase B session/hour breakdown, Phase C all 9 patterns × 4 configs × 4 windows
- `verify_filters.py` — hour-filter expansion + 13+23 combo + drawdown profile

### Logs (raw data — reproducible from scripts)
- `baseline_step1.log` — Step 1 corrected baseline
- `step2_tp1330.log` — Step 2 R:R restoration test
- `stress_windows.log` — Step 3 initial cross-window data
- `stress_full.log` — Step 3 extended + Phase C all-patterns
- `verify_filters.log` — final hour-filter + drawdown analysis

### Earlier session (kept for reference)
- `DIAGNOSIS_2026-05-22.md` — the EA blowup audit
- `tp_sl_sweep.py` / `tp_sl_sweep.log` — original TP/SL grid search (had buggy scanner)
- `scanner_realistic_v25.log` — first scan with broker params (had buggy scanner)

---

## 🔁 How to reproduce

```powershell
# 1. Honest baseline of all patterns under broker reality
py PatternScanner.py --symbol R_25 --years 1 --sl 500 --tp 940
# (BROKER_PRESETS auto-loads spread=137, stops_level=423)

# 2. Pattern 9 cross-window stability with extended configs
py stress_full.py
# Output: stress_full.log

# 3. Hour-filter verification + drawdown
py verify_filters.py
# Output: verify_filters.log
```

---

## ⚠️ Risk warnings to internalise

1. **Backtest != live.** Apply 60–80% retention haircut to every expectancy number above.
2. **Variance >> expectation on small samples.** A 5-loss week (−$5) is normal. A 12-trade loss streak is in the backtest data.
3. **W2 regime risk.** Nov–Dec 2025 was a tough window for *every* config. Similar regimes will recur. Don't disable the EA after one bad month.
4. **W2 backtest DD = $25 (25% of $100).** If you can't watch that happen without panicking, this account is too small.
5. **Live edge is tiny in $ terms.** Expected +$22/year on $100. This is a learning vehicle, not income.
6. **Don't size up after a winning streak.** Variance will mean-revert.
7. **Don't change the EA mid-test.** Run the configured strategy for 4+ weeks before judging.

---

_Captured: 2026-05-26._
