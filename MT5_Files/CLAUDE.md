# CLAUDE.md — Project brief for Claude Code sessions

This file is read automatically by Claude Code when it starts in this directory. It's the handover note so you (Claude) know what this project is, what's been built, and what's pending without me having to re-explain every session.

---

## What this project is

ICT-style breakout trading system for **Deriv's Volatility 25 Index (V25 / R_25)** on MT5, M5 timeframe. The system has four parts:

1. **`ICTSessionsEA.mq5`** — the production Expert Advisor
2. **`ICTManualTradeAssist.mq5`** — chart indicator for hand-trading the same setups
3. **`SolidSessionOCLevels.mq5`** — simpler session/level visualiser (legacy, indicator-only)
4. **`PatternScanner.py`** — Python backtester for strategy research

User's account: **Deriv SVG**, MT5 broker time **UTC+2 (SAST)**, V25 broker `stops_level` = 423 points, min lot 0.5, point 0.001, tick value 0.001. Account size **~$100 USD live, demo for testing**.

---

## The winning strategy (as of 2026-05-29)

**Pattern 9 + SL=2000 / TP=6000 + 13:00 UTC hour filter.** Read [`MODEL_FINDINGS_2026-05-26.md`](MODEL_FINDINGS_2026-05-26.md) first for the full context.

| Parameter | Value |
|---|---|
| Pattern | OC + ICT sessions, M5 trigger (Pattern 9) |
| Configured SL | 2000 ticks (broker_sl = 2000, 1R = $1.00 at 0.5 lot) |
| Configured TP | 6000 ticks ($-R:R = 3.0, break-even WR only 25%) |
| Hour filter | 13:00 UTC ONLY (NY open — the verified edge) |
| Backtest expectancy | +0.122R per trade, 4/4 windows positive |
| Live forecast (×0.7 retention) | ~+$44/year on $100 account |
| Max DD seen in backtest | $26 over 8 months (~26% of account) |

**This is NOT the old +0.841R Pattern 9 number.** That came from running the scanner with no broker friction modelled. See [`DIAGNOSIS_2026-05-22.md`](DIAGNOSIS_2026-05-22.md) for how the original number collapsed and [`MODEL_FINDINGS_2026-05-26.md`](MODEL_FINDINGS_2026-05-26.md) for how we recovered an edge with wide SL + hour filter.

---

## File inventory

### Production files (don't modify without explicit approval)
- `ICTSessionsEA.mq5` — the EA. Defaults are: SL=2000, TP=6000, hour filter ON ("13"). Has per-position risk tracking (day-R denominator bug fixed in code).
- `ICTManualTradeAssist.mq5` — manual-trading indicator: session boxes + OC/CC levels with live ARMED/UNARMED state + 13:00 UTC trade-window highlight + status panel + SL/TP guides.
- `PatternScanner.py` — research backtester. BROKER_PRESETS auto-load real spread/stops_level per symbol; trades report $-frame R-multiple.

### Research scripts (kept — reusable for future analysis)
- `stress_windows.py` — Pattern 9 cross-window stability test (4 non-overlapping 2-mo windows)
- `stress_full.py` — comprehensive 3-phase test: wide-SL extension, hour breakdown, all 9 patterns × 4 configs
- `verify_filters.py` — hour-filter sweep + drawdown profile for chosen config
- `tp_sl_sweep.py` — original TP/SL grid sweep (predates the scanner fix; left for reference)

### Older/legacy MQL5 (kept as fallbacks, do not delete)
- `SolidSessionOCLevels.mq5` — simpler session-box indicator (v2)
- `OpenCloseLevels.mq5`, `GOLDOpenCloseEA.mq5`, `SessionBreakoutEA.mq5`, `SessionLevels.mq5` — older versions

### Documentation (read these before answering questions about state)
- **`MODEL_FINDINGS_2026-05-26.md`** ← read FIRST for current strategy spec + diagnostic story + forecast
- **`SETUP_GUIDE.txt`** — step-by-step deployment instructions (CURRENT — supersedes HOW_TO_INSTALL.txt)
- `CHANGELOG.md` — full history of what's been built and what's pending (Phase 9 is the latest)
- `DIAGNOSIS_2026-05-22.md` — historical record of the EA blowup audit
- `USER_GUIDE.md` — install + usage (PARTIALLY UPDATED — defer to SETUP_GUIDE.txt if conflicts)
- `STRATEGY_REPORT.md` — has STALE +0.841R numbers; flagged with header pointing to MODEL_FINDINGS
- `SELLER_CHECKLIST.md` — productisation guide (strategy-agnostic, still current)
- `HOW_TO_INSTALL.txt`, `OPEN_CLOSE_README.txt` — historical install docs (superseded)

### Analysis logs (evidence of work done — keep)
- `baseline_step1.log`, `step2_tp1330.log`, `stress_windows.log`, `stress_full.log`, `verify_filters.log` — from the 2026-05-26 diagnostic session

---

## Key context that's easy to miss

### Time zones
- MT5 broker time on this account = **UTC+2 (SAST)**
- MT5 chart time = **UTC**
- Log file timestamps = SAST
- EA inputs (`InpAsianOpenH=22` etc.) are in **broker time** (which is what `bar.time` returns)
- When user says "3am" they usually mean **chart time = UTC** which is **5am SAST in logs**

### Symbol scan results
| Symbol | Verdict |
|---|---|
| R_25 (V25) | ✅ Production — Pattern 9 + 13:00 UTC filter +0.122R live |
| R_10 (V10) | ⏳ Re-scan needed under broker-realistic scanner (old +0.811R was idealised) |
| R_50 (V50) | ❌ All patterns negative (re-confirmed under broker model) |
| R_75 (V75) | ❌ Broker stops_level = 10,770, too wide |
| 1HZ* variants | ⏳ Untested, in backlog |

### Critical bugs fixed (in this codebase, in order)
- **State machine** — ARMED/UNARMED per level, re-arms on box re-entry. Eliminates stale-level chains.
- **Broker-correct SL/TP validation** — BUY against Bid, SELL against Ask, with stops_level + freeze_level + spread + safety margin.
- **R:R filter with logged skips** — `[SKIP]` log lines.
- **Per-position risk tracking** (EA lines 120–207) — day-R counter uses actual broker-widened SL, not configured SL. Fixes the 41% under-count bug.
- **Scanner `eff_tp` direction** — was `tp - spread`, corrected to `tp + spread`. Made the −0.350R baseline drop to honest −0.406R.
- **Scanner broker auto-load** — BROKER_PRESETS dict means no more "forgot the flag" idealised reports.

---

## Common user requests and where to find the answer

| User asks | Read this first |
|---|---|
| "What's the strategy?" | `MODEL_FINDINGS_2026-05-26.md` (winning model + forecast) |
| "How do I install?" | `SETUP_GUIDE.txt` (current) |
| "What's done?" | `CHANGELOG.md` |
| "What's next?" | `CHANGELOG.md` (Backlog section) |
| "Why did this trade fire?" | Live log at `C:\Users\User\AppData\Roaming\MetaQuotes\Terminal\6AB79ED795024EC1B7F61552A87628BC\MQL5\Logs\YYYYMMDD.log` |
| "How much will I make?" | `MODEL_FINDINGS_2026-05-26.md` Expected performance table |
| "How many patterns work?" | Only ONE: Pattern 9 with the specific config above. `MODEL_FINDINGS` cross-window data |
| "Should I sell this?" | `SELLER_CHECKLIST.md` |

---

## Operational rules with this user

1. **Never modify EA inputs or code without explicit approval.** This user has lost money on bad changes; always propose, get a "go", then edit.
2. **No new EA file names without checking** — user prefers fixing existing files unless we agreed otherwise.
3. **The user trades a small live account (~$100 USD).** A single wrong trade can wipe a meaningful %. Be cautious with risk-related changes.
4. **Backtest expectancy ≠ live expectancy.** Always cite 60–80% retention in any forecast. Default to 0.7 in tables.
5. **The user has lost prior chat history before.** Keep this CLAUDE.md current after any meaningful change.
6. **For diagnostic work, present full plan once and get one upfront approval; only pause for code/EA edits.** (Saved in memory.)

---

## Common commands

### Run the scanner on V25 (auto-loads broker preset for R_25)
```
py PatternScanner.py --symbol R_25 --years 1 --sl 2000 --tp 6000
```
The scanner auto-applies spread=137, stops_level=423, point=0.001, slippage=2 for R_25. To override, pass `--spread N --stops-level N`. To test the production config, use SL=2000 TP=6000 (current EA defaults).

### Cross-window stress test on Pattern 9
```
py stress_full.py
```
Tests Pattern 9 with extended wide-SL configs + 13:00 hour filter + all patterns × 4 configs across 4 windows. Output: `stress_full.log`.

### Hour-filter + drawdown verification
```
py verify_filters.py
```
Output: `verify_filters.log`.

### Run scanner on a new symbol (re-verify with broker reality)
```
py PatternScanner.py --symbol R_10 --years 1 --sl 2000 --tp 6000 --spread N --stops-level N
```
(Need to look up V10's actual broker spread + stops_level first, then add to `BROKER_PRESETS` in PatternScanner.py.)

### Read today's MT5 logs
```
C:\Users\User\AppData\Roaming\MetaQuotes\Terminal\6AB79ED795024EC1B7F61552A87628BC\MQL5\Logs\YYYYMMDD.log
```

---

## Current state (as of 2026-05-29)

- ✅ Scanner rewritten for broker realism (BROKER_PRESETS, $-frame R-multiple, slippage). Always honest now.
- ✅ Pattern 9 wide-SL + 13:00 UTC filter discovered and cross-window verified (4/4 positive).
- ✅ `ICTSessionsEA.mq5` defaults updated: SL=2000, TP=6000, hour filter ON ("13").
- ✅ Day-R denominator bug already fixed in EA code (per-position risk tracking).
- ✅ `ICTManualTradeAssist.mq5` built and verified working when dragged onto M5 chart.
- ✅ All work committed to git (commit `1c1e3e7`).
- 🔄 **DEMO TESTING IN PROGRESS** — EA on Deriv demo account. Target: 10–14 trading days. Currently early in this window.
- ⏳ V10 broker-realistic re-scan — still on the backlog
- ⏳ 1HZ variants untested
- ⏳ Live deployment — gated on demo verification

---

_When in doubt: read `MODEL_FINDINGS_2026-05-26.md` for the current strategy, then `CHANGELOG.md` for history, then ask the user before making code changes._
