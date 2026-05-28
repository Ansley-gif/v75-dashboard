//+------------------------------------------------------------------+
//|                                              SessionLevels.mq5    |
//|              ICT Session Levels & Market Structure Indicator       |
//|                      V75 Trading Systems v1.0                      |
//|                                                                    |
//|  Marks on chart:                                                   |
//|   - Asian / London / New York session boxes & H/L levels          |
//|   - Fair Value Gaps (FVG) — bullish & bearish                     |
//|   - Order Blocks (OB)    — bullish & bearish                      |
//|   - Swing Highs / Swing Lows                                       |
//|   - Breaker Blocks (broken OBs that flip)                         |
//|   - Voids (large impulsive body moves)                             |
//|                                                                    |
//|  Designed for M5 timeframe on Deriv synthetic indices (V75, V10…) |
//+------------------------------------------------------------------+
#property copyright   "V75 Trading Systems"
#property version     "1.00"
#property indicator_chart_window
#property indicator_buffers 0
#property indicator_plots   0
#property description "ICT Session H/L · FVG · OB · Swings · Breakers · Voids — M5 only"

//--- Session Time Inputs (UTC / Server Time)
input group "══════════ SESSION TIMES  (Server UTC) ══════════"
input int   InpAsianH1    =  0;   // Asian Open  Hour
input int   InpAsianH2    =  8;   // Asian Close Hour
input int   InpLondonH1   =  8;   // London Open  Hour
input int   InpLondonH2   = 17;   // London Close Hour
input int   InpNYH1       = 13;   // New York Open  Hour
input int   InpNYH2       = 22;   // New York Close Hour

input group "══════════ SESSION APPEARANCE ══════════"
input bool  InpShowBox    = true;            // Draw session box
input bool  InpShowHL     = true;            // Draw session H/L lines
input bool  InpExtendHL   = true;            // Extend H/L lines to the right
input color InpAsianClr   = C'20,90,160';   // Asian colour
input color InpLondonClr  = C'20,130,40';   // London colour
input color InpNYClr      = C'160,80,0';    // New York colour
input bool  InpShowLabels = true;            // Show session labels

input group "══════════ FAIR VALUE GAPS ══════════"
input bool  InpShowFVG    = true;
input int   InpFVGBars    = 300;            // Bars to scan for FVGs
input color InpFVGBullClr = C'0,60,0';     // Bullish FVG colour
input color InpFVGBearClr = C'70,0,0';     // Bearish FVG colour

input group "══════════ ORDER BLOCKS ══════════"
input bool  InpShowOB     = true;
input int   InpOBBars     = 200;            // Bars to scan for OBs
input int   InpOBMinMove  = 3;             // Min follow-through bars for OB
input color InpOBBullClr  = C'0,0,110';    // Bullish OB colour
input color InpOBBearClr  = C'110,0,0';    // Bearish OB colour

input group "══════════ SWING POINTS ══════════"
input bool  InpShowSwing  = true;
input int   InpSwingN     = 5;             // Bars each side for swing detection
input color InpSHClr      = clrCrimson;    // Swing High colour
input color InpSLClr      = clrLimeGreen;  // Swing Low colour

input group "══════════ BREAKER BLOCKS ══════════"
input bool  InpShowBrk    = true;
input color InpBrkBullClr = C'0,140,140';  // Bullish Breaker (broken bear OB)
input color InpBrkBearClr = C'140,0,140';  // Bearish Breaker (broken bull OB)

input group "══════════ VOIDS ══════════"
input bool   InpShowVoid  = true;
input double InpVoidATR   = 1.8;           // Min candle body (×ATR) to flag void
input color  InpVoidClr   = C'100,75,0';  // Void outline colour

input group "══════════ GENERAL ══════════"
input int   InpDays       = 10;            // Days of history to display

//--- Globals
string g_pfx    = "ICT_";  // all chart objects start with this prefix
int    g_atr_h  = INVALID_HANDLE;
datetime g_from;

//+------------------------------------------------------------------+
int OnInit()
{
   if(_Period != PERIOD_M5)
   {
      Alert("SessionLevels: Please apply this indicator on an M5 chart.");
      return INIT_FAILED;
   }

   g_from  = TimeCurrent() - (datetime)(InpDays * 86400);
   g_atr_h = iATR(_Symbol, _Period, 14);
   if(g_atr_h == INVALID_HANDLE) return INIT_FAILED;

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   ObjectsDeleteAll(0, g_pfx);
   if(g_atr_h != INVALID_HANDLE) IndicatorRelease(g_atr_h);
}

//+------------------------------------------------------------------+
int OnCalculate(const int       rates_total,
                const int       prev_calculated,
                const datetime &time[],
                const double   &open[],
                const double   &high[],
                const double   &low[],
                const double   &close[],
                const long     &tick_volume[],
                const long     &volume[],
                const int      &spread[])
{
   if(rates_total < 50) return 0;

   // Only redraw when a new bar has closed
   if(prev_calculated == rates_total) return rates_total;

   // Pull ATR values
   double atr[];
   if(CopyBuffer(g_atr_h, 0, 0, rates_total, atr) <= 0) return prev_calculated;

   // Find index of oldest bar we care about
   int idx0 = 0;
   for(int i = 0; i < rates_total; i++)
   {
      if(time[i] >= g_from) { idx0 = i; break; }
   }
   if(idx0 == 0 && time[0] < g_from) idx0 = 0; // fallback: use all bars

   // Clear and redraw everything
   ObjectsDeleteAll(0, g_pfx);

   if(InpShowBox || InpShowHL)
      DrawSessions(time, high, low, rates_total, idx0);

   if(InpShowFVG)
      DrawFVGs(time, open, high, low, close, rates_total, idx0);

   if(InpShowOB)
      DrawOBs(time, open, high, low, close, rates_total, idx0);

   if(InpShowSwing)
      DrawSwings(time, high, low, rates_total, idx0);

   if(InpShowBrk)
      DrawBreakers(time, open, high, low, close, rates_total, idx0);

   if(InpShowVoid)
      DrawVoids(time, open, high, low, close, atr, rates_total, idx0);

   ChartRedraw();
   return rates_total;
}

//+------------------------------------------------------------------+
//  Utilities
//+------------------------------------------------------------------+

// Returns session type for a given hour: 0=none 1=Asian 2=London 3=NY
int SessType(int h)
{
   if(h >= InpNYH1    && h < InpNYH2)    return 3;
   if(h >= InpLondonH1 && h < InpLondonH2) return 2;
   if(h >= InpAsianH1  && h < InpAsianH2)  return 1;
   return 0;
}

color SessColor(int t)
{
   if(t == 1) return InpAsianClr;
   if(t == 2) return InpLondonClr;
   return InpNYClr;
}

string SessLabel(int t)
{
   if(t == 1) return "ASIAN";
   if(t == 2) return "LONDON";
   return "NY";
}

// Create a rectangle object (background, filled, non-selectable)
void MakeRect(const string name, datetime t1, double p1, datetime t2, double p2,
              color clr, bool filled, ENUM_LINE_STYLE style = STYLE_SOLID, int width = 1)
{
   if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
   ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, p1, t2, p2);
   ObjectSetInteger(0, name, OBJPROP_COLOR,      clr);
   ObjectSetInteger(0, name, OBJPROP_FILL,       filled);
   ObjectSetInteger(0, name, OBJPROP_STYLE,      style);
   ObjectSetInteger(0, name, OBJPROP_WIDTH,      width);
   ObjectSetInteger(0, name, OBJPROP_BACK,       true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN,     true);
}

// Create a trend line (non-selectable, optionally horizontal)
void MakeLine(const string name, datetime t1, double p1, datetime t2, double p2,
              color clr, ENUM_LINE_STYLE style = STYLE_DASH, int width = 1)
{
   if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
   ObjectCreate(0, name, OBJ_TREND, 0, t1, p1, t2, p2);
   ObjectSetInteger(0, name, OBJPROP_COLOR,      clr);
   ObjectSetInteger(0, name, OBJPROP_STYLE,      style);
   ObjectSetInteger(0, name, OBJPROP_WIDTH,      width);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT,  false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN,     true);
}

// Create a text label
void MakeText(const string name, datetime t, double p, const string txt,
              color clr, int fontsize = 7)
{
   if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
   ObjectCreate(0, name, OBJ_TEXT, 0, t, p);
   ObjectSetString(0,  name, OBJPROP_TEXT,      txt);
   ObjectSetInteger(0, name, OBJPROP_COLOR,     clr);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE,  fontsize);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE,false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN,    true);
}

// Create an arrow object
void MakeArrow(const string name, datetime t, double p, int code, color clr, int width = 2)
{
   if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
   ObjectCreate(0, name, OBJ_ARROW, 0, t, p);
   ObjectSetInteger(0, name, OBJPROP_ARROWCODE,  code);
   ObjectSetInteger(0, name, OBJPROP_COLOR,      clr);
   ObjectSetInteger(0, name, OBJPROP_WIDTH,      width);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN,     true);
}

//+------------------------------------------------------------------+
//  SESSION BOXES & H/L LINES
//+------------------------------------------------------------------+
void DrawSessions(const datetime &time[],
                  const double   &high[],
                  const double   &low[],
                  int total, int idx0)
{
   // We collect session instances then draw them all
   struct SInst {
      datetime t_open;   // first bar time
      datetime t_close;  // last bar time + 300s
      double   hi;
      double   lo;
      int      sess_type;
      int      uid;      // unique key: year*100000 + doy*10 + type
   };

   SInst arr[];
   int   n      = 0;
   int   cur_uid = -1;

   for(int i = idx0; i < total; i++)
   {
      MqlDateTime mdt;
      TimeToStruct(time[i], mdt);
      int st  = SessType(mdt.hour);
      if(st == 0) { cur_uid = -1; continue; }

      int uid = mdt.year * 100000 + mdt.day_of_year * 10 + st;

      if(uid != cur_uid)
      {
         ArrayResize(arr, n + 1);
         arr[n].t_open   = time[i];
         arr[n].t_close  = time[i] + 300;
         arr[n].hi       = high[i];
         arr[n].lo       = low[i];
         arr[n].sess_type = st;
         arr[n].uid      = uid;
         n++;
         cur_uid = uid;
      }
      else
      {
         arr[n-1].t_close = time[i] + 300;
         if(high[i] > arr[n-1].hi) arr[n-1].hi = high[i];
         if(low[i]  < arr[n-1].lo) arr[n-1].lo = low[i];
      }
   }

   datetime now_ext = time[total-1] + 7200; // extend lines 2h past last bar

   for(int s = 0; s < n; s++)
   {
      string sid  = IntegerToString(arr[s].uid);
      color  clr  = SessColor(arr[s].sess_type);
      string lbl  = SessLabel(arr[s].sess_type);

      // Session shaded box
      if(InpShowBox)
         MakeRect(g_pfx+"BOX_"+sid, arr[s].t_open, arr[s].hi,
                                    arr[s].t_close, arr[s].lo, clr, true);

      // Session H/L lines
      if(InpShowHL)
      {
         datetime ext = InpExtendHL ? now_ext : arr[s].t_close;

         MakeLine(g_pfx+"SH_"+sid,
                  arr[s].t_open, arr[s].hi, ext, arr[s].hi, clr, STYLE_DASH, 1);
         MakeLine(g_pfx+"SL_"+sid,
                  arr[s].t_open, arr[s].lo, ext, arr[s].lo, clr, STYLE_DASH, 1);

         // Session open candle H/L (first bar of session — key ICT level)
         MakeLine(g_pfx+"SOH_"+sid,
                  arr[s].t_open, high[idx0], ext, high[idx0], clr, STYLE_DOT, 1);

         if(InpShowLabels)
         {
            MakeText(g_pfx+"TH_"+sid, arr[s].t_open, arr[s].hi,
                     lbl+" H", clr, 7);
            MakeText(g_pfx+"TL_"+sid, arr[s].t_open, arr[s].lo,
                     lbl+" L", clr, 7);
         }
      }
   }
}

//+------------------------------------------------------------------+
//  FAIR VALUE GAPS
//+------------------------------------------------------------------+
// Bullish FVG : three-candle pattern where candle[i-1].high < candle[i+1].low
//               The gap between them is bullish inefficiency
// Bearish FVG : candle[i-1].low > candle[i+1].high
//               The gap is bearish inefficiency
//+------------------------------------------------------------------+
void DrawFVGs(const datetime &time[],
              const double   &open[],
              const double   &high[],
              const double   &low[],
              const double   &close[],
              int total, int idx0)
{
   int scan_start = MathMax(idx0, total - InpFVGBars);

   for(int i = scan_start + 1; i < total - 1; i++)
   {
      // Bullish FVG
      if(high[i-1] < low[i+1])
      {
         string nm = g_pfx + "BFVG_" + IntegerToString(i);
         MakeRect(nm, time[i-1], low[i+1], time[i+1]+300, high[i-1],
                  InpFVGBullClr, true);
         if(InpShowLabels)
            MakeText(g_pfx+"BFVGT_"+IntegerToString(i),
                     time[i], high[i-1], "FVG", InpFVGBullClr, 6);
      }

      // Bearish FVG
      if(low[i-1] > high[i+1])
      {
         string nm = g_pfx + "SFVG_" + IntegerToString(i);
         MakeRect(nm, time[i-1], low[i-1], time[i+1]+300, high[i+1],
                  InpFVGBearClr, true);
         if(InpShowLabels)
            MakeText(g_pfx+"SFVGT_"+IntegerToString(i),
                     time[i], low[i-1], "FVG", InpFVGBearClr, 6);
      }
   }
}

//+------------------------------------------------------------------+
//  ORDER BLOCKS
//+------------------------------------------------------------------+
// Bullish OB : last bearish candle before N consecutive bullish candles
// Bearish OB : last bullish candle before N consecutive bearish candles
//+------------------------------------------------------------------+
void DrawOBs(const datetime &time[],
             const double   &open[],
             const double   &high[],
             const double   &low[],
             const double   &close[],
             int total, int idx0)
{
   int scan_start = MathMax(idx0, total - InpOBBars);
   int ext_bars   = 30; // how many bars to extend the OB zone to the right

   for(int i = scan_start; i < total - InpOBMinMove - 1; i++)
   {
      bool is_bear = (close[i] < open[i]);
      bool is_bull = (close[i] > open[i]);

      // Potential Bullish OB: bearish candle followed by bullish impulse
      if(is_bear)
      {
         int bull_cnt = 0;
         for(int j = i+1; j <= i+InpOBMinMove && j < total; j++)
            if(close[j] > open[j]) bull_cnt++;

         if(bull_cnt >= InpOBMinMove)
         {
            double ob_hi = open[i];   // top of bearish candle body
            double ob_lo = close[i];  // bottom of bearish candle body
            datetime t_end = time[MathMin(i + ext_bars, total-1)] + 300;

            string nm = g_pfx + "BOB_" + IntegerToString(i);
            MakeRect(nm, time[i], ob_hi, t_end, ob_lo, InpOBBullClr, true);
            if(InpShowLabels)
               MakeText(g_pfx+"BOBT_"+IntegerToString(i),
                        time[i], ob_hi, "OB", InpOBBullClr, 6);
         }
      }

      // Potential Bearish OB: bullish candle followed by bearish impulse
      if(is_bull)
      {
         int bear_cnt = 0;
         for(int j = i+1; j <= i+InpOBMinMove && j < total; j++)
            if(close[j] < open[j]) bear_cnt++;

         if(bear_cnt >= InpOBMinMove)
         {
            double ob_hi = close[i];  // top of bullish candle body
            double ob_lo = open[i];   // bottom of bullish candle body
            datetime t_end = time[MathMin(i + ext_bars, total-1)] + 300;

            string nm = g_pfx + "SOB_" + IntegerToString(i);
            MakeRect(nm, time[i], ob_hi, t_end, ob_lo, InpOBBearClr, true);
            if(InpShowLabels)
               MakeText(g_pfx+"SOBT_"+IntegerToString(i),
                        time[i], ob_hi, "OB", InpOBBearClr, 6);
         }
      }
   }
}

//+------------------------------------------------------------------+
//  SWING HIGHS / LOWS
//+------------------------------------------------------------------+
void DrawSwings(const datetime &time[],
                const double   &high[],
                const double   &low[],
                int total, int idx0)
{
   int n = InpSwingN;

   for(int i = MathMax(idx0, n); i < total - n; i++)
   {
      // Swing High: highest point among 2n+1 bars centred on i
      bool is_sh = true;
      for(int j = 1; j <= n && is_sh; j++)
         if(high[i-j] >= high[i] || high[i+j] >= high[i]) is_sh = false;

      if(is_sh)
         MakeArrow(g_pfx+"SWH_"+IntegerToString(i),
                   time[i], high[i] + _Point * 20,
                   218, InpSHClr, 2); // ▼ arrow above high

      // Swing Low
      bool is_sl = true;
      for(int j = 1; j <= n && is_sl; j++)
         if(low[i-j] <= low[i] || low[i+j] <= low[i]) is_sl = false;

      if(is_sl)
         MakeArrow(g_pfx+"SWL_"+IntegerToString(i),
                   time[i], low[i] - _Point * 20,
                   217, InpSLClr, 2); // ▲ arrow below low
   }
}

//+------------------------------------------------------------------+
//  BREAKER BLOCKS
//+------------------------------------------------------------------+
// A Bullish OB whose low is subsequently broken → becomes Bearish Breaker
// A Bearish OB whose high is subsequently broken → becomes Bullish Breaker
//+------------------------------------------------------------------+
void DrawBreakers(const datetime &time[],
                  const double   &open[],
                  const double   &high[],
                  const double   &low[],
                  const double   &close[],
                  int total, int idx0)
{
   int scan_start = MathMax(idx0, total - InpOBBars);
   int ext_bars   = 25;

   for(int i = scan_start; i < total - InpOBMinMove - 2; i++)
   {
      // --- Check for Bullish OB that was broken (→ Bearish Breaker) ---
      if(close[i] < open[i]) // bearish candle
      {
         int bull_cnt = 0;
         for(int j = i+1; j <= i+InpOBMinMove && j < total; j++)
            if(close[j] > open[j]) bull_cnt++;

         if(bull_cnt >= InpOBMinMove)
         {
            double ob_lo = close[i]; // OB low
            // Check if subsequent price broke below ob_lo
            int break_bar = -1;
            for(int j = i + InpOBMinMove + 1; j < total; j++)
            {
               if(close[j] < ob_lo) { break_bar = j; break; }
            }

            if(break_bar > 0)
            {
               // Draw as Bearish Breaker (dashed outline)
               string nm = g_pfx + "BRKB_" + IntegerToString(i);
               datetime t_end = time[MathMin(break_bar + ext_bars, total-1)] + 300;
               MakeRect(nm, time[i], open[i], t_end, ob_lo,
                        InpBrkBearClr, false, STYLE_DASH, 1);
               if(InpShowLabels)
                  MakeText(g_pfx+"BRKBT_"+IntegerToString(i),
                           time[break_bar], open[i], "BRK", InpBrkBearClr, 6);
            }
         }
      }

      // --- Check for Bearish OB that was broken (→ Bullish Breaker) ---
      if(close[i] > open[i]) // bullish candle
      {
         int bear_cnt = 0;
         for(int j = i+1; j <= i+InpOBMinMove && j < total; j++)
            if(close[j] < open[j]) bear_cnt++;

         if(bear_cnt >= InpOBMinMove)
         {
            double ob_hi = close[i]; // OB high
            int break_bar = -1;
            for(int j = i + InpOBMinMove + 1; j < total; j++)
            {
               if(close[j] > ob_hi) { break_bar = j; break; }
            }

            if(break_bar > 0)
            {
               string nm = g_pfx + "BRKBU_" + IntegerToString(i);
               datetime t_end = time[MathMin(break_bar + ext_bars, total-1)] + 300;
               MakeRect(nm, time[i], ob_hi, t_end, open[i],
                        InpBrkBullClr, false, STYLE_DASH, 1);
               if(InpShowLabels)
                  MakeText(g_pfx+"BRKBUT_"+IntegerToString(i),
                           time[break_bar], open[i], "BRK", InpBrkBullClr, 6);
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//  VOIDS
//+------------------------------------------------------------------+
// A void is a large single-candle body move (> InpVoidATR × ATR14).
// Price often returns to fill these zones.  Drawn as dashed outline.
//+------------------------------------------------------------------+
void DrawVoids(const datetime &time[],
               const double   &open[],
               const double   &high[],
               const double   &low[],
               const double   &close[],
               const double   &atr[],
               int total, int idx0)
{
   int ext_bars = 40;

   for(int i = idx0; i < total - 1; i++)
   {
      double body = MathAbs(close[i] - open[i]);
      double atr_v = (i < (int)ArraySize(atr)) ? atr[i] : 0;
      if(atr_v <= 0) continue;

      if(body >= InpVoidATR * atr_v)
      {
         double top = MathMax(open[i], close[i]);
         double bot = MathMin(open[i], close[i]);
         datetime t_end = time[MathMin(i + ext_bars, total-1)] + 300;

         string nm = g_pfx + "VOID_" + IntegerToString(i);
         MakeRect(nm, time[i], top, t_end, bot,
                  InpVoidClr, false, STYLE_DOT, 1);
         if(InpShowLabels)
            MakeText(g_pfx+"VOIDT_"+IntegerToString(i),
                     time[i], top, "VOID", InpVoidClr, 6);
      }
   }
}
//+------------------------------------------------------------------+
