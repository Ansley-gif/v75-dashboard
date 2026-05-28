# CLAUDE.md — Project brief for Claude Code sessions

This file is read automatically by Claude Code when it starts in this directory. It's the handover note so you (Claude) know what this project is, what's been built, and what's pending without me having to re-explain every session.

---

## What this project is

ICT-style breakout trading system for **Deriv's Volatility 25 Index (V25 / R_25)** on MT5, M5 timeframe. The system has three parts:

1. **`ICTSessionsEA.mq5`** — the production Expert Advisor (current strategy)
2. **`SessionOCLevels.mq5`** — chart indicator showing session boxes + OC/CC levels
3. **`PatternScanner.py`** — Python backtester for strategy research

User's account: **Deriv SVG**, MT5 broker time **UTC+2 (SAST)**, V25 broker `stops_level` = 423 points, min lot 0.5, point 0.001, tick value 0.001.

---

## File inventory

### Production files (don't modify without explicit approval)
- `ICTSessionsEA.mq5` — the EA we currently trade. Pattern 9 baked in.
- `SessionOCLevels.mq5` — the chart indicator (v2, with shaded boxes, today-only)
- `PatternScanner.py` — research backtester, fetches Deriv API + simulates strategies

### Older EAs (kept as fallbacks, do not delete)
- `OpenCloseEA.mq5` — original ICT EA, older session times
- `GOLDOpenCloseEA.mq5` — mid-development EA with ARMED/UNARMED state machine but OLD session times
- `SessionBreakoutEA.mq5` — v1 broader strategy (deprecated)
- `SessionLevels.mq5` — v1 indicator (deprecated)

### Documentation (the source of truth — read these before answering questions about state)
- `CHANGELOG.md` — full history of what's been built and what's pending
- `USER_GUIDE.md` — install + usage for every tool
- `STRATEGY_REPORT.md` — all 10 patterns and their backtest results
- `SELLER_CHECKLIST.md` — productisation guide (legal, license, support)
- `HOW_TO_INSTALL.txt`, `OPEN_CLOSE_README.txt` — original strategy docs
- `scanner_results.csv` — raw output of the last full backtest

---

## The 10 patterns (full list)

The scanner tests all 10. **Pattern 9 is the production winner.**

| # | Pattern | V25 Expectancy | Trades | Status |
|---|---|---|---|---|
| 1 | Session H/L Breakout | +0.793R | 1,070 | ✅ Positive |
| 2 | London Breakout of Asian Range | +0.007R | 134 | ⚠️ Tiny edge |
| 3 | NY Open Reversal (Judas Swing) | +0.236R | 238 | ✅ Positive |
| 4 | Opening Range Breakout (30-min) | −0.009R | 1,157 | ❌ Negative |
| 5 | Consolidation Squeeze | No trades | 0 | ⚠️ Doesn't fit V25 |
| 6 | Previous Session Level Run | +0.774R | 633 | ✅ Positive |
| 7A | OC Candle — SL=candle extreme | +0.001R | 2,672 | ⚠️ Flat |
| 7B | OC Candle — SL=fixed ticks | +0.762R | 2,672 | ✅ Positive (baseline) |
| 7C | OC Candle — SL=tighter of both | +0.762R | 2,672 | ✅ Positive |
| 8 | OC Box Flip + hard SL | −0.013R | 87,877 | ❌ Negative |
| **9** | **OC + ICT Sessions, M5 trigger** | **+0.841R** | **2,656** | ✅ **PRODUCTION** |
| 10 | OC + ICT Sessions, H1 trigger | +0.783R | 2,450 | ✅ Positive but worse than 9 |

(Pattern 7 has 3 sub-variants A/B/C, hence 12 numbered rows for 10 patterns.)

For the full detail per pattern, monthly breakdown, and cross-symbol results: read `STRATEGY_REPORT.md`.

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
| R_25 (V25) | ✅ Production — Pattern 9 +0.841R |
| R_10 (V10) | 🔄 +0.811R at native scale, needs re-verify at broker scale |
| R_50 (V50) | ❌ All patterns negative |
| R_75 (V75) | ❌ Broker stops_level = 10,770, too wide |
| 1HZ* variants | ⏳ Untested, in backlog |

### Critical bugs fixed (state-machine logic)
The current ICTSessionsEA includes:
- **ARMED/UNARMED state machine** per level — fires once, must wait for box re-entry to re-arm. Solves the "stale level fires 13 hours later" bug.
- **Broker-correct SL/TP validation** — BUY validated against Bid, SELL against Ask, plus stops_level + freeze_level + spread + safety margin.
- **R:R filter with logged skips** — `[SKIP]` log lines for filtered-out signals.

---

## Common user requests and where to find the answer

| User asks | Read this first |
|---|---|
| "How many patterns?" | `STRATEGY_REPORT.md` or this file's table above |
| "What's done?" | `CHANGELOG.md` |
| "What's next?" | `CHANGELOG.md` (Backlog section) |
| "How do I install?" | `USER_GUIDE.md` |
| "Why did this trade fire?" | Read the live log at `C:\Users\User\AppData\Roaming\MetaQuotes\Terminal\6AB79ED795024EC1B7F61552A87628BC\MQL5\Logs\YYYYMMDD.log` |
| "Should I sell this?" | `SELLER_CHECKLIST.md` |

---

## Operational rules with this user

1. **Never modify EA inputs or code without explicit approval.** This user has lost money on bad changes; always propose, get a "go", then edit.
2. **No new EA file names without checking** — user prefers fixing existing files unless we agreed otherwise.
3. **The user trades a small live account (~$5–10 USD).** A single wrong trade can wipe a meaningful % — be cautious with risk-related changes.
4. **Backtest expectancy ≠ live expectancy.** Always cite ~60–80% retention in any forecast.
5. **The user has lost prior chat history before.** Keep this CLAUDE.md current after any meaningful change.

---

## Common commands

### Run the scanner on V25 with current settings
```
py PatternScanner.py --symbol R_25 --years 1 --point 0.001 --sl 500 --tp 940
```

### Run scanner on V10
```
py PatternScanner.py --symbol R_10 --years 1 --point 0.001 --sl 500 --tp 940
```

### Run scanner on a 1HZ variant
```
py PatternScanner.py --symbol 1HZ25V --years 1 --point 0.001 --sl 500 --tp 940
```

### Read today's MT5 logs
The path is:
```
C:\Users\User\AppData\Roaming\MetaQuotes\Terminal\6AB79ED795024EC1B7F61552A87628BC\MQL5\Logs\YYYYMMDD.log
```

---

## Current state (as of 2026-05-13)

- ✅ `ICTSessionsEA.mq5` built and ready, defaults set to Pattern 9 specs
- ⏳ User has not yet demo-tested the production EA for the full 1-2 weeks
- ⏳ V10 re-scan with broker-correct parameters is the next "high priority" backlog item
- ⏳ 1HZ variants untested

---

_When in doubt: read the four .md files, then ask the user before making code changes._
