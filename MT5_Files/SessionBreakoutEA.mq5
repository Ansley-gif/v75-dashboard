//+------------------------------------------------------------------+
//|                                          SessionBreakoutEA.mq5    |
//|              ICT Session Breakout Expert Advisor                   |
//|                      V75 Trading Systems v1.0                      |
//|                                                                    |
//|  Logic:                                                            |
//|   1. Track session H/L for Asian / London / New York               |
//|   2. When price breaks a session level → enter trade               |
//|   3. SL = nearest swing H/L  OR  breakout candle extreme           |
//|   4. TP = next liquidity level (swing H/L / FVG / OB)              |
//|         OR fixed tick target (50-100 ticks)                        |
//|   5. Designed for M5, Deriv Volatility indices on MT5              |
//+------------------------------------------------------------------+
#property copyright "V75 Trading Systems"
#property version   "1.00"
#property description "ICT Session Breakout EA — M5 · Deriv Synthetics"

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\OrderInfo.mqh>

CTrade         g_trade;
CPositionInfo  g_pos;

//+------------------------------------------------------------------+
//  INPUTS
//+------------------------------------------------------------------+

input group "══════════ SESSION TIMES  (Server UTC) ══════════"
input int    InpAsianH1       =  0;   // Asian Open  Hour
input int    InpAsianH2       =  8;   // Asian Close Hour
input int    InpLondonH1      =  8;   // London Open  Hour
input int    InpLondonH2      = 17;   // London Close Hour
input int    InpNYH1          = 13;   // New York Open  Hour
input int    InpNYH2          = 22;   // New York Close Hour

input group "══════════ SESSION FILTER ══════════"
input bool   InpTradeAsian    = true;   // Trade Asian session breakouts
input bool   InpTradeLondon   = true;   // Trade London session breakouts
input bool   InpTradeNY       = true;   // Trade New York session breakouts
input int    InpMinSessBars   = 12;     // Min M5 bars before session level is tradeable
input double InpMinBreakTicks = 3;      // Min ticks above/below level to confirm break

input group "══════════ TRADE SETTINGS ══════════"
input double InpLotSize       = 0.10;  // Lot size
input int    InpMaxTrades     = 1;     // Max concurrent positions (per magic)
input long   InpMagic         = 202401; // Magic number

input group "══════════ STOP LOSS ══════════"
input int    InpSLMode        = 0;     // 0=Nearest swing  1=Breakout candle extreme
input int    InpSwingLookback = 20;    // Bars to look back for swing SL
input double InpSLBuffer      = 5;    // Extra ticks beyond SL level

input group "══════════ TAKE PROFIT ══════════"
input int    InpTPMode        = 0;     // 0=Next liquidity  1=Fixed ticks
input int    InpTPTicks       = 75;    // Fixed TP in ticks (mode 1)
input int    InpMinTPTicks    = 50;    // Minimum TP distance in ticks
input int    InpLiqLookback   = 100;   // Bars to scan for next liquidity (mode 0)

input group "══════════ RISK MANAGEMENT ══════════"
input bool   InpUseTrailStop  = false;  // Enable trailing stop
input int    InpTrailStart    = 30;    // Ticks of profit before trail activates
input int    InpTrailStep     = 10;    // Trail step in ticks
input bool   InpCloseEOD      = true;  // Close all trades before end of day (23:00)

//+------------------------------------------------------------------+
//  SESSION STATE
//+------------------------------------------------------------------+
struct SessState
{
   datetime t_sess_start; // start of current session instance
   double   hi;           // running session high
   double   lo;           // running session low
   double   open_hi;      // first-bar high (opening candle level)
   double   open_lo;      // first-bar low  (opening candle level)
   int      bar_count;    // bars seen in this session instance
   bool     formed;       // enough bars to trade
   bool     hi_traded;    // already took a high-break trade
   bool     lo_traded;    // already took a low-break trade
};

SessState g_asian, g_london, g_ny;
datetime  g_last_bar_time = 0;
double    g_tick;          // cached _Point value

//+------------------------------------------------------------------+
int OnInit()
{
   if(_Period != PERIOD_M5)
   {
      Alert("SessionBreakoutEA: Please attach to an M5 chart.");
      return INIT_FAILED;
   }

   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(50);
   g_trade.SetTypeFilling(ORDER_FILLING_IOC);
   g_tick = _Point;

   ResetAllSessions();
   Print("SessionBreakoutEA started — Symbol: ", _Symbol,
         "  Point: ", g_tick);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   Print("SessionBreakoutEA stopped.");
}

//+------------------------------------------------------------------+
void OnTick()
{
   // ── Work once per closed M5 bar ───────────────────────────────
   datetime bar0 = iTime(_Symbol, _Period, 0);
   if(bar0 == g_last_bar_time) return;
   g_last_bar_time = bar0;

   // ── End-of-day close ──────────────────────────────────────────
   if(InpCloseEOD)
   {
      MqlDateTime now;
      TimeToStruct(TimeCurrent(), now);
      if(now.hour == 23 && now.min >= 45)
      {
         CloseAll();
         return;
      }
   }

   // ── Get the just-closed bar (bar index 1) ─────────────────────
   MqlRates bars[];
   if(CopyRates(_Symbol, _Period, 1, 1, bars) < 1) return;
   MqlRates &b = bars[0];

   MqlDateTime mdt;
   TimeToStruct(b.time, mdt);
   int hour = mdt.hour;

   // ── Update each session ───────────────────────────────────────
   UpdateSession(g_asian,  hour, InpAsianH1,  InpAsianH2,  b);
   UpdateSession(g_london, hour, InpLondonH1, InpLondonH2, b);
   UpdateSession(g_ny,     hour, InpNYH1,     InpNYH2,     b);

   // ── Trailing stop management ──────────────────────────────────
   if(InpUseTrailStop) ManageTrails();

   // ── Breakout checks ───────────────────────────────────────────
   if(CountOpenTrades() >= InpMaxTrades) return;

   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   if(InpTradeAsian  && g_asian.formed)  CheckBreakout(g_asian,  ask, bid, b);
   if(InpTradeLondon && g_london.formed) CheckBreakout(g_london, ask, bid, b);
   if(InpTradeNY     && g_ny.formed)     CheckBreakout(g_ny,     ask, bid, b);
}

//+------------------------------------------------------------------+
//  SESSION UPDATE
//+------------------------------------------------------------------+
void UpdateSession(SessState &s, int cur_hour, int h1, int h2,
                   const MqlRates &bar)
{
   bool in_sess = (cur_hour >= h1 && cur_hour < h2);

   if(!in_sess)
   {
      // Outside the session window — keep H/L intact for post-session trading
      // but do NOT update bar count
      return;
   }

   // Determine the canonical start of this session on this day
   MqlDateTime mdt;
   TimeToStruct(bar.time, mdt);
   mdt.hour = h1; mdt.min = 0; mdt.sec = 0;
   datetime sess_id = StructToTime(mdt);

   // New session instance?
   if(sess_id != s.t_sess_start)
   {
      s.t_sess_start = sess_id;
      s.hi           = bar.high;
      s.lo           = bar.low;
      s.open_hi      = bar.high;
      s.open_lo      = bar.low;
      s.bar_count    = 1;
      s.formed       = false;
      s.hi_traded    = false;
      s.lo_traded    = false;
      return;
   }

   // Existing session: update H/L
   if(bar.high > s.hi) s.hi = bar.high;
   if(bar.low  < s.lo) s.lo = bar.low;
   s.bar_count++;
   if(s.bar_count >= InpMinSessBars) s.formed = true;
}

//+------------------------------------------------------------------+
//  BREAKOUT CHECK
//+------------------------------------------------------------------+
void CheckBreakout(SessState &s, double ask, double bid, const MqlRates &brk_bar)
{
   double min_break = InpMinBreakTicks * g_tick;

   // ── Bullish breakout: ask closes above session high ──────────
   if(!s.hi_traded && ask > s.hi + min_break)
   {
      double sl = CalcSL(true,  brk_bar, s.lo);
      double tp = CalcTP(true,  ask, s.hi);

      if(sl > 0 && tp > 0 && (tp - ask) >= InpMinTPTicks * g_tick)
      {
         if(g_trade.Buy(InpLotSize, _Symbol, ask, sl, tp,
                        "ICT SessBreak BUY"))
         {
            PrintTrade("BUY", ask, sl, tp, s.bar_count);
            s.hi_traded = true;
         }
      }
   }

   // ── Bearish breakout: bid closes below session low ────────────
   if(!s.lo_traded && bid < s.lo - min_break)
   {
      double sl = CalcSL(false, brk_bar, s.hi);
      double tp = CalcTP(false, bid, s.lo);

      if(sl > 0 && tp > 0 && (bid - tp) >= InpMinTPTicks * g_tick)
      {
         if(g_trade.Sell(InpLotSize, _Symbol, bid, sl, tp,
                         "ICT SessBreak SELL"))
         {
            PrintTrade("SELL", bid, sl, tp, s.bar_count);
            s.lo_traded = true;
         }
      }
   }
}

//+------------------------------------------------------------------+
//  STOP LOSS CALCULATION
//+------------------------------------------------------------------+
double CalcSL(bool is_buy, const MqlRates &brk_bar, double sess_opposite)
{
   double buf = InpSLBuffer * g_tick;

   if(InpSLMode == 1)
   {
      // SL at the breakout candle's opposite extreme
      return is_buy ? brk_bar.low  - buf
                    : brk_bar.high + buf;
   }

   // Mode 0: SL at nearest swing high/low within lookback
   if(is_buy)
   {
      double swing_lo = FindSwingLow(InpSwingLookback);
      if(swing_lo <= 0) swing_lo = sess_opposite;
      return swing_lo - buf;
   }
   else
   {
      double swing_hi = FindSwingHigh(InpSwingLookback);
      if(swing_hi <= 0) swing_hi = sess_opposite;
      return swing_hi + buf;
   }
}

//+------------------------------------------------------------------+
//  TAKE PROFIT CALCULATION
//+------------------------------------------------------------------+
double CalcTP(bool is_buy, double entry_price, double sess_level)
{
   if(InpTPMode == 1)
   {
      // Fixed tick TP
      double tp = is_buy ? entry_price + InpTPTicks * g_tick
                         : entry_price - InpTPTicks * g_tick;
      return NormalizeDouble(tp, _Digits);
   }

   // Mode 0: next liquidity — nearest swing H (for buys) or L (for sells)
   if(is_buy)
   {
      double res = FindNextSwingHigh(entry_price, InpLiqLookback);
      if(res <= 0 || res < entry_price + InpMinTPTicks * g_tick)
         res = entry_price + InpTPTicks * g_tick;
      return NormalizeDouble(res, _Digits);
   }
   else
   {
      double sup = FindNextSwingLow(entry_price, InpLiqLookback);
      if(sup <= 0 || sup > entry_price - InpMinTPTicks * g_tick)
         sup = entry_price - InpTPTicks * g_tick;
      return NormalizeDouble(sup, _Digits);
   }
}

//+------------------------------------------------------------------+
//  LIQUIDITY / SWING HELPERS
//+------------------------------------------------------------------+

// Lowest low in the last N closed bars (for SL on buys)
double FindSwingLow(int bars)
{
   double lo_array[];
   if(CopyLow(_Symbol, _Period, 1, bars, lo_array) <= 0) return 0;
   double lowest = lo_array[0];
   for(int i = 1; i < ArraySize(lo_array); i++)
      if(lo_array[i] < lowest) lowest = lo_array[i];
   return lowest;
}

// Highest high in the last N closed bars (for SL on sells)
double FindSwingHigh(int bars)
{
   double hi_array[];
   if(CopyHigh(_Symbol, _Period, 1, bars, hi_array) <= 0) return 0;
   double highest = hi_array[0];
   for(int i = 1; i < ArraySize(hi_array); i++)
      if(hi_array[i] > highest) highest = hi_array[i];
   return highest;
}

// Nearest swing HIGH above entry_price (resistance / TP for buys)
double FindNextSwingHigh(double above, int bars)
{
   int n = 3; // swing detection half-width
   double hi[], lo[];
   datetime t[];

   int copied = (int)CopyHigh(_Symbol, _Period, 1, bars, hi);
   if(copied <= 2*n) return 0;

   // Iterate from most recent back; arrays are oldest-first from CopyHigh
   double nearest = 0;
   for(int i = n; i < copied - n; i++)
   {
      bool is_sh = true;
      for(int j = 1; j <= n && is_sh; j++)
         if(hi[i-j] >= hi[i] || hi[i+j] >= hi[i]) is_sh = false;

      if(is_sh && hi[i] > above)
      {
         if(nearest == 0 || hi[i] < nearest) nearest = hi[i];
      }
   }
   return nearest;
}

// Nearest swing LOW below entry_price (support / TP for sells)
double FindNextSwingLow(double below, int bars)
{
   int n = 3;
   double lo[];

   int copied = (int)CopyLow(_Symbol, _Period, 1, bars, lo);
   if(copied <= 2*n) return 0;

   double nearest = 0;
   for(int i = n; i < copied - n; i++)
   {
      bool is_sl = true;
      for(int j = 1; j <= n && is_sl; j++)
         if(lo[i-j] <= lo[i] || lo[i+j] <= lo[i]) is_sl = false;

      if(is_sl && lo[i] < below)
      {
         if(nearest == 0 || lo[i] > nearest) nearest = lo[i];
      }
   }
   return nearest;
}

//+------------------------------------------------------------------+
//  TRAILING STOP
//+------------------------------------------------------------------+
void ManageTrails()
{
   double trail_start = InpTrailStart * g_tick;
   double trail_step  = InpTrailStep  * g_tick;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!g_pos.SelectByIndex(i)) continue;
      if(g_pos.Magic()  != InpMagic) continue;
      if(g_pos.Symbol() != _Symbol)  continue;

      double cur_sl    = g_pos.StopLoss();
      double open_p    = g_pos.PriceOpen();
      double cur_price = g_pos.PriceCurrent();
      ulong  ticket    = g_pos.Ticket();

      if(g_pos.PositionType() == POSITION_TYPE_BUY)
      {
         double profit_dist = cur_price - open_p;
         if(profit_dist < trail_start) continue;

         double new_sl = NormalizeDouble(cur_price - trail_step, _Digits);
         if(new_sl > cur_sl + g_tick)
            g_trade.PositionModify(ticket, new_sl, g_pos.TakeProfit());
      }
      else // SELL
      {
         double profit_dist = open_p - cur_price;
         if(profit_dist < trail_start) continue;

         double new_sl = NormalizeDouble(cur_price + trail_step, _Digits);
         if(new_sl < cur_sl - g_tick || cur_sl == 0)
            g_trade.PositionModify(ticket, new_sl, g_pos.TakeProfit());
      }
   }
}

//+------------------------------------------------------------------+
//  POSITION UTILITIES
//+------------------------------------------------------------------+
int CountOpenTrades()
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(g_pos.SelectByIndex(i) &&
         g_pos.Magic()  == InpMagic &&
         g_pos.Symbol() == _Symbol)
         count++;
   }
   return count;
}

void CloseAll()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!g_pos.SelectByIndex(i)) continue;
      if(g_pos.Magic()  != InpMagic) continue;
      if(g_pos.Symbol() != _Symbol)  continue;
      g_trade.PositionClose(g_pos.Ticket());
   }
}

void ResetAllSessions()
{
   ZeroMemory(g_asian);
   ZeroMemory(g_london);
   ZeroMemory(g_ny);
}

void PrintTrade(string dir, double price, double sl, double tp, int sess_bars)
{
   PrintFormat(">> %s  price=%.5f  SL=%.5f  TP=%.5f  sess_bars=%d",
               dir, price, sl, tp, sess_bars);
}
//+------------------------------------------------------------------+
