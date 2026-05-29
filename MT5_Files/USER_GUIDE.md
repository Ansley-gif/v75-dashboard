# ICT Sessions Trading System — User Guide

A complete guide to every file in this package, what it does, and how to use it.

> **For the CURRENT install + deployment steps, prefer `SETUP_GUIDE.txt`** —
> it reflects the post-2026-05-26 strategy update (SL=2000/TP=6000 + 13:00
> UTC filter). This guide is kept as background reference but some sections
> (EA defaults, expected performance) are flagged below where they differ
> from current production.

---

## 1. What's in this package

```
MT5_Files/
├── ICTSessionsEA.mq5            ← THE PRODUCTION EA
├── ICTManualTradeAssist.mq5     ← Manual-trading indicator (NEW, matches EA)
├── SolidSessionOCLevels.mq5     ← Simpler session-box visualiser (legacy)
├── PatternScanner.py            ← Python backtester (broker-realistic)
│
├── stress_windows.py            ← Cross-window stability test
├── stress_full.py               ← Comprehensive 3-phase stress test
├── verify_filters.py            ← Hour-filter + drawdown verification
│
├── OpenCloseLevels.mq5          ← Original ICT EA (older sessions, fallback)
├── GOLDOpenCloseEA.mq5          ← Mid-development EA (state-machine version)
├── SessionBreakoutEA.mq5        ← v1 EA (broader strategy, deprecated)
├── SessionLevels.mq5            ← v1 indicator (with FVGs and OBs, deprecated)
│
├── MODEL_FINDINGS_2026-05-26.md ← ★ Winning model spec + diagnostic story
├── DIAGNOSIS_2026-05-22.md      ← The EA blowup audit
├── SETUP_GUIDE.txt              ← ★ Current step-by-step install + run guide
├── CHANGELOG.md                 ← What's been built and what's next
├── USER_GUIDE.md                ← This file
├── STRATEGY_REPORT.md           ← Historical results (STALE — see MODEL_FINDINGS)
├── SELLER_CHECKLIST.md          ← For productising / selling
├── HOW_TO_INSTALL.txt           ← Original install steps (superseded by SETUP_GUIDE)
├── OPEN_CLOSE_README.txt        ← Historical strategy explanation
└── *.log                        ← Analysis output from the 2026-05-26 work
```

---

## 2. The two main tools

### `ICTSessionsEA.mq5` — the trader

**What it does:** Trades V25 (Volatility 25 Index) on the 5-minute chart. Watches 6 specific candles per day (the first candle of each ICT session and the first candle after each session ends). When price closes past any of those candles' highs or lows, it enters a trade in the breakout direction.

**Why these 6 candles:** ICT methodology says institutional algos respect session opens and closes as liquidity anchors. The first 5-min candle of a session frames the institutional bias; price reactions at its high/low are statistically meaningful.

**The 6 watched candles (UTC):**
| Tag | What it is | When it forms |
|---|---|---|
| `ASIA_OC` | First M5 of Asia session | 22:00 UTC |
| `ASIA_CC` | First M5 after Asia ends | 09:00 UTC |
| `LDN_OC` | First M5 of London session | 07:00 UTC |
| `LDN_CC` | First M5 after London ends | 16:00 UTC |
| `NY_OC` | First M5 of NY session | 13:00 UTC |
| `NY_CC` | First M5 after NY ends | 22:00 UTC (same bar as next Asia_OC) |

Each candle's HIGH and LOW become breakout levels that live for 24 hours. So at any moment there are up to 12 active levels (6 candles × HIGH + LOW).

**The trade rules (CURRENT DEFAULTS as of 2026-05-29):**
1. When an M5 candle closes ABOVE a tracked HIGH **at 13:00 UTC** → BUY at next ask, SL = entry − 2000 ticks, TP = entry + 6000 ticks
2. When an M5 candle closes BELOW a tracked LOW **at 13:00 UTC** → SELL at next bid, SL = entry + 2000 ticks, TP = entry − 6000 ticks
3. After a trade fires, that level becomes UNARMED. It must wait for price to close back inside its box before it can fire again.
4. **Outside 13:00 UTC the hour filter blocks entries** — the EA logs `[SKIP] hour filter blocked` instead of trading.

**Inputs at a glance (defaults are correct — usually leave alone):**

```
─ Sessions (UTC) ──
InpAsianOpenH    = 22       ←ICT KillZone Asia open
InpAsianCloseH   = 9
InpLondonOpenH   = 7
InpLondonCloseH  = 16
InpNYOpenH       = 13
InpNYCloseH      = 22

─ Trade ──
InpLotSize       = 0.5      ←V25 broker minimum
InpMagic         = 25009    ←unique to this EA

─ Stop loss ──
InpSLMode        = 1        ←1 = fixed ticks (current)
InpFixedSLTicks  = 2000     ←= 2.0 price units on V25 (1R = $1.00 at 0.5 lot)
InpTPTicks       = 6000     ←= 6.0 price units (R:R 1:3.0, BE WR only 25%)

─ Risk ──
InpUseDailyStop    = true
InpDailyMaxLossR   = 3.0    ←pause trading after 3R loss in a day

─ Hour filter ──
InpUseHourFilter = true     ←ON — only 13:00 UTC trades (verified 4/4 windows)
InpHoursAllowed  = "13"     ←NY open only
```

**Why these specific numbers?** See `MODEL_FINDINGS_2026-05-26.md`. Short version: wider SL is needed because V25's M5 noise eats SL<2000. 13:00 UTC is the only hour that's consistently positive across 4 non-overlapping 2-month windows.

### `ICTManualTradeAssist.mq5` — the manual-trading companion

**What it does:** Shows exactly what the EA sees so you can hand-trade the same setups. Visualises session boxes, OC/CC level lines with live ARMED/UNARMED state, highlights the 13:00 UTC trade window, and shows status panel + SL/TP guides.

| What you'll see | Means |
|---|---|
| Solid coloured lines (blue/green/orange) | OPEN candle HIGH/LOW levels for each session |
| Dashed coloured lines | CLOSE candle HIGH/LOW levels for each session |
| `[ARMED]` next to a level label | Level is live — a close past it will fire a trade (inside 13:00 UTC window) |
| `[UNARMED]` next to a level label | Level already fired today — needs box re-entry to re-arm |
| Light shaded box per session | Session range (high-to-low) as it progresses |
| Pale green vertical band | 13:00 UTC trade window (only hour the EA will fire) |
| Red dotted horizontal lines | SL guides at ±2000 ticks from current bid |
| Green dotted horizontal lines | TP guides at ±6000 ticks from current bid |
| Status panel (top-left) | UTC time, countdown to next 13:00, armed levels list, today's signal count |

**Recommended install:** see `SETUP_GUIDE.txt` Part 3 — drag onto an M5 V25 chart, then save your own template via MT5's "Save Template" UI.

### `SolidSessionOCLevels.mq5` — legacy simpler visualiser

Kept around as a lightweight alternative. Just draws session boxes + OC/CC lines without the ARMED state, panel, or trade-window highlight. Use `ICTManualTradeAssist.mq5` for the production strategy.

### `PatternScanner.py` — the researcher (BROKER-REALISTIC)

**What it does:** Pulls up to ~8 months of M5 candles from the Deriv API, simulates 10 different ICT-style strategies under broker reality (spread + stops_level + slippage), and prints a $-frame statistical report. Used to validate strategies BEFORE risking real money.

**Run (current production config):**
```
py PatternScanner.py --symbol R_25 --years 1 --sl 2000 --tp 6000
```
The scanner auto-loads `BROKER_PRESETS["R_25"]` = spread 137, stops_level 423, point 0.001, slippage 2.

**Arguments:**
| Flag | Default | Meaning |
|---|---|---|
| `--symbol` | R_75 | Deriv symbol code (R_10, R_25, R_50, R_75, 1HZ25V, etc.) |
| `--years` | 1.0 | How much history to fetch |
| `--point` | 0.01 | Tick size for the symbol (V25 = 0.001, auto-loaded for R_25) |
| `--sl` | 40 | Configured SL distance in ticks (broker may widen via stops_level) |
| `--tp` | 75 | Configured TP distance in ticks |
| `--spread` | 0 | Broker spread in ticks (auto-loaded for known symbols) |
| `--stops-level` | 0 | Broker stops_level in ticks (auto-loaded for known symbols) |
| `--slippage` | 2 | Entry slippage in ticks (adverse fill beyond spread) |
| `--hard-sl-mult` | 1.0 | (Pattern 8 only) hard SL multiplier of box height |

If running an unrecognised symbol with no `--spread/--stops-level`, the scanner prints a LOUD WARNING banner and produces an idealised (untrustworthy) report.

Results print to console with $-frame R-multiple per trade. Every trade is also written to `scanner_results.csv`.

---

## 3. Install & start trading

### One-time setup
1. Open MT5 → **File → Open Data Folder**.
2. Copy `ICTSessionsEA.mq5` to `MQL5\Experts\`.
3. Copy `SessionOCLevels.mq5` to `MQL5\Indicators\`.
4. Open MetaEditor (F4) → open each file → press **F7** to compile. Both should say "0 errors, 0 warnings".

### Each time you want to trade
1. In MT5, open a chart for **Volatility 25 Index**.
2. Switch timeframe to **M5** (required).
3. From Navigator → Indicators, drag **SessionOCLevels** onto chart. Click OK.
4. From Navigator → Expert Advisors, drag **ICTSessionsEA** onto chart. Click OK.
5. Click the **Algo Trading** button in the top toolbar — it should turn green.
6. Check the smiley face on the chart (top-right next to EA name) — must be 🙂 (smiling, not sad).
7. Open Toolbox (Ctrl+T) → **Experts** tab to watch logs.

### Confirming it's running
You should see in the Experts tab within 5 minutes of attaching:
```
═══════ ICTSessionsEA started (Pattern 9, V25) ═══════
Symbol         : Volatility 25 Index
Stops level    : 423 points
Min lot        : 0.500
...
```

Then at each session hour (UTC 22:00, 9:00, 7:00, 16:00, 13:00, 22:00) you'll see:
```
[LEVEL] ASIA_OC  H=2925.40300  L=2920.10000  TTL=22:00
```

When a level is broken:
```
>> SELL LDN_CC_L @2914.20700  SL=2914.70700 (500 tk)  TP=2913.26700 (940 tk)  R:R=1:1.88
```

When a level re-arms after price returns inside:
```
[RE-ARM] LDN_CC_L armed by close 2915.10500 (level 2914.20700)
```

---

## 4. Reading the trade tags

Every trade is tagged with its source level so you can audit it:

```
ICT_BUY:NY_OC_H        ← BUY on break above NY OPEN candle HIGH
ICT_SELL:LDN_CC_L      ← SELL on break below London CLOSE candle LOW
ICT_BUY:ASIA_CC_H      ← BUY on break above Asia CLOSE candle HIGH
```

Format is `ICT_<direction>:<SESSION>_<KIND>_<SIDE>` where:
- `SESSION` = ASIA / LDN / NY
- `KIND` = OC (open candle) / CC (close candle)
- `SIDE` = H (high) / L (low)

---

## 5. Sanity checks before going live

| Check | How |
|---|---|
| Chart is V25 (not V75 or another symbol) | Top-left of chart shows "Volatility 25 Index" |
| Timeframe is M5 | Top-left of toolbar M5 button is highlighted |
| Algo Trading is ON | Toolbar button is green |
| EA smile | Top-right of chart, next to "ICTSessionsEA", should be 🙂 |
| Account has enough margin | Min lot 0.5 on V25 ≈ $0.50 margin needed per trade |
| Daily stop active | `InpUseDailyStop = true` and `InpDailyMaxLossR = 3` |
| No conflicting EA on same chart | Only one EA per chart per magic number |
| PC won't sleep | Settings → Power → Sleep = Never |

---

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "invalid stops" error in log | Broker stops_level changed | EA already handles this; if persists, check OnInit log for new `Stops level` value |
| No trades for hours | All levels UNARMED, or no breakout signals, or hour filter on | Check Experts tab for `[LEVEL]` and `[SKIP]` lines |
| EA shows "Daily loss limit reached" | Hit 3R loss for the day | Wait for next UTC day rollover (00:00 UTC) |
| "InpLotSize ... is BELOW broker minimum" warning | V25 min lot changed | Raise `InpLotSize` to match the alert |
| 🙁 sad face on EA | Algo Trading is OFF | Click the green Algo Trading button in toolbar |
| Lines from yesterday still visible | Indicator was attached before today's 22:00 UTC | Wait — they clear automatically at the next Asia open |

---

## 7. Don't do these

- Don't run the EA on a symbol other than V25 without re-running the scanner first
- Don't change `InpSLMode` to 0 unless you understand the catastrophic-SL risk on giant candles
- Don't turn off `InpUseDailyStop` — it's your account protection
- Don't run multiple EA instances on the same V25 chart (they'll conflict)
- Don't trade live without 1+ week of demo verification first

---

## 8. Expected performance

Based on the broker-realistic backtest of Pattern 9 + SL=2000/TP=6000 + 13:00 UTC filter (2026-05-26 stress test, 8 months R_25 M5 data, 4 non-overlapping 2-month windows):

| Metric | Backtest | Live (×0.7 retention) |
|---|---:|---:|
| Trades per day | ~1–2 | ~1–2 |
| Win rate | 28.1% | 24–32% expected |
| Average R per win (=$ R:R) | +3.0R = +$3.00 | same |
| Loss per stop | −1R = −$1.00 | same |
| Expectancy per trade | +0.122R = +$0.122 | +0.087R = +$0.087 |
| Trades per year | ~504 | ~504 |
| Annual P/L on $100 acct | ~+$62 | **~+$44** |
| Worst 2-month DD seen | −$25 (25% of $100) | similar |
| Longest losing streak seen | 12 trades | similar |
| Probability of profitable year | 86% | similar |

**Important:** This is a much smaller edge than the original `+0.841R` STRATEGY_REPORT figure — the old number came from the scanner without broker friction modelled. The current numbers reflect 2x spread + slippage + broker-widened SL.

**Variance dominates short-term outcomes.** Plan to see losing weeks (−$5 in a week is normal), occasional losing months (−$10 to −$15), and rare losing quarters. Don't sit on the EA's shoulder; check at the end of each week, not each day. See `MODEL_FINDINGS_2026-05-26.md` for the full forecast tables.

---

## 9. When to seek help

- Multiple "invalid stops" errors in a row → broker may have changed minimums; paste log and ask
- EA stops trading for days with no logs → MT5 likely disconnected from server
- Live win rate drops below 18% over 100+ trades → strategy may have decayed, re-run scanner. (Target WR is ~28%, so allow 22–34% before worrying.)
- 13:00 UTC passes with armed levels but no trade fires → confirm hour filter is reading UTC not broker time; check Experts log for `[SKIP] hour filter blocked`
- Account balance drops more than 30% from peak → STOP and reassess; don't average down
- Average $-R per win drops below $2.00 → live spread + slippage is worse than modeled; tighten the scanner's BROKER_PRESETS to match reality and re-test

---

_See `STRATEGY_REPORT.md` for detailed strategy results across all tested symbols._
