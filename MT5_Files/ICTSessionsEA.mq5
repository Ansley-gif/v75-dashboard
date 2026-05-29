//+------------------------------------------------------------------+
//|                                                ICTSessionsEA.mq5  |
//|         ICT Session Open + Close Candle Breakout EA              |
//|                       V25 Trading Systems v1.0                   |
//|                                                                  |
//|  STRATEGY (Pattern 9 from PatternScanner on R_25):               |
//|     Mark FIRST 5-min candle of each ICT session (OC) AND first   |
//|     5-min candle after each session ends (CC).  Each candle's    |
//|     H and L become a breakout level valid for 24 hours.          |
//|                                                                  |
//|     ICT Session times (UTC):                                     |
//|        Asia   : 22:00 → 09:00 (overnight)                        |
//|        London : 07:00 → 16:00                                    |
//|        NY     : 13:00 → 22:00                                    |
//|                                                                  |
//|     ENTRY  : M5 close above an H or below an L  (fresh-armed)    |
//|     SL     : Fixed 2000 ticks (V25 M5 noise eats SL<2000)        |
//|     TP     : Fixed 6000 ticks  (1:3 R:R — break-even WR only 25%)|
//|     FILTER : 13:00 UTC ONLY (verified 4/4 windows cross-stable)  |
//|                                                                  |
//|  ARMED/UNARMED STATE MACHINE (the key safety):                   |
//|     A level can only fire when ARMED. Once it fires it becomes   |
//|     UNARMED.  It re-arms ONLY when price closes back through     |
//|     the level on the OPPOSITE side (back inside the box).        |
//|     This prevents stale-level chains (e.g. price stays below a   |
//|     LO level all night → only fires ONCE, not on every bar).    |
//|                                                                  |
//|  BACKTEST RESULT — broker-realistic, 8 months (2025-09→2026-04): |
//|     Config       : SL=2000 ticks / TP=6000 ticks / 13:00 UTC     |
//|     Trades       : 338 (~42/month, ~1 per day)                   |
//|     Win rate     : 28.1%                                         |
//|     Avg R/win    : 3.00R   (1R = $1.00 at 0.5 lot)               |
//|     Expectancy   : +0.122R per trade                             |
//|     Stability    : 4 / 4 non-overlapping 2-month windows positive|
//|     Max DD       : $26 in 8 months (~26% of $100 account)        |
//|     Live haircut : Apply 0.6-0.8 retention → ~$22/yr realistic   |
//|                                                                  |
//|  See MODEL_FINDINGS_2026-05-26.md for the full diagnostic story. |
//+------------------------------------------------------------------+
#property copyright "V25 Trading Systems"
#property version   "1.00"
#property description "ICT Open/Close Candle Breakout with ARMED/UNARMED state — M5 only"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

CTrade        g_trade;
CPositionInfo g_pos;

//+------------------------------------------------------------------+
//  INPUTS — defaults set for Pattern-9 V25 strategy
//+------------------------------------------------------------------+

input group "═══ ICT SESSION TIMES (UTC) ═══"
input int InpAsianOpenH   = 22;    // Asia OPEN  (UTC) — overnight session
input int InpAsianCloseH  = 9;     // Asia CLOSE (UTC)
input int InpLondonOpenH  = 7;     // London OPEN  (UTC)
input int InpLondonCloseH = 16;    // London CLOSE (UTC)
input int InpNYOpenH      = 13;    // NY OPEN  (UTC)
input int InpNYCloseH     = 22;    // NY CLOSE (UTC)  — also = next Asia OPEN

input group "═══ WHICH CANDLES TO TRADE ═══"
input bool InpTradeAsianOC   = true;
input bool InpTradeAsianCC   = true;
input bool InpTradeLondonOC  = true;
input bool InpTradeLondonCC  = true;
input bool InpTradeNYOC      = true;
input bool InpTradeNYCC      = true;

input group "═══ TIME-OF-DAY FILTER (ON by default — 13:00 UTC verified 4/4 windows) ═══"
input bool   InpUseHourFilter = true;                         // 13:00 UTC = only hour with cross-window stability
input string InpHoursAllowed  = "13";                         // Comma-separated UTC hours. "13" = NY open ONLY

input group "═══ TRADE SETTINGS ═══"
input double InpLotSize           = 0.5;     // V25 broker min lot = 0.5
input int    InpMaxConcurrent     = 1;       // Max simultaneous positions
input int    InpLevelTTLHours     = 24;      // How long a level stays alive
input int    InpMinBufferTks      = 2;       // Min ticks past level to confirm break
input int    InpAttemptsPerLevel  = 1;       // Hard cap (state machine is the real control)
input long   InpMagic             = 25009;   // Distinct from other EAs

input group "═══ STOP LOSS ═══"
input int    InpSLMode        = 1;       // 0=level-candle extreme  1=FIXED ticks (Pattern-9)  2=tighter of both
input int    InpFixedSLTicks  = 2000;    // Fixed SL ticks (= 2.0 price units on V25) — wider for noise
input int    InpSLBufferTks   = 2;       // Extra ticks beyond SL

input group "═══ TAKE PROFIT ═══"
input int    InpTPTicks       = 6000;    // Fixed TP ticks (= 6.0 price units on V25) — $R:R = 3.0
input int    InpMinRMultiple  = 10;      // Skip if R:R < this/10  (10 = 1:1 minimum)

input group "═══ RISK / CIRCUIT BREAKER ═══"
input bool   InpUseDailyStop  = true;
input double InpDailyMaxLossR = 3.0;     // Stop trading after N R-losses in a day
input bool   InpFridayOff     = false;
input bool   InpUseTrailStop  = false;
input int    InpTrailStartTks = 300;
input int    InpTrailStepTks  = 100;

input group "═══ DEBUG ═══"
input bool   InpVerboseLog    = true;

//+------------------------------------------------------------------+
//  STATE
//+------------------------------------------------------------------+
struct Level {
   string   tag;
   double   price;
   double   opposite_extreme;
   bool     is_high;
   datetime created;
   datetime expires;
   int      session_id;
   int      kind;
   int      attempts;
   bool     armed;           // STATE: true = ready to fire; false = waiting for box re-entry
};

#define MAX_LEVELS 200
Level    g_levels[MAX_LEVELS];
int      g_n_levels = 0;

datetime g_last_bar = 0;
datetime g_day_start = 0;
double   g_day_pnl_r = 0.0;

// Per-position risk tracking — fixes day-R counter bug
// (actual SL distance is wider than InpFixedSLTicks because of broker stops_level)
struct PosRisk { ulong pos_id; double risk_money; };
#define MAX_RISK_TRACK 20
PosRisk  g_risk[MAX_RISK_TRACK];
int      g_n_risk = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   if(_Period != PERIOD_M5)
   { Alert("ICTSessionsEA: must be M5"); return INIT_FAILED; }

   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(50);
   g_trade.SetTypeFillingBySymbol(_Symbol);

   g_n_levels  = 0;
   g_day_pnl_r = 0;
   g_day_start = 0;

   long   stops_lvl  = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   long   freeze_lvl = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   double min_lot    = SymbolInfoDouble (_Symbol, SYMBOL_VOLUME_MIN);
   double max_lot    = SymbolInfoDouble (_Symbol, SYMBOL_VOLUME_MAX);
   double lot_step   = SymbolInfoDouble (_Symbol, SYMBOL_VOLUME_STEP);
   double tick_value = SymbolInfoDouble (_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size  = SymbolInfoDouble (_Symbol, SYMBOL_TRADE_TICK_SIZE);

   PrintFormat("═══════ ICTSessionsEA started (Pattern 9, V25) ═══════");
   PrintFormat("Symbol         : %s",            _Symbol);
   PrintFormat("Point          : %.5f",          _Point);
   PrintFormat("Stops level    : %d points",     (int)stops_lvl);
   PrintFormat("Freeze level   : %d points",     (int)freeze_lvl);
   PrintFormat("Min lot        : %.3f",          min_lot);
   PrintFormat("Max lot        : %.2f",          max_lot);
   PrintFormat("Lot step       : %.3f",          lot_step);
   PrintFormat("Tick value     : %.5f",          tick_value);
   PrintFormat("Tick size      : %.5f",          tick_size);
   PrintFormat("Account balance: %.2f %s",
               AccountInfoDouble(ACCOUNT_BALANCE),
               AccountInfoString(ACCOUNT_CURRENCY));
   PrintFormat("Configured lot : %.3f",          InpLotSize);
   PrintFormat("Sessions UTC   : Asia %02d→%02d  London %02d→%02d  NY %02d→%02d",
               InpAsianOpenH, InpAsianCloseH, InpLondonOpenH, InpLondonCloseH,
               InpNYOpenH, InpNYCloseH);
   PrintFormat("SL mode        : %d   SL ticks: %d   TP ticks: %d",
               InpSLMode, InpFixedSLTicks, InpTPTicks);
   PrintFormat("Hour filter    : %s   Min R-mult: %.1f   Daily stop: %.1fR",
               InpUseHourFilter ? "ON" : "OFF",
               InpMinRMultiple * 0.1, InpDailyMaxLossR);
   if(InpLotSize < min_lot)
      Alert("⚠  InpLotSize (", DoubleToString(InpLotSize, 3),
            ") is BELOW broker minimum (", DoubleToString(min_lot, 3), ")");
   PrintFormat("══════════════════════════════════════════════════════");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int r) { Print("ICTSessionsEA stopped."); }

//+------------------------------------------------------------------+
//  Per-position risk tracking helpers (for accurate day-R accounting)
//+------------------------------------------------------------------+
void StorePositionRisk(double risk_money)
{
   ulong entry_deal = g_trade.ResultDeal();
   if(!HistoryDealSelect(entry_deal)) return;
   ulong pos_id = (ulong)HistoryDealGetInteger(entry_deal, DEAL_POSITION_ID);

   // Ring buffer — oldest entry overwritten when full
   int slot = g_n_risk;
   if(slot >= MAX_RISK_TRACK)
   {
      for(int i = 0; i < MAX_RISK_TRACK - 1; i++) g_risk[i] = g_risk[i+1];
      slot = MAX_RISK_TRACK - 1;
   }
   else g_n_risk++;

   g_risk[slot].pos_id     = pos_id;
   g_risk[slot].risk_money = risk_money;
}

double LookupPositionRisk(ulong pos_id)
{
   for(int i = 0; i < g_n_risk; i++)
      if(g_risk[i].pos_id == pos_id) return g_risk[i].risk_money;
   return 0.0;
}

//+------------------------------------------------------------------+
void OnTick()
{
   datetime bar0 = iTime(_Symbol, _Period, 0);
   if(bar0 == g_last_bar) return;
   g_last_bar = bar0;

   ResetDailyIfNewDay();

   if(InpUseTrailStop) ManageTrails();

   MqlRates b[];
   if(CopyRates(_Symbol, _Period, 1, 1, b) < 1) return;

   RecordLevelsFromBar(b[0]);
   PruneExpired();

   if(!CanTradeNow(b[0])) return;
   if(CountOpenPositions() >= InpMaxConcurrent) return;

   CheckBreakouts(b[0]);
}

//+------------------------------------------------------------------+
//  Record OC / CC candle levels
//+------------------------------------------------------------------+
void RecordLevelsFromBar(const MqlRates &bar)
{
   MqlDateTime dt;
   TimeToStruct(bar.time, dt);
   if(dt.min != 0) return;

   datetime ttl = bar.time + (datetime)(InpLevelTTLHours * 3600);

   if(InpTradeAsianOC  && dt.hour == InpAsianOpenH)
      AddLevels(bar, "ASIA_OC", 1, 1, ttl);

   if(InpTradeAsianCC  && dt.hour == InpAsianCloseH)
      AddLevels(bar, "ASIA_CC", 1, 2, ttl);

   if(InpTradeLondonOC && dt.hour == InpLondonOpenH)
      AddLevels(bar, "LDN_OC",  2, 1, ttl);

   if(InpTradeLondonCC && dt.hour == InpLondonCloseH)
      AddLevels(bar, "LDN_CC",  2, 2, ttl);

   if(InpTradeNYOC     && dt.hour == InpNYOpenH)
      AddLevels(bar, "NY_OC",   3, 1, ttl);

   if(InpTradeNYCC     && dt.hour == InpNYCloseH)
      AddLevels(bar, "NY_CC",   3, 2, ttl);
}

void AddLevels(const MqlRates &bar, string tag, int sess, int kind, datetime ttl)
{
   AddLevel(tag + "_H", bar.high, bar.low,  true,  bar.time, ttl, sess, kind);
   AddLevel(tag + "_L", bar.low,  bar.high, false, bar.time, ttl, sess, kind);

   if(InpVerboseLog)
      PrintFormat("[LEVEL] %s  H=%.5f  L=%.5f  TTL=%s",
                  tag, bar.high, bar.low, TimeToString(ttl, TIME_MINUTES));
}

void AddLevel(string tag, double price, double opposite, bool is_high,
              datetime created, datetime expires, int sess, int kind)
{
   if(g_n_levels >= MAX_LEVELS) PruneExpired();
   if(g_n_levels >= MAX_LEVELS) { Print("Levels full"); return; }

   g_levels[g_n_levels].tag              = tag;
   g_levels[g_n_levels].price            = price;
   g_levels[g_n_levels].opposite_extreme = opposite;
   g_levels[g_n_levels].is_high          = is_high;
   g_levels[g_n_levels].created          = created;
   g_levels[g_n_levels].expires          = expires;
   g_levels[g_n_levels].session_id       = sess;
   g_levels[g_n_levels].kind             = kind;
   g_levels[g_n_levels].attempts         = 0;
   g_levels[g_n_levels].armed            = true;
   g_n_levels++;
}

void PruneExpired()
{
   datetime now = TimeCurrent();
   int w = 0;
   for(int r = 0; r < g_n_levels; r++)
   {
      if(g_levels[r].attempts >= InpAttemptsPerLevel) continue;
      if(g_levels[r].expires < now)                    continue;
      if(r != w) g_levels[w] = g_levels[r];
      w++;
   }
   g_n_levels = w;
}

//+------------------------------------------------------------------+
//  BREAKOUT CHECKING with ARMED/UNARMED state machine
//+------------------------------------------------------------------+
void CheckBreakouts(const MqlRates &bar)
{
   double tick   = _Point;
   double buffer = InpMinBufferTks * tick;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   long stops_level  = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   long freeze_level = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   double spread_pts = (ask - bid) / tick;
   double min_dist   = (MathMax(stops_level, freeze_level) + (long)MathCeil(spread_pts) + 10) * tick;

   for(int i = 0; i < g_n_levels; i++)
   {
      if(g_levels[i].attempts >= InpAttemptsPerLevel) continue;
      if(bar.time <= g_levels[i].created)             continue;

      // ── RE-ARM STATE MACHINE ──────────────────────────────────────
      if(!g_levels[i].armed)
      {
         bool reentry = false;
         if(g_levels[i].is_high)
            reentry = (bar.close < g_levels[i].price);   // back below HI = inside box
         else
            reentry = (bar.close > g_levels[i].price);   // back above LO = inside box

         if(reentry)
         {
            g_levels[i].armed = true;
            if(InpVerboseLog)
               PrintFormat("[RE-ARM] %s armed by close %.5f (level %.5f)",
                           g_levels[i].tag, bar.close, g_levels[i].price);
         }
         continue;
      }

      // BULLISH break of HI level
      if(g_levels[i].is_high && bar.close > g_levels[i].price + buffer)
      {
         double entry = ask;
         double sl_p  = ComputeSL(true, entry, g_levels[i].opposite_extreme);
         double tp_p  = entry + InpTPTicks * tick;

         if(bid - sl_p < min_dist) sl_p = bid - min_dist;
         if(tp_p - bid < min_dist) tp_p = bid + min_dist;

         sl_p = NormalizeDouble(sl_p, _Digits);
         tp_p = NormalizeDouble(tp_p, _Digits);

         if(IsValidRR(true, entry, sl_p, tp_p))
         {
            if(g_trade.Buy(InpLotSize, _Symbol, entry, sl_p, tp_p,
                           "ICT_BUY:" + g_levels[i].tag))
            {
               LogTrade("BUY", g_levels[i].tag, entry, sl_p, tp_p);
               double tick_val = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
               double tick_sz  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
               double risk_money = MathAbs(entry - sl_p) / tick_sz * tick_val * InpLotSize;
               StorePositionRisk(risk_money);
               g_levels[i].attempts++;
               g_levels[i].armed = false;
               return;
            }
            else
            {
               PrintFormat("BUY rejected: %s  retcode=%d  err=%d  bid=%.5f ask=%.5f sl=%.5f tp=%.5f min_dist=%.5f",
                           g_trade.ResultRetcodeDescription(),
                           g_trade.ResultRetcode(), GetLastError(),
                           bid, ask, sl_p, tp_p, min_dist);
            }
         }
         else if(InpVerboseLog)
         {
            PrintFormat("[SKIP] %s BUY signal — R:R %.2f below %.2f minimum",
                        g_levels[i].tag,
                        (tp_p - entry) / (entry - sl_p),
                        InpMinRMultiple * 0.1);
         }
      }

      // BEARISH break of LO level
      if(!g_levels[i].is_high && bar.close < g_levels[i].price - buffer)
      {
         double entry = bid;
         double sl_p  = ComputeSL(false, entry, g_levels[i].opposite_extreme);
         double tp_p  = entry - InpTPTicks * tick;

         if(sl_p - ask < min_dist) sl_p = ask + min_dist;
         if(ask - tp_p < min_dist) tp_p = ask - min_dist;

         sl_p = NormalizeDouble(sl_p, _Digits);
         tp_p = NormalizeDouble(tp_p, _Digits);

         if(IsValidRR(false, entry, sl_p, tp_p))
         {
            if(g_trade.Sell(InpLotSize, _Symbol, entry, sl_p, tp_p,
                            "ICT_SELL:" + g_levels[i].tag))
            {
               LogTrade("SELL", g_levels[i].tag, entry, sl_p, tp_p);
               double tick_val = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
               double tick_sz  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
               double risk_money = MathAbs(sl_p - entry) / tick_sz * tick_val * InpLotSize;
               StorePositionRisk(risk_money);
               g_levels[i].attempts++;
               g_levels[i].armed = false;
               return;
            }
            else
            {
               PrintFormat("SELL rejected: %s  retcode=%d  err=%d  bid=%.5f ask=%.5f sl=%.5f tp=%.5f min_dist=%.5f",
                           g_trade.ResultRetcodeDescription(),
                           g_trade.ResultRetcode(), GetLastError(),
                           bid, ask, sl_p, tp_p, min_dist);
            }
         }
         else if(InpVerboseLog)
         {
            PrintFormat("[SKIP] %s SELL signal — R:R %.2f below %.2f minimum",
                        g_levels[i].tag,
                        (entry - tp_p) / (sl_p - entry),
                        InpMinRMultiple * 0.1);
         }
      }
   }
}

//+------------------------------------------------------------------+
//  STOP LOSS COMPUTATION
//
//  Mode 1 (Pattern-9 default):  SL = entry ± InpFixedSLTicks ticks
//  Mode 0:  SL = opposite extreme of the level-defining candle (ICT)
//  Mode 2:  Tighter (closer to entry) of Mode 0 and Mode 1
//+------------------------------------------------------------------+
double ComputeSL(bool is_buy, double entry, double level_opposite)
{
   double tick      = _Point;
   double buffer    = InpSLBufferTks * tick;
   double level_sl  = is_buy ? level_opposite - buffer : level_opposite + buffer;
   double fixed_sl  = is_buy ? entry - InpFixedSLTicks * tick
                             : entry + InpFixedSLTicks * tick;

   if(InpSLMode == 1) return fixed_sl;
   if(InpSLMode == 2)
      return is_buy ? MathMax(level_sl, fixed_sl)
                    : MathMin(level_sl, fixed_sl);
   return level_sl;
}

bool IsValidRR(bool is_buy, double entry, double sl, double tp)
{
   double risk   = is_buy ? entry - sl : sl - entry;
   double reward = is_buy ? tp - entry : entry - tp;
   if(risk <= 0 || reward <= 0) return false;
   return (reward / risk) >= (InpMinRMultiple * 0.1);
}

//+------------------------------------------------------------------+
//  FILTERS
//+------------------------------------------------------------------+
bool CanTradeNow(const MqlRates &bar)
{
   MqlDateTime dt;
   TimeToStruct(bar.time, dt);

   if(InpFridayOff && dt.day_of_week == 5) return false;

   if(InpUseDailyStop && g_day_pnl_r <= -InpDailyMaxLossR)
   {
      if(InpVerboseLog) Print("Daily loss limit reached — skipping.");
      return false;
   }

   if(InpUseHourFilter)
   {
      string hours_str = InpHoursAllowed;
      string parts[];
      int n = StringSplit(hours_str, ',', parts);
      bool ok = false;
      for(int i = 0; i < n; i++)
         if((int)StringToInteger(parts[i]) == dt.hour) { ok = true; break; }
      if(!ok)
      {
         if(InpVerboseLog) PrintFormat("[SKIP] hour filter blocked at %02d:00", dt.hour);
         return false;
      }
   }
   return true;
}

void ResetDailyIfNewDay()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   datetime today = StructToTime(dt) - dt.hour*3600 - dt.min*60 - dt.sec;
   if(today != g_day_start)
   {
      g_day_start = today;
      g_day_pnl_r = 0.0;
   }
}

//+------------------------------------------------------------------+
//  POSITION MANAGEMENT
//+------------------------------------------------------------------+
int CountOpenPositions()
{
   int c = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(g_pos.SelectByIndex(i) &&
         g_pos.Magic()  == InpMagic &&
         g_pos.Symbol() == _Symbol) c++;
   return c;
}

void ManageTrails()
{
   double tick   = _Point;
   double start  = InpTrailStartTks * tick;
   double step   = InpTrailStepTks  * tick;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!g_pos.SelectByIndex(i)) continue;
      if(g_pos.Magic()  != InpMagic) continue;
      if(g_pos.Symbol() != _Symbol)  continue;

      double op = g_pos.PriceOpen();
      double cp = g_pos.PriceCurrent();
      double sl = g_pos.StopLoss();
      ulong  tk = g_pos.Ticket();

      if(g_pos.PositionType() == POSITION_TYPE_BUY)
      {
         if(cp - op < start) continue;
         double new_sl = NormalizeDouble(cp - step, _Digits);
         if(new_sl > sl + tick) g_trade.PositionModify(tk, new_sl, g_pos.TakeProfit());
      }
      else
      {
         if(op - cp < start) continue;
         double new_sl = NormalizeDouble(cp + step, _Digits);
         if(sl == 0 || new_sl < sl - tick) g_trade.PositionModify(tk, new_sl, g_pos.TakeProfit());
      }
   }
}

//+------------------------------------------------------------------+
//  TRADE TRANSACTION HOOK — track daily P&L in R-units
//+------------------------------------------------------------------+
void OnTradeTransaction(const MqlTradeTransaction &trans,
                        const MqlTradeRequest     &req,
                        const MqlTradeResult      &res)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD) return;

   ulong deal = trans.deal;
   if(!HistoryDealSelect(deal)) return;

   long magic = HistoryDealGetInteger(deal, DEAL_MAGIC);
   if(magic != InpMagic) return;

   long entry = HistoryDealGetInteger(deal, DEAL_ENTRY);
   if(entry != DEAL_ENTRY_OUT) return;

   double profit = HistoryDealGetDouble(deal, DEAL_PROFIT);

   // Use the position's ACTUAL risk recorded at entry time (broker may have
   // widened SL past InpFixedSLTicks via stops_level + spread, so the old
   // computation under-counted real R losses by 40%+).
   ulong pos_id = (ulong)HistoryDealGetInteger(deal, DEAL_POSITION_ID);
   double risk_money = LookupPositionRisk(pos_id);

   // Fallback to the old fixed-SL approximation if we somehow don't have a
   // stored value (e.g. position opened before EA restart).
   if(risk_money <= 0)
      risk_money = InpFixedSLTicks *
                   SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE) *
                   InpLotSize;

   if(risk_money > 0) g_day_pnl_r += profit / risk_money;

   if(InpVerboseLog)
      PrintFormat("[EXIT] profit=%.2f  risk=%.4f  day_R=%+.2f",
                  profit, risk_money, g_day_pnl_r);
}

//+------------------------------------------------------------------+
//  LOGGING
//+------------------------------------------------------------------+
void LogTrade(string dir, string tag, double e, double s, double t)
{
   if(!InpVerboseLog) return;
   double risk   = MathAbs(e - s);
   double reward = MathAbs(t - e);
   PrintFormat(">> %s %s @%.5f  SL=%.5f (%.0f tk)  TP=%.5f (%.0f tk)  R:R=1:%.2f",
               dir, tag, e, s, risk/_Point, t, reward/_Point, reward/risk);
}
//+------------------------------------------------------------------+
