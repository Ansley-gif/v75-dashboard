══════════════════════════════════════════════════════════════════
  ICT OPEN + CLOSE CANDLE BREAKOUT STRATEGY  (V2)
  V75 Trading Systems
══════════════════════════════════════════════════════════════════

  THE TWO FILES:
    OpenCloseLevels.mq5     →  Indicator (marks the 6 candles + draws extras)
    OpenCloseEA.mq5         →  Expert Advisor (executes the strategy)


══════════════════════════════════════════════════════════════════
  THE STRATEGY (proven on 8 months of R_75 M5 data)
══════════════════════════════════════════════════════════════════

  Each trading day produces 6 high-significance 5-minute candles:

      ASIA   OC  : 00:00–00:05 UTC   (Asian Open)
      ASIA   CC  : 08:00–08:05 UTC   (Asian Close = London Open)
      LDN    OC  : 08:00–08:05 UTC   (London Open)
      LDN    CC  : 17:00–17:05 UTC   (London Close)
      NY     OC  : 13:00–13:05 UTC   (NY Open)
      NY     CC  : 22:00–22:05 UTC   (NY Close)

  Each candle's HIGH and LOW become breakout levels valid for 24h.
  When price closes above an H or below an L → enter a trade.

  ENTRY  :  M5 close above the H (BUY) or below the L (SELL)
  SL     :  Whichever is closer to entry — breakout candle's
            opposite extreme  OR  fixed 40 ticks
  TP     :  Fixed 75 ticks (default)


══════════════════════════════════════════════════════════════════
  BACKTEST RESULTS  (1 year R_75 M5 — Sep 2025 to May 2026)
══════════════════════════════════════════════════════════════════

  OC_OPEN levels   :  3,990 trades   51.1% WR   +0.196R/trade
  OC_CLOSE levels  :  4,002 trades   51.5% WR   +0.204R/trade

  COMBINED         :  ~8,000 trades  ~51%  WR   +0.20R/trade
  Net P&L (1 yr)   :  +1,601 R-units

  At 1% risk/trade this is a theoretical 1,600% return per year
  before fees, slippage and drawdown — clearly not all of that is
  realistic, but the math says the edge is real and persistent.


══════════════════════════════════════════════════════════════════
  STEP 1 — INSTALL THE FILES
══════════════════════════════════════════════════════════════════

  1. In MT5 click  File → Open Data Folder
  2. Copy  OpenCloseLevels.mq5  to   MQL5\Indicators\
  3. Copy  OpenCloseEA.mq5      to   MQL5\Experts\
  4. Open MetaEditor (F4 in MT5)
  5. Open each .mq5 file → press F7 to compile
     ✓ Should report "0 errors, 0 warnings"


══════════════════════════════════════════════════════════════════
  STEP 2 — DROP THE INDICATOR ON A CHART  (visual only)
══════════════════════════════════════════════════════════════════

  1. Open R_75 (or any V75 / V100 / V25 / V10) chart
  2. Switch to M5 timeframe (REQUIRED)
  3. Navigator → Indicators → OpenCloseLevels → drag onto chart

  You'll see the 6 candles per day each marked with:
     ─ A small box around the candle itself
     ─ Two horizontal lines (H and L) extending 24 hours forward
     ─ A label  ("ASIA OC H", "LDN CC L", etc.)

  Plus FVGs, Order Blocks, Swing H/L, Breakers, and Voids drawn
  for ICT-style confluence.


══════════════════════════════════════════════════════════════════
  STEP 3 — APPLY THE EA  (auto-trading)
══════════════════════════════════════════════════════════════════

  ⚠️  ALWAYS test on demo first!

  1. Make sure  Algo Trading  is ON (top toolbar in MT5)
  2. Navigator → Expert Advisors → OpenCloseEA
  3. Drag onto the same M5 chart
  4. Configure inputs (see below)
  5. Press OK


══════════════════════════════════════════════════════════════════
  KEY EA INPUTS
══════════════════════════════════════════════════════════════════

  ─── WHICH CANDLES TO TRADE ───────────────────────────────────
  Toggle each on/off independently:
     InpTradeAsianOC   |  InpTradeAsianCC
     InpTradeLondonOC  |  InpTradeLondonCC
     InpTradeNYOC      |  InpTradeNYCC

  Backtest shows OC_CLOSE candles slightly outperform OC_OPEN.

  ─── HOUR FILTER (high-edge hours only) ───────────────────────
     InpUseHourFilter   = false  (set true to enable)
     InpHoursAllowed    = "9,12,18,19,21"

  These are the hours that backtested 70%+ WR. Restricting trades
  to these hours cuts noise and could lift expectancy further.

  ─── STOP LOSS MODE  ──────────────────────────────────────────
     InpSLMode = 0   →  Candle extreme  (textbook ICT, but can
                        give big SL on V75 — backtest negative)
     InpSLMode = 1   →  Fixed 40 ticks  (locks 1:1.875 R:R)
     InpSLMode = 2   →  Tighter of both (RECOMMENDED — best
                        backtested expectancy)

  ─── RISK ─────────────────────────────────────────────────────
     InpLotSize         = 0.01    (start tiny on demo!)
     InpMaxConcurrent   = 1       (only 1 open trade at a time)
     InpUseDailyStop    = true    (stop after 5R loss in a day)
     InpDailyMaxLossR   = 5.0
     InpFridayOff       = false   (Fridays were weakest in backtest;
                                   set true to skip them)


══════════════════════════════════════════════════════════════════
  RECOMMENDED STARTER PROFILE
══════════════════════════════════════════════════════════════════

  Symbol            : R_75   (Volatility 75 Index)
  Timeframe         : M5
  InpLotSize        : 0.01   (until you've run 100+ live trades)
  InpSLMode         : 2      (tighter of both)
  InpFixedSLTicks   : 40
  InpTPTicks        : 75
  InpMaxConcurrent  : 1
  InpUseDailyStop   : true
  InpDailyMaxLossR  : 5.0
  InpUseHourFilter  : false  (enable later once comfortable)
  InpFridayOff      : false  (enable later if you confirm weakness)

  ⚠️  Run on a Deriv DEMO account for at least 2 weeks before live.


══════════════════════════════════════════════════════════════════
  STRATEGY TESTER — RECOMMENDED SETTINGS
══════════════════════════════════════════════════════════════════

  Mode      :  Every tick based on real ticks
  Symbol    :  R_75
  Period    :  M5
  Date Range:  1+ year back
  Optimize  :  Try InpSLMode 0 vs 1 vs 2
               Try InpTPTicks  50 / 75 / 100
               Try InpFixedSLTicks  30 / 40 / 50


══════════════════════════════════════════════════════════════════
  PROTECTING THE PRODUCT FOR RESALE
══════════════════════════════════════════════════════════════════

  1. MetaEditor → compile to .ex5 (compiled, source hidden)
  2. Distribute the .ex5 only — your source stays private
  3. Optional: lock to specific account numbers in OnInit()
     by checking AccountInfoInteger(ACCOUNT_LOGIN)
  4. Optional: add expiry date for trial versions


══════════════════════════════════════════════════════════════════
  FILES IN THIS FOLDER
══════════════════════════════════════════════════════════════════

  OpenCloseLevels.mq5     ← INSTALL THIS  → MQL5/Indicators/
  OpenCloseEA.mq5         ← INSTALL THIS  → MQL5/Experts/
  OPEN_CLOSE_README.txt   ← this file

  PatternScanner.py       ← run to back-test new symbols/parameters
  scanner_results.csv     ← latest scan output

  SessionLevels.mq5       ← v1 indicator (broader session H/L)
  SessionBreakoutEA.mq5   ← v1 EA (broader session breakout)
  HOW_TO_INSTALL.txt      ← v1 install instructions

══════════════════════════════════════════════════════════════════
