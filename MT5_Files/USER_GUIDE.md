# ICT Sessions Trading System — User Guide

A complete guide to every file in this package, what it does, and how to use it.

---

## 1. What's in this package

```
MT5_Files/
├── ICTSessionsEA.mq5         ← THE PRODUCTION EA (Pattern 9, ICT sessions)
├── SessionOCLevels.mq5       ← Visual indicator (session boxes + OC/CC levels)
├── PatternScanner.py         ← Python backtester for strategy research
│
├── OpenCloseEA.mq5           ← Original ICT EA (older sessions, kept as fallback)
├── GOLDOpenCloseEA.mq5       ← Mid-development EA (state-machine version of OpenCloseEA)
├── SessionBreakoutEA.mq5     ← v1 EA (broader session H/L breakout, deprecated)
├── SessionLevels.mq5         ← v1 indicator (with FVGs and OBs, deprecated)
│
├── CHANGELOG.md              ← What's been built and what's next
├── USER_GUIDE.md             ← This file
├── STRATEGY_REPORT.md        ← Detailed strategy results across symbols
├── SELLER_CHECKLIST.md       ← For productising / selling
├── HOW_TO_INSTALL.txt        ← Quick install steps for the EA
├── OPEN_CLOSE_README.txt     ← Strategy explanation
└── scanner_results.csv       ← Last full scanner output (every trade tested)
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

**The trade rules:**
1. When an M5 candle closes ABOVE a tracked HIGH → BUY at next ask, SL = entry − 500 ticks, TP = entry + 940 ticks
2. When an M5 candle closes BELOW a tracked LOW → SELL at next bid, SL = entry + 500 ticks, TP = entry − 940 ticks
3. After a trade fires, that level becomes UNARMED. It must wait for price to close back inside its box before it can fire again.

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
InpSLMode        = 1        ←1 = fixed ticks (Pattern 9 backtest)
InpFixedSLTicks  = 500      ←= 0.5 price units on V25
InpTPTicks       = 940      ←= 0.94 price units (R:R 1:1.875)

─ Risk ──
InpUseDailyStop    = true
InpDailyMaxLossR   = 3.0    ←pause trading after 3R loss in a day

─ Hour filter ──
InpUseHourFilter = false    ←off by default; the state machine handles freshness
```

### `SessionOCLevels.mq5` — the visual

**What it does:** Draws on your chart what the EA is "seeing" internally. Visualises the 6 session boxes and OC/CC candle high/low levels.

| What you'll see | Means |
|---|---|
| Solid blue lines | Asia OPEN candle HIGH and LOW |
| Dashed blue lines | Asia CLOSE candle HIGH and LOW |
| Solid green lines | London OPEN candle HIGH and LOW |
| Dashed green lines | London CLOSE candle HIGH and LOW |
| Solid orange lines | NY OPEN candle HIGH and LOW |
| Dashed orange lines | NY CLOSE candle HIGH and LOW |
| Light shaded box per session | Session range (high-to-low) as it progresses |
| Dotted vertical lines | Where each session ends |

**Today only:** at 22:00 UTC (Asia open = start of new trading day) all previous-day objects are wiped and the chart starts fresh.

### `PatternScanner.py` — the researcher

**What it does:** Pulls 1 year of M5 candles from the Deriv API, then simulates 10 different ICT-style strategies and prints a full statistical report. Used to validate strategies BEFORE risking real money.

**Run:**
```
py PatternScanner.py --symbol R_25 --years 1 --point 0.001 --sl 500 --tp 940
```

**Arguments:**
| Flag | Default | Meaning |
|---|---|---|
| `--symbol` | R_75 | Deriv symbol code (R_10, R_25, R_50, R_75, 1HZ25V, etc.) |
| `--years` | 1.0 | How much history to fetch |
| `--point` | 0.01 | Tick size for the symbol (V25 = 0.001) |
| `--sl` | 40 | SL distance in "ticks" (the `--point` units) |
| `--tp` | 75 | TP distance in "ticks" |
| `--hard-sl-mult` | 1.0 | (Pattern 8 only) hard SL multiplier of box height |

Results print to console and every trade goes to `scanner_results.csv`.

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

Based on Pattern 9 backtest (8 months R_25 M5 data):

| Metric | Backtest | Realistic live estimate |
|---|---|---|
| Trades per day | ~10 | 5–12 |
| Win rate | 63.9% | 55–62% |
| Average R per trade | +0.841R | +0.40 to +0.60R |
| Avg $ per trade (at 0.5 lot) | +$0.21 | +$0.10 to +$0.15 |
| Daily expectancy | +$2.10 | +$1.00 to +$1.50 |
| Worst single trade | −1R (= −$0.25) | up to −2R if slippage |

**Important:** Backtests have look-ahead bias (TP and SL in same bar both count as wins). Live will be lower. Plan for ~60–70% of backtest figures, not 100%.

---

## 9. When to seek help

- Multiple "invalid stops" errors in a row → broker may have changed minimums; paste log and ask
- EA stops trading for days with no logs → MT5 likely disconnected from server
- Live win rate drops below 50% over 100+ trades → strategy may have decayed, re-run scanner
- Account balance drops more than 30% from peak → STOP and reassess; don't average down

---

_See `STRATEGY_REPORT.md` for detailed strategy results across all tested symbols._
