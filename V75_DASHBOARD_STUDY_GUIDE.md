# V75 BEHAVIORAL DASHBOARD — STUDY GUIDE
## Solid Gold Performance

This guide teaches you how to READ the dashboard — what every number means,
when to act on it, and when to ignore it. Written for your ICT-style methodology.

---

## THE ONE IDEA BEHIND EVERYTHING

V75 is not driven by fundamentals. It's driven by an algorithm.
You can't ask "why is it moving?" — only "HOW is it moving?"

The dashboard answers these questions in order:

```
1. REGIME     → What state is the market in?          (Panel A)
2. TIMING     → When does it move cleanly?            (Panel B)
3. SETUP      → What pattern has edge right now?      (Panel C)
4. RISK       → How much should I commit?             (Panel D)
5. TRACK      → Am I actually profitable?             (Panel E)
6. ALERTS     → What just changed?                    (Panel F)
7. INTERPRET  → What does it all mean? (plain English)(Panel G)
8. ASK        → Quick Q&A with live data              (Panel H)
```

Each answer feeds the next. Never skip ahead.
Panels G and H are your shortcut — they synthesize everything above.

---

## PANEL A — MARKET REGIME (The Foundation)

### What It Shows
The market is always in one of four behavioral states:

| Regime | What It Means | What You Do |
|--------|--------------|-------------|
| **TRENDING** | Price has sustained directional momentum. ADX >25, Hurst >0.55 | Trade pullbacks to trend. Follow the momentum. This is where your ICT order blocks work best. |
| **RANGING** | Price is oscillating sideways. ATR compressing, low ADX | Fade the extremes or wait. Mean reversion setups work here. |
| **EXPANDING** | Volatility is spiking. ATR ratio >1.5 | Breakout trades. Get in early or wait for the pullback after expansion. Be careful — this can also be whipsaw. |
| **CHOPPY** | No structure at all. Random walk. Hurst ≈ 0.5, autocorrelation near zero | **SIT OUT.** This is where accounts bleed. No edge exists in random noise. |

### The Numbers That Matter

**Confidence %** — How clearly the market fits the classified regime.
- 70%+ → Strong classification. Trust it.
- 50-70% → Moderate. Regime is probably correct but transitioning.
- <50% → Weak. Market is between states. Be cautious.

**ADX** — Trend strength, not direction.
- >25: Trend is real
- 15-25: Weak trend, could go either way
- <15: No trend at all

**Hurst Exponent** — The most important number most traders ignore.
- >0.55: Market is PERSISTENT — trends continue. Follow them.
- 0.45-0.55: Random walk — no statistical edge in direction.
- <0.45: Market is ANTI-PERSISTENT — it reverses. Fade moves.

**ATR Ratio** — Current volatility vs historical.
- >1.5: Volatility expanding — breakout conditions
- 0.6-1.5: Normal
- <0.6: Compression — something is building

**Autocorrelation** — Do returns predict future returns?
- |>0.3|: Yes — momentum exists. Trend follow.
- |<0.1|: No — each bar is independent. No momentum edge.

### The Multi-Timeframe Strip
Shows regime on ALL timeframes simultaneously.
- If 1H says TRENDING but 4H says RANGING → you're in a pullback within a range.
- If all TFs agree → strongest signal.
- Your ICT quarterly shifts show up here as regime changes on the 4H.

### Sub-Regimes (Read These Carefully)
- **trending_up**: SMA20 > SMA50, price above both. Classic bullish flow.
- **trending_down**: Inverse. Bearish structure.
- **trending_mixed**: Trend strength is there but direction is unclear. Choppy trend.
- **compressing**: ATR is shrinking. This is your pre-breakout phase. Watch closely.
- **breakout_run**: Expansion + multi-candle streak. Already moving.
- **volatility_spike**: Expansion without direction. Could be news or algo reset.

---

## PANEL B — TENDENCY ENGINE (When to Trade)

This panel replaces your manual seasonal/quarterly chart analysis with statistics.

### Hourly Heatmap
Each cell = one hour of the day (UTC). Color tells you:
- **Green** = More bullish bars than expected (>55% bullish)
- **Red** = More bearish bars (>55% bearish)
- **Grey** = Neutral / no bias

**Stars in the corner:**
- *** = 99% confidence this hour is different from average
- ** = 95% confidence
- * = 90% confidence
- No star = Might just be noise

**How to use it:**
Find your green hours with stars. That's when the algorithm statistically trends.
If you're trading at an hour with no star and grey color → you're gambling, not trading.

### Day of Week
Same concept but per weekday. V75 runs 24/7 including weekends.
You may find that certain days have cleaner moves.
- Bar height = bullish percentage
- The significance tag below tells you if it's real or noise

### Sessions
Even though V75 is synthetic, the algorithm may behave differently when
real-market liquidity is present. The sessions defined:
- **Asian (00-08 UTC)**: Often quieter
- **London (08-16 UTC)**: Often more structured
- **LDN/NY Overlap (13-16 UTC)**: Historically the most active window globally
- **New York (16-21 UTC)**: Post-overlap wind-down
- **Late NY (21-00 UTC)**: Off-hours

### Monthly Seasonal Strip
This REPLACES your manual colored seasonal zones.
- Each month shows bullish %, average return, and volatility
- Hover for z-score and sample size
- If a month is green with a high z-score → it's a statistically real seasonal tendency
- If it's colored but z-score is low → small sample, might be noise

### Quarterly View
This REPLACES your manual quarterly shift analysis.
- Q1-Q4 bars show which quarters trend bullish/bearish
- **Phase grid**: Early/Mid/Late breakdown per quarter — where does the move happen?
  - e.g., "Q1 Late" being strongly bullish means March historically pushes up
- **Shift Analysis**: Pre-shift vs post-shift returns. Measures if behavior actually
  changes around quarter boundaries (last 5 days of old Q vs first 5 days of new Q)

### Rolling Momentum (20/40/60-Bar)
This REPLACES your manual 20/40/60-day liquidity projections.
- Shows current directional momentum over each window
- **Return %**: Total return over that window
- **Consistency**: What % of bars were bullish?
  - 70%+ = very consistent trend
  - 50% = no momentum
- **Strength**: Composite of magnitude × consistency (0-1 scale)

### Summary Banner
The verdict that synthesizes everything:
- **BULLISH/BEARISH/NEUTRAL** — what the combined tendency data says right now
- **Strength %** — how strong the consensus is
- **Quality** — HIGH/MED/LOW. High quality = clean moves expected. Low = choppy.

**Decision rule**: Only trade in the direction of the tendency when quality is HIGH.
When quality is LOW, either reduce size or wait.

---

## PANEL C — SETUP SCANNER (What to Trade)

### The 5 Detectors

**1. Compression Breakout (COMP)**
- Bollinger Bands squeeze to historical tight range
- Price breaks out with ATR expansion
- YOUR ICT EQUIVALENT: Consolidation → displacement → expansion
- Best in: RANGING → EXPANDING transition
- Stage "compression" = building. Stage "breakout" = go time.

**2. Pullback to Trend (PULL)**
- ADX confirms trend. Price pulls back to 20 EMA zone.
- Wick rejection at the zone = entry signal
- YOUR ICT EQUIVALENT: Pullback to order block within trend
- Best in: TRENDING regime
- Stage "approaching" = watch it. Stage "rejection" = entry.

**3. Mean Reversion (MR)**
- RSI at extremes (<28 or >72) + Hurst confirms mean-reverting behavior
- Price at Bollinger Band edge
- YOUR ICT EQUIVALENT: Liquidity sweep at range extreme → rejection
- Best in: RANGING regime
- Stage "oversold"/"overbought" = watch for rejection

**4. Streak Exhaustion (EXHST)**
- Current streak length exceeds mean + 1.5 standard deviations
- Returns are shrinking bar-over-bar (momentum dying)
- YOUR ICT EQUIVALENT: Extended move that's run out of steam. Turtle soup.
- Best in: Late TRENDING / EXPANDING

**5. Order Block Touch (OB)**
- Finds historical zones where price made a large candle + displacement
- Detects price returning to that zone with wick rejection
- YOUR ICT EQUIVALENT: This IS your order block methodology, automated.
- Best in: TRENDING regime (OBs with trend have higher probability)

### Reading the Cards

**Confidence (circular gauge)** — How cleanly the pattern matches.
- 65+ = High confidence setup
- 40-65 = Moderate — needs more confirmation
- <40 = Forming / low quality

**Composite Score** — The money number. Confidence × Regime Compatibility.
- 60+ = A+ setup. This is what you wait for.
- 35-60 = Decent but imperfect conditions
- <35 = Setup exists but regime doesn't support it. Dangerous.

**Regime Tag:**
- IDEAL = This setup type thrives in the current regime
- OKAY = It can work but not optimal
- CAUTION = Regime works against this setup type. Reduce size or skip.

**Direction** — Bullish or Bearish. Always trade in the direction shown.

### Multi-Timeframe Scanner Strip
Shows setup count per timeframe. When multiple TFs show setups →
stronger signal. When only one low TF shows a setup → lower confidence.

**KEY RULE**: The best trades happen when Panel A (regime), Panel B (tendency),
and Panel C (setup) ALL agree. Regime supports it. Timing is right. Pattern is clean.

---

## PANEL D — RISK MODULE (How Much to Risk)

### Stop Calculator
Based on ATR (Average True Range) — the market's own volatility measure.

| Stop Type | Distance | When to Use |
|-----------|----------|-------------|
| **Tight** (1× ATR) | Closest stop | Strong conviction setups (IDEAL regime tag + high confidence) |
| **Normal** (1.5× ATR) | Standard stop | Default for most trades |
| **Wide** (2× ATR) | Furthest stop | Low conviction, wider ranges, or higher timeframe trades |

The dashboard shows exact price levels for stop-long and stop-short.

### Position Sizing
```
Lot Size = (Account Balance × Risk %) ÷ Stop Distance
```
This is auto-calculated. The dashboard also scales for volatility:
- High volatility → reduces position size (protection)
- Low volatility → slightly increases (more room)

### R:R Targets
For every stop level, see the take-profit at:
- 1:1.5R (conservative)
- 1:2R (standard — your default)
- 1:3R (aggressive — only for A+ setups)

### Trade Frequency Governor
**This is your discipline enforcer.**
- Green light = You can trade
- Red light = STOP. You've hit your session/daily limit or are on a loss streak.
- Tracks trades per session, per day
- Enforces cooldown after consecutive losses

**Treat the red light as absolute.** The system calculates it based on your actual
trading data. If it says stop, stop.

---

## PANEL E — PERFORMANCE TRACKER (Your Edge Profile)

### Overall Stats
- **Win Rate**: Your actual win rate. Meaningless alone — combine with Profit Factor.
- **Profit Factor**: Total wins ÷ Total losses. >1.5 is good. >2.0 is excellent.
- **Expectancy (R)**: Average R-multiple per trade. Positive = you have edge.
  - This is the single most important number. If negative, something is wrong.
- **Max Drawdown**: Largest peak-to-trough decline. Know your pain tolerance.

### Performance by Regime
THIS IS WHY THE DASHBOARD EXISTS.
- Shows your win rate and expectancy in each regime
- You might discover: "I'm profitable in trending, breakeven in ranging, and bleeding in choppy"
- That tells you: ONLY trade trending regimes. Sit out choppy.

### Performance by Time
- By session and day of week
- Cross-reference with Panel B tendency data
- If Panel B says London session is bullish AND your performance in London is your best →
  that's your edge window. Trade there, nowhere else.

### Performance by Setup
- Which of the 5 detectors actually makes YOU money?
- Maybe Compression Breakout has 70% win rate for you but Mean Reversion is 40%
- Stop trading the setup types where you lose. Double down where you win.

### Equity Curve
- Visual P&L over time
- Green dots = wins, Red dots = losses
- Should trend upward. If flattening or declining → something changed.

---

## PANEL F — ALERTS (What to Watch Right Now)

### Alert Types and What to Do

| Alert | Severity | Action |
|-------|----------|--------|
| **Regime Shift** | Critical (1H/4H) | STOP. Re-evaluate all open positions. The market changed. |
| **Compression** | Warning | PREPARE. A breakout is building. Set your levels. |
| **Time Window** | Info | Note it. A high-performance hour is approaching. Be ready. |
| **Overtrading** | Critical | STOP IMMEDIATELY. Walk away. Review your plan. |
| **Streak Exhaustion** | Warning | Watch for reversal. Don't chase the streak. |
| **Setup Confluence** | Critical | OPPORTUNITY. Multiple high-confidence setups aligned. This is your A+ trade. |

### Priority Rules
1. **Critical alerts override everything**. Regime shift on 1H = close longs if shifted bearish.
2. **Overtrading alert = non-negotiable stop**. Every trader's #1 killer.
3. **Setup confluence = your best trade**. When this fires, you pay full attention.

---

## PANEL G — AI INTERPRETER (The Market Read)

### What It Does
Reads ALL the panels for you and produces a single, plain-English action call.
This is the panel you check first when you're on your phone and need a quick answer.

### The Action Banner
The large text at the top is the dashboard's recommendation:

| Action | Meaning | What You Do |
|--------|---------|-------------|
| **LOOK FOR LONGS** | Regime + tendency + setups all point bullish | Watch for long entries. Don't force shorts. |
| **LOOK FOR SHORTS** | Everything points bearish | Watch for short entries. Don't force longs. |
| **WAIT** | Conditions are mixed or forming | Stay flat. Wait for clarity. |
| **SIT OUT** | Choppy regime, no edge, or conflicting signals | Close the chart. Come back later. |

### Conviction Level
Next to the action, you'll see HIGH / MEDIUM / LOW / NONE:
- **HIGH** = Multiple panels agree strongly. This is your best window.
- **MEDIUM** = Partial agreement. Reduce size.
- **LOW** = Weak signal. Only trade if you see a perfect setup.
- **NONE** = No edge. Don't trade.

### Context Pills
Small tags showing what's driving the recommendation:
- Regime state, tendency direction, active setups, streak info
- These let you quickly verify WHY the interpreter is making its call

### The Narrative
Below the banner, the interpreter writes a paragraph explaining:
1. Current regime and what it means for your trading
2. What tendency data says about timing
3. Which setups are active and whether they're compatible
4. Specific action guidance

### Setup Callout
When a high-confidence setup is active, the interpreter highlights it with:
- Setup name and composite score
- Direction (BULLISH/BEARISH)
- Stage (e.g., "breakout", "rejection")
- Timeframe

**KEY RULE**: The interpreter synthesizes — it doesn't replace your judgment.
Use it as a checklist: if the interpreter says WAIT but you see a clear setup,
check the panels yourself. If they disagree with your read, trust the data.

---

## PANEL H — ASK THE DASHBOARD (Interactive Q&A)

### What It Does
A chat interface where you type questions and get answers based on **live dashboard data**.
Not a general AI — it specifically reads your current panels and answers with real numbers.

### How to Use It
- Type a question or click one of the quick-ask chips
- The answer pulls from live regime, indicator, tendency, setup, and performance data
- Great for quick checks when you can't scan all panels yourself

### What You Can Ask

| Topic | Example Questions |
|-------|-------------------|
| **Regime** | "What's the current regime?" "Is the market trending?" |
| **Indicators** | "What's the ADX?" "Is Hurst persistent?" |
| **Tendency** | "Is there a bullish tendency?" "Best hour to trade?" |
| **Setups** | "Any active setups?" "What's the top setup?" |
| **Risk** | "What lot size should I use?" "Where's the stop?" |
| **Performance** | "What's my win rate?" "Am I profitable?" |
| **Alerts** | "Any active alerts?" "What should I watch?" |
| **Direction** | "Should I go long or short?" "What's the bias?" |

### What It Can't Do
- It doesn't place trades or connect to your broker
- It can't predict what price will do next
- It reads current data, not historical — use Panel E for past performance
- It's rule-based, not AI — answers are consistent but not creative

---

## CLICK-TO-EXPLAIN (Learn While You Trade)

### What It Does
Click any panel header, indicator label, or data element on the dashboard and
a tooltip pops up explaining what that number means and how to use it.

### Why This Matters
- You don't need to keep this study guide open while trading
- The explanations are built into the dashboard itself
- Each explanation includes: what it is, how to read it, and how to use it
- Over time, you'll stop needing the tooltips — the numbers become intuitive

### How to Use
- Click any panel title → explains what the whole panel does
- Click an indicator value → explains that specific metric
- Click regime badge → explains what that regime means for trading
- Click a setup card → explains that setup detector
- Press the X or click outside to dismiss

### 30+ Explainable Elements
Every significant element across all 8 panels has an explanation.
This turns the dashboard into a self-teaching tool — you learn the system
by using it, not by reading documentation.

---

## TELEGRAM ALERTS (Stay Connected on Mobile)

### What It Does
Forwards **critical** and **warning** alerts to your Telegram as instant messages.
You get notified even when you're not looking at the dashboard.

### What Gets Sent
| Severity | Sent to Telegram? | Example |
|----------|-------------------|---------|
| **Critical** | Yes (with sound) | Regime shift on 1H, setup confluence, overtrading |
| **Warning** | Yes (silent) | Compression forming, streak exhaustion |
| **Info** | No (too frequent) | Time window approaching |

### Setup (One Time)
1. Open Telegram, search for **@BotFather**
2. Send `/newbot`, follow the prompts, name it something like "V75 Alerts"
3. BotFather gives you a **token** — save it
4. Start a chat with your new bot, send it any message
5. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
6. Find your **chat_id** in the response JSON
7. Add both to your `D.env` file on the server:
   ```
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   TELEGRAM_CHAT_ID=your_chat_id_here
   ```
8. Restart the dashboard: `sudo systemctl restart v75-dashboard`
9. Test it: visit `http://130.162.58.230:8085/api/telegram/test` (POST request)

### Message Format
```
⚠️ V75 [1H]
Regime Shift: RANGING → TRENDING
Market regime changed to trending_up on the 1H timeframe. Confidence: 78%.
```

Critical alerts send with notification sound. Warning alerts arrive silently.

---

## THE TRADING WORKFLOW

Here's how to use the dashboard from open to close:

### Pre-Session (Before You Trade)
1. Check **Panel A** — What's the regime on your primary TF (1H)?
2. Check **Panel B** — Is this a good time window? Is tendency aligned?
3. Check **Panel C** — Any setups already active?
4. If regime is CHOPPY → don't trade today
5. If tendency quality is LOW → reduce size or wait

### During Session
1. Alerts panel tells you what changed
2. When a **Setup Confluence** alert fires:
   - Confirm regime supports it (Panel A)
   - Confirm tendency is aligned (Panel B)
   - Check composite score (Panel C) — needs 50+
   - Use Panel D to calculate position size and stops
   - Log the trade in Panel E
3. When **Regime Shift** fires:
   - Stop everything. Re-read the panels.
   - New regime = new rules. Old setups may be invalid.

### Post-Session
1. Review Panel E performance
2. Check: Did you trade your best regime? Your best session?
3. Check: Did any "CAUTION" setup trades slip through?
4. Update your notes in the trade log

---

## THE NUMBERS CHEAT SHEET

### "Is this trend real?"
- ADX > 25 + Hurst > 0.55 + Autocorrelation > 0.3 → **YES**
- Any of those missing → **Maybe, reduce size**
- ADX < 15 + Hurst ≈ 0.5 → **NO. It's noise.**

### "Is this breakout real?"
- ATR Ratio > 1.5 + BB expanding + streak 3+ bars → **Likely**
- ATR Ratio > 1.5 but no streak → **Volatility spike, not breakout. Wait.**

### "Should I take this setup?"
- Composite > 60 + IDEAL tag → **Yes (full size)**
- Composite 40-60 + OKAY tag → **Maybe (half size)**
- Composite < 40 OR CAUTION tag → **Skip it**

### "Is this a good time to trade?"
- Tendency: BULLISH/BEARISH + Strength > 60% + Quality HIGH → **Yes**
- Quality LOW OR Strength < 30% → **Not now**

### "Am I overtrading?"
- Red light on frequency governor → **Yes. Stop.**
- 3+ consecutive losses → **Stop. The conditions changed.**
- Trading a CHOPPY regime → **Yes. By definition.**

---

## COMMON MISTAKES THIS DASHBOARD PREVENTS

1. **Trading choppy markets** → Regime panel shows CHOPPY. Don't trade.
2. **Fighting the regime** → Taking mean reversion trades in a trending market.
   The CAUTION tag warns you.
3. **Random entry times** → Tendency engine shows which hours have edge.
   Trading outside those = gambling.
4. **No position sizing** → Risk module forces you to calculate before entry.
5. **Not knowing your edge** → Performance tracker shows WHERE you make money.
   Trade more of that. Less of everything else.
6. **Overtrading** → Frequency governor + alert system. Hard stops.
7. **Missing regime changes** → Regime shift alert fires immediately.
8. **Missing confluence** → Setup confluence alert catches multi-setup alignment.

---

## GLOSSARY

| Term | Meaning |
|------|---------|
| ADX | Average Directional Index — measures trend strength (not direction) |
| ATR | Average True Range — average bar size. Measures volatility. |
| ATR Ratio | Current ATR ÷ Long-term ATR. Shows if volatility is expanding or compressing |
| Autocorrelation | Statistical measure of whether returns predict future returns |
| BB Width | Bollinger Band width — how far apart the bands are |
| Composite Score | Confidence × Regime Compatibility. The final setup quality score |
| Hurst Exponent | Measures if price trends persist (>0.55), revert (<0.45), or is random (~0.5) |
| R-Multiple | Trade P&L expressed as multiples of risk. 2R = you made 2× what you risked |
| Regime | The current market behavioral state (trending/ranging/expanding/choppy) |
| Sub-regime | More specific classification within a regime (e.g., trending_up) |
| Tendency | Statistical bias for a time period (hour, day, month, quarter) |
| Z-score | How many standard deviations from the mean. >1.96 = statistically significant |

---

*Study this guide alongside the live dashboard. The numbers will make more
sense when you see them updating in real time with actual V75 data.*
