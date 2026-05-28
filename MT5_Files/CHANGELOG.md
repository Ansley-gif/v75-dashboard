# V25 ICT Trading System — Changelog & Backlog

Living record of what's been built, fixed, tested, and what's still on the runway.

---

## ✅ Done

### Phase 1 — Foundation (early sessions)
- [x] Built `SessionBreakoutEA.mq5` (v1) — broader full-session H/L breakout
- [x] Built `OpenCloseEA.mq5` (v2) — first ICT Open/Close candle breakout EA
- [x] Built `SessionLevels.mq5` (v1) — visual indicator drawing session boxes + FVGs + order blocks
- [x] Built `PatternScanner.py` — 1-year Deriv API backtester for 7 ICT-style patterns
- [x] Documented strategy in `OPEN_CLOSE_README.txt` and `HOW_TO_INSTALL.txt`

### Phase 2 — Bug fixes on EA execution (May 2026)
- [x] Fixed "invalid stops" rejection — broker validates BUY SL/TP against Bid, SELL against Ask
- [x] Fixed `min_dist` calculation to account for `stops_level + freeze_level + spread + safety margin`
- [x] Added broker diagnostic block to OnInit (logs `Stops level`, `Tick size`, `Tick value`, lot bounds)
- [x] Added enhanced rejection logs showing bid/ask/sl/tp/min_dist for debugging

### Phase 3 — Strategy refinements
- [x] Added Mode 0 SL placement = level-defining candle's opposite extreme (true ICT logic)
- [x] Added Mode 2 SL placement = tighter of (candle-extreme, fixed-ticks) as risk-capped fallback
- [x] Added multi-attempt-per-level logic (replaced single-shot `used` boolean with `attempts` counter)
- [x] Added hour-filter input with V25 high-WR hours from initial backtest

### Phase 4 — Symbol exploration
- [x] Scanned R_75 → broker stops_level = 10,770 → strategy dies at any sensible scale ✗
- [x] Scanned R_50 → all OC patterns negative at native scale ✗
- [x] Scanned R_25 → **+0.944R expectancy at original scale** ✓
- [x] Scanned R_10 → +0.811R expectancy at original scale (yet to verify at broker scale)
- [x] Verified V25 broker `stops_level` = 423 (= 0.423 price units, workable)
- [x] Re-scanned V25 at broker-realistic 500:940 ticks → **+0.757R expectancy still positive** ✓

### Phase 5 — ICT session-time integration (latest)
- [x] Identified mismatch between MT5 broker time (UTC+2 SAST) and chart time (UTC)
- [x] Updated PatternScanner.py with `SESSIONS_ICT` (Asia 22→9, London 7→16, NY 13→22)
- [x] Added **Pattern 9** to scanner — OC + ICT sessions + M5 trigger + fixed SL
- [x] Added **Pattern 10** to scanner — OC + ICT sessions + H1 trigger + fixed SL
- [x] Scan results: Pattern 9 = **+0.841R/trade, 63.9% WR, all 9 months positive** ← BEST
- [x] Pattern 10 (H1 trigger): worse than M5 (+0.783R) — H1 filtering loses good signals

### Phase 6 — Indicator
- [x] Built `SessionOCLevels.mq5` v1 (basic horizontal lines)
- [x] Rewrote `SessionOCLevels.mq5` v2 with shaded boxes, today-only focus, trading-day reset at Asia open (22:00 UTC), session-end vertical lines

### Phase 7 — Critical EA bug fixes (May 13)
- [x] Discovered stale-level firing bug — yesterday's London Close LOW fired SELL 13 hours later
- [x] Diagnosed root cause: hour filter blocked yesterday's actual break, attempts counter reset for today
- [x] Implemented **ARMED / UNARMED state machine** in `GOLDOpenCloseEA.mq5`:
  - Level can only fire when ARMED
  - Fires once → becomes UNARMED
  - Re-arms only when a bar closes back through the level (into the box)
  - Eliminates "stale level fires endlessly" bug
- [x] Added `[RE-ARM]` log lines for state-machine visibility

### Phase 8 — Production EA
- [x] Built **`ICTSessionsEA.mq5`** as the production EA based on Pattern 9 backtest
  - All Pattern-9 defaults baked in (ICT sessions, SL Mode 1, 500-tick SL, 940-tick TP, lot 0.5)
  - ARMED/UNARMED state machine integrated
  - Magic 25009 (distinct from other EAs)
  - Hour filter OFF by default
  - `[SKIP]` log lines when R:R or hour filter rejects a signal
  - Daily stop at 3R, suitable for small accounts

### Phase 9 — V25 Strategy Tester blowup + scanner rewrite (May 22–26)
- [x] EA wiped $100 → $2 in MT5's every-tick Strategy Tester despite Pattern 9 = +0.841R/trade backtest
- [x] Diagnosed in `DIAGNOSIS_2026-05-22.md`: broker SL widened to 707 ticks (not 500), R:R degraded 1.88 → 1.33, day-R counter using wrong denominator
- [x] Re-ran scanner with `--spread 137 --stops-level 423` — Pattern 9 collapsed to **−0.350R/trade**
- [x] Found a SECOND bug in scanner: `eff_tp = tp - spread` was wrong direction; correct is `tp + spread`
- [x] Rewrote scanner broker model: BROKER_PRESETS auto-load per symbol, $-frame R-multiple post-process, loud no-friction warning, slippage support — see `PatternScanner.py:1144-1209`
- [x] Honest baseline after fix: **Pattern 9 = −0.406R/trade**, no pattern positive at original config
- [x] Cross-window stability test (4 non-overlapping 2-month windows, all 9 patterns, multiple configs)
- [x] **Sole survivor discovered**: Pattern 9 with **SL=2000/TP=6000 + 13:00 UTC hour filter** → 4/4 positive windows, +0.122R/trade backtest
- [x] Full diagnostic + winning model captured in **`MODEL_FINDINGS_2026-05-26.md`** ← read this first for context

---

## 🔄 In Progress / Verification Needed

- [ ] Update `ICTSessionsEA.mq5`: SL=2000, TP=6000, hour filter defaulting to 13:00 UTC, fix day-R denominator
- [ ] Build manual-trading chart template (indicator) matching new EA style
- [ ] Demo-test the updated EA on V25 for 1–2 weeks → compare live to backtest
- [ ] Apply 60–80% retention haircut to forecasts (live edge ≈ $37–$50/year on $100 acct, mid $44, NOT the old $300+ projection)

---

## 📋 Backlog / Next

### High priority
- [ ] Re-scan **V10** with broker-correct point (0.001) and ICT sessions — currently only have native 40:75 result
- [ ] Re-scan **1HZ10V** and **1HZ25V** — 1-second variants may have tighter stops_level and better fills
- [ ] Add per-trade R-tracking to EA (currently uses fixed-SL approximation, miscounts when SL is wider than expected)

### Medium priority
- [ ] **Liquidity-target TP variant** (Pattern 11) — instead of fixed 940-tick TP, target nearest swing high/low, order block, FVG, or void. Needs swing/OB/FVG detection in scanner.
- [ ] **Compound sizing logic** — increase lot once account hits next equity tier (e.g. $50 → 1 lot, $100 → 1.5 lot, etc.)
- [ ] **Multi-symbol EA wrapper** — run same strategy on V10 + V25 + V50 from a single chart with shared daily-stop budget
- [ ] **Trail-stop refinement** for V25 — current `InpTrailStartTks/InpTrailStepTks` defaults untested live

### Low priority / nice-to-have
- [ ] Web dashboard integration — push EA trade events into the V75 Dashboard (Flask on Oracle Cloud)
- [ ] Telegram trade alerts (EA → existing dashboard alert system)
- [ ] Backtest seasonal patterns (Q1 vs Q4, weekday breakdown for new ICT sessions)
- [ ] Build VPS deployment guide (Windows VPS for MT5)

### Deferred (don't pursue unless other things prove out)
- [ ] Pattern 8 box-flip strategy — tested, doesn't work at this scale
- [ ] Mode 0 SL on default — too risky on giant candles, kept as option only
- [ ] Multi-trade per level after WIN — replaced by state machine

---

## 🐛 Known Issues / Caveats

| Issue | Status | Workaround |
|---|---|---|
| Day-R counter uses fixed-SL baseline (not actual trade SL) | open | Don't rely on day-R for accurate accounting; check $ profit directly |
| State machine starts fresh on EA re-attach (loses prior level state) | open | Avoid re-attaching mid-session if a level was already consumed today |
| Scanner has "TP within same bar as entry" optimism | known | Expect live to retain ~60–80% of backtest expectancy |
| Hour filter, when on, blocks legitimate breaks at "off" hours | mitigated | Default = OFF; state machine handles freshness |

---

## 📊 Tested Symbols Summary

| Symbol | Pattern 9 / 7B Result | Verdict |
|---|---|---|
| R_25 (V25) | **+0.841R Pattern 9, 9/9 months positive** | ✅ Production |
| R_10 (V10) | +0.811R Pattern 7B at native scale | 🔄 Re-verify at broker scale |
| R_50 (V50) | All OC patterns negative | ❌ Skip |
| R_75 (V75) | broker stops_level too wide | ❌ Skip |

---

_Last updated: 2026-05-27_
