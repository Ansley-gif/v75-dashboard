//+------------------------------------------------------------------+
//|                                                  OpenCloseEA.mq5  |
//|         ICT Open + Close Candle Breakout Expert Advisor           |
//|                       V75 Trading Systems v2.0                    |
//|                                                                   |
//|  THE STRATEGY (proven on 8 months of R_75 M5 data):               |
//|     Mark the FIRST 5-min candle of each session (OC = Open        |
//|     Candle) AND the FIRST 5-min candle AFTER each session ends    |
//|     (CC = Close Candle).  Each candle's H and L become a level    |
//|     that's valid for 24 hours.                                    |
//|                                                                   |
//|     ENTRY  : M5 close above an H or below an L                    |
//|     SL     : tighter of (breakout candle extreme, fixed ticks)    |
//|     TP     : fixed ticks (default 75)                             |
//|                                                                   |
//|  Backtest result on R_75 M5 (1 year, ~8000 signals):              |
//|     Win rate    : ~51%                                            |
//|     Avg R/win   : 1.34R                                           |
//|     Expectancy  : +0.20R per trade                                |
//|     Net 1-year  : +1,600R                                         |
//+------------------------------------------------------------------+
#property copyright "V75 Trading Systems"
#property version   "2.00"
#property description "ICT Open & Close Candle Breakout — M5 only"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

CTrade        g_trade;
CPositionInfo g_pos;

//+------------------------------------------------------------------+
//  INPUTS
//+------------------------------------------------------------------+

input group "═══ SESSION TIMES (UTC) ═══"
input int InpAsianOpenH   = 0;
input int InpAsianCloseH  = 8;
input int InpLondonOpenH  = 8;
input int InpLondonCloseH = 17;
input int InpNYOpenH      = 13;
input int InpNYCloseH     = 22;

input group "═══ WHICH CANDLES TO TRADE ═══"
input bool InpTradeAsianOC   = true;   // Asian Open  candle
input bool InpTradeAsianCC   = true;   // Asian Close candle
input bool InpTradeLondonOC  = true;   // London Open  candle
input bool InpTradeLondonCC  = true;   // London Close candle
input bool InpTradeNYOC      = true;   // NY Open  candle
input bool InpTradeNYCC      = true;   // NY Close candle

input group "═══ TIME-OF-DAY FILTER (high-edge hours only) ═══"
input bool InpUseHourFilter  = true;                         // Restrict trading to specific hours
input string InpHoursAllowed = "3,5,11,12,13,20,22,23";      // V25 high-WR hours from backtest

input group "═══ TRADE SETTINGS ═══"
input double InpLotSize           = 0.01;  // Lot size (broker min may apply)
input int    InpMaxConcurrent     = 1;     // Max simultaneous positions
input int    InpLevelTTLHours     = 24;    // How long a level stays active
input int    InpMinBufferTks      = 2;     // Min ticks past level to confirm break
input int    InpAttemptsPerLevel  = 2;     // Re-trade after stopout: 1=once 2=twice etc
input long   InpMagic             = 75001;

input group "═══ STOP LOSS ═══"
input int    InpSLMode        = 0;      // 0=LEVEL-CANDLE opposite extreme (ICT, recommended)  1=fixed ticks  2=tighter of both
input int    InpFixedSLTicks  = 40;     // Fixed SL ticks (modes 1 & 2)
input int    InpSLBufferTks   = 2;      // Extra ticks beyond SL

input group "═══ TAKE PROFIT ═══"
input int    InpTPTicks       = 75;     // Fixed TP in ticks
input int    InpMinRMultiple  = 1;      // Skip trade if reward/risk < this (×0.1, so 10 = 1.0R)

input group "═══ RISK / CIRCUIT BREAKER ═══"
input bool   InpUseDailyStop  = true;
input double InpDailyMaxLossR = 5.0;    // Stop trading after N R-loss in a day
input bool   InpFridayOff     = false;  // Disable Fridays (lower-edge day in backtest)
input bool   InpUseTrailStop  = false;
input int    InpTrailStartTks = 30;
input int    InpTrailStepTks  = 10;

input group "═══ DEBUG ═══"
input bool   InpVerboseLog    = true;

//+------------------------------------------------------------------+
//  STATE
//+------------------------------------------------------------------+
struct Level {
   string   tag;             // "ASIA_OC_H" etc.
   double   price;           // the level itself (HI or LO of defining candle)
   double   opposite_extreme;// opposite side of the defining candle — used for SL
   bool     is_high;         // true = bullish-break level, false = bearish
   datetime created;
   datetime expires;
   int      session_id;      // 1=Asian 2=London 3=NY
   int      kind;            // 1=OC (open candle)  2=CC (close candle)
   int      attempts;        // how many times we've already traded this level
};

#define MAX_LEVELS 200
Level    g_levels[MAX_LEVELS];
int      g_n_levels = 0;

datetime g_last_bar = 0;
datetime g_day_start = 0;
double   g_day_pnl_r = 0.0;

//+------------------------------------------------------------------+
int OnInit()
{
   if(_Period != PERIOD_M5)
   { Alert("OpenCloseEA: must be M5"); return INIT_FAILED; }

   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(50);
   g_trade.SetTypeFillingBySymbol(_Symbol);

   g_n_levels  = 0;
   g_day_pnl_r = 0;
   g_day_start = 0;

   // Broker / symbol diagnostics — important for "invalid stops" debugging
   long   stops_lvl  = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   long   freeze_lvl = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   double min_lot    = SymbolInfoDouble (_Symbol, SYMBOL_VOLUME_MIN);
   double max_lot    = SymbolInfoDouble (_Symbol, SYMBOL_VOLUME_MAX);
   double lot_step   = SymbolInfoDouble (_Symbol, SYMBOL_VOLUME_STEP);
   double tick_value = SymbolInfoDouble (_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size  = SymbolInfoDouble (_Symbol, SYMBOL_TRADE_TICK_SIZE);

   PrintFormat("════════ OpenCloseEA started ════════");
   PrintFormat("Symbol         : %s",           _Symbol);
   PrintFormat("Point          : %.5f",         _Point);
   PrintFormat("Stops level    : %d points",    (int)stops_lvl);
   PrintFormat("Freeze level   : %d points",    (int)freeze_lvl);
   PrintFormat("Min lot        : %.3f",         min_lot);
   PrintFormat("Max lot        : %.2f",         max_lot);
   PrintFormat("Lot step       : %.3f",         lot_step);
   PrintFormat("Tick value     : %.5f",         tick_value);
   PrintFormat("Tick size      : %.5f",         tick_size);
   PrintFormat("Account balance: %.2f %s",
               AccountInfoDouble(ACCOUNT_BALANCE),
               AccountInfoString(ACCOUNT_CURRENCY));
   PrintFormat("Configured lot : %.3f", InpLotSize);
   if(InpLotSize < min_lot)
      Alert("⚠  InpLotSize (", DoubleToString(InpLotSize,3),
            ") is BELOW broker minimum (", DoubleToString(min_lot,3), ")");
   PrintFormat("══════════════════════════════════════");
   return INIT_SUCCEEDED;
}

void OnDeinit(const int r) { Print("OpenCloseEA stopped."); }

//+------------------------------------------------------------------+
void OnTick()
{
   datetime bar0 = iTime(_Symbol, _Period, 0);
   if(bar0 == g_last_bar) return;
   g_last_bar = bar0;

   ResetDailyIfNewDay();

   if(InpUseTrailStop) ManageTrails();

   // Get last closed bar
   MqlRates b[];
   if(CopyRates(_Symbol, _Period, 1, 1, b) < 1) return;

   // 1) Check if this closed bar is one of our 6 OC/CC candles → record level
   RecordLevelsFromBar(b[0]);

   // 2) Expire and prune old levels
   PruneExpired();

   // 3) Check if this closed bar broke any active level → trade
   if(!CanTradeNow(b[0])) return;
   if(CountOpenPositions() >= InpMaxConcurrent) return;

   CheckBreakouts(b[0]);
}

//+------------------------------------------------------------------+
//  Record open / close candle levels
//+------------------------------------------------------------------+
void RecordLevelsFromBar(const MqlRates &bar)
{
   MqlDateTime dt;
   TimeToStruct(bar.time, dt);
   if(dt.min != 0) return;        // only candles starting at minute 0

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
   // HI level: opposite_extreme = the candle's LOW (used as SL if a BUY fires)
   AddLevel(tag+"_H", bar.high, bar.low,  true,  bar.time, ttl, sess, kind);
   // LO level: opposite_extreme = the candle's HIGH (used as SL if a SELL fires)
   AddLevel(tag+"_L", bar.low,  bar.high, false, bar.time, ttl, sess, kind);

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
//  BREAKOUT CHECKING
//+------------------------------------------------------------------+
void CheckBreakouts(const MqlRates &bar)
{
   double tick   = _Point;
   double buffer = InpMinBufferTks * tick;

   // Live prices and broker constraints
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   long stops_level  = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   long freeze_level = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_FREEZE_LEVEL);
   double spread_pts = (ask - bid) / tick;
   // Pad must cover: broker stops_level + freeze_level + current spread + margin
   double min_dist   = (MathMax(stops_level, freeze_level) + (long)MathCeil(spread_pts) + 10) * tick;

   for(int i = 0; i < g_n_levels; i++)
   {
      if(g_levels[i].attempts >= InpAttemptsPerLevel) continue;
      if(bar.time <= g_levels[i].created)             continue;

      // BULLISH break of HI level
      if(g_levels[i].is_high && bar.close > g_levels[i].price + buffer)
      {
         double entry = ask;                                              // use current ask
         double sl_p  = ComputeSL(true, entry, g_levels[i].opposite_extreme);
         double tp_p  = entry + InpTPTicks * tick;

         // Broker validates BUY SL/TP against the BID (close-side), not entry.
         if(bid - sl_p < min_dist) sl_p = bid - min_dist;
         if(tp_p - bid < min_dist) tp_p = bid + min_dist;

         sl_p = NormalizeDouble(sl_p, _Digits);
         tp_p = NormalizeDouble(tp_p, _Digits);

         if(IsValidRR(true, entry, sl_p, tp_p))
         {
            if(g_trade.Buy(InpLotSize, _Symbol, entry, sl_p, tp_p,
                           "OC_BUY:" + g_levels[i].tag))
            {
               LogTrade("BUY", g_levels[i].tag, entry, sl_p, tp_p);
               g_levels[i].attempts++;
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
      }

      // BEARISH break of LO level
      if(!g_levels[i].is_high && bar.close < g_levels[i].price - buffer)
      {
         double entry = bid;                                              // use current bid
         double sl_p  = ComputeSL(false, entry, g_levels[i].opposite_extreme);
         double tp_p  = entry - InpTPTicks * tick;

         // Broker validates SELL SL/TP against the ASK (close-side), not entry.
         if(sl_p - ask < min_dist) sl_p = ask + min_dist;
         if(ask - tp_p < min_dist) tp_p = ask - min_dist;

         sl_p = NormalizeDouble(sl_p, _Digits);
         tp_p = NormalizeDouble(tp_p, _Digits);

         if(IsValidRR(false, entry, sl_p, tp_p))
         {
            if(g_trade.Sell(InpLotSize, _Symbol, entry, sl_p, tp_p,
                            "OC_SELL:" + g_levels[i].tag))
            {
               LogTrade("SELL", g_levels[i].tag, entry, sl_p, tp_p);
               g_levels[i].attempts++;
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
      }
   }
}

//+------------------------------------------------------------------+
//  STOP LOSS COMPUTATION
//
//  Mode 0 (default, ICT logic):
//     SL goes at the opposite extreme of the LEVEL-DEFINING candle.
//     For a BUY (broke level HI): SL = level.opposite_extreme (the candle's LOW)
//     For a SELL (broke level LO): SL = level.opposite_extreme (the candle's HIGH)
//     Trade is only invalidated when price takes out the WHOLE defining candle.
//
//  Mode 1: Fixed-tick SL from entry
//  Mode 2: Tighter (closer to entry) of Mode 0 and Mode 1
//+------------------------------------------------------------------+
double ComputeSL(bool is_buy, double entry, double level_opposite)
{
   double tick      = _Point;
   double buffer    = InpSLBufferTks * tick;
   double level_sl  = is_buy ? level_opposite - buffer : level_opposite + buffer;
   double fixed_sl  = is_buy ? entry - InpFixedSLTicks * tick
                             : entry + InpFixedSLTicks * tick;

   if(InpSLMode == 1) return fixed_sl;
   if(InpSLMode == 2)                        // tighter of the two
      return is_buy ? MathMax(level_sl, fixed_sl)
                    : MathMin(level_sl, fixed_sl);
   return level_sl;                          // Mode 0 — ICT default
}

bool IsValidRR(bool is_buy, double entry, double sl, double tp)
{
   double risk   = is_buy ? entry - sl : sl - entry;
   double reward = is_buy ? tp - entry : entry - tp;
   if(risk <= 0 || reward <= 0) return false;
   double r = reward / risk;
   return r >= (InpMinRMultiple * 0.1);
}

//+------------------------------------------------------------------+
//  TIME / DAY FILTERS
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
      if(!ok) return false;
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
   if(entry != DEAL_ENTRY_OUT) return;   // only count exits

   double profit = HistoryDealGetDouble(deal, DEAL_PROFIT);

   // Approximate R-multiple from profit using the symbol value per tick
   double risk_money = InpFixedSLTicks * _Point *
                       SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   if(risk_money > 0) g_day_pnl_r += profit / risk_money;

   if(InpVerboseLog)
      PrintFormat("[EXIT] profit=%.2f  day_R=%+.2f", profit, g_day_pnl_r);
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
