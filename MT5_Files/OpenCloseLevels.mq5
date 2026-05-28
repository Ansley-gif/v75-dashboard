//+------------------------------------------------------------------+
//|                                            OpenCloseLevels.mq5    |
//|         ICT Open + Close Candle Breakout Levels Indicator         |
//|                       V75 Trading Systems v2.0                    |
//|                                                                   |
//|  Marks the SIX key candles per day on M5:                         |
//|     ASIAN  Open    : 00:00-00:05 UTC                              |
//|     ASIAN  Close   : 08:00-08:05 UTC  (= LONDON Open)             |
//|     LONDON Open    : 08:00-08:05 UTC                              |
//|     LONDON Close   : 17:00-17:05 UTC                              |
//|     NY     Open    : 13:00-13:05 UTC                              |
//|     NY     Close   : 22:00-22:05 UTC                              |
//|                                                                   |
//|  Each candle's HIGH and LOW become breakout levels that extend    |
//|  forward for the next 24 hours.  When price closes above the H    |
//|  or below the L of any of these levels → tradeable breakout.      |
//|                                                                   |
//|  Also marks: FVGs, Order Blocks, Swing H/L, Breakers, Voids       |
//+------------------------------------------------------------------+
#property copyright "V75 Trading Systems"
#property version   "2.00"
#property indicator_chart_window
#property indicator_buffers 0
#property indicator_plots   0
#property description "Open & Close Candle Breakout Levels — M5 only"

//=== Session times (UTC) ===
input group "═══ SESSION TIMES (Server UTC) ═══"
input int InpAsianOpenH   = 0;    // Asian Open Hour
input int InpAsianCloseH  = 8;    // Asian Close Hour
input int InpLondonOpenH  = 8;    // London Open Hour
input int InpLondonCloseH = 17;   // London Close Hour
input int InpNYOpenH      = 13;   // NY Open Hour
input int InpNYCloseH     = 22;   // NY Close Hour

//=== Display options ===
input group "═══ WHAT TO SHOW ═══"
input bool InpShowAsianOpen   = true;
input bool InpShowAsianClose  = true;
input bool InpShowLondonOpen  = true;
input bool InpShowLondonClose = true;
input bool InpShowNYOpen      = true;
input bool InpShowNYClose     = true;

input group "═══ COLOURS ═══"
input color InpAsianOpenClr   = C'80,160,255';   // Asian OPEN level
input color InpAsianCloseClr  = C'40,100,180';   // Asian CLOSE level
input color InpLondonOpenClr  = C'80,200,80';    // London OPEN level
input color InpLondonCloseClr = C'40,140,40';    // London CLOSE level
input color InpNYOpenClr      = C'255,160,40';   // NY OPEN level
input color InpNYCloseClr     = C'200,100,0';    // NY CLOSE level

input group "═══ LINE STYLE ═══"
input int            InpLineWidth      = 1;
input ENUM_LINE_STYLE InpOpenStyle     = STYLE_SOLID;   // OPEN candle line style
input ENUM_LINE_STYLE InpCloseStyle    = STYLE_DASH;    // CLOSE candle line style
input bool           InpHighlightCandle = true;          // Box around the actual candle
input int            InpExtendHours    = 24;             // Hours to extend lines

input group "═══ LABELS ═══"
input bool InpShowLabels    = true;
input int  InpLabelFontSize = 7;

input group "═══ EXTRAS ═══"
input bool   InpShowFVG       = true;     // Fair Value Gaps
input bool   InpShowOB        = true;     // Order Blocks
input bool   InpShowSwing     = true;     // Swing Highs/Lows
input bool   InpShowBreaker   = true;     // Breaker Blocks
input bool   InpShowVoid      = true;     // Voids (large candles)
input int    InpExtraLookback = 200;      // Bars to scan for FVG/OB/etc.
input int    InpSwingN        = 5;        // Bars each side for swing
input double InpVoidATR       = 1.8;      // Min body × ATR to flag void
input color  InpFVGBullClr    = C'0,80,0';
input color  InpFVGBearClr    = C'90,0,0';
input color  InpOBBullClr     = C'0,0,140';
input color  InpOBBearClr     = C'140,0,0';
input color  InpSwingHClr     = clrCrimson;
input color  InpSwingLClr     = clrLime;
input color  InpBreakerClr    = C'150,80,150';
input color  InpVoidClr       = C'160,140,0';

input group "═══ GENERAL ═══"
input int InpHistoryDays = 10;            // Days of history to draw

//--- Globals
string   g_pfx   = "OCL_";
int      g_atrH  = INVALID_HANDLE;
datetime g_from;

//+------------------------------------------------------------------+
int OnInit()
{
   if(_Period != PERIOD_M5)
   { Alert("OpenCloseLevels: must be applied on an M5 chart"); return INIT_FAILED; }

   g_from = TimeCurrent() - (datetime)(InpHistoryDays * 86400);
   g_atrH = iATR(_Symbol, _Period, 14);
   if(g_atrH == INVALID_HANDLE) return INIT_FAILED;
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   ObjectsDeleteAll(0, g_pfx);
   if(g_atrH != INVALID_HANDLE) IndicatorRelease(g_atrH);
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
   if(prev_calculated == rates_total) return rates_total;

   double atr[];
   if(CopyBuffer(g_atrH, 0, 0, rates_total, atr) <= 0) return prev_calculated;

   int idx0 = 0;
   for(int i = 0; i < rates_total; i++)
      if(time[i] >= g_from) { idx0 = i; break; }

   ObjectsDeleteAll(0, g_pfx);

   DrawOCLevels(time, high, low, rates_total, idx0);

   if(InpShowFVG)     DrawFVGs(time, open, high, low, close, rates_total, idx0);
   if(InpShowOB)      DrawOBs (time, open, high, low, close, rates_total, idx0);
   if(InpShowSwing)   DrawSwings(time, high, low, rates_total, idx0);
   if(InpShowBreaker) DrawBreakers(time, open, high, low, close, rates_total, idx0);
   if(InpShowVoid)    DrawVoids(time, open, high, low, close, atr, rates_total, idx0);

   ChartRedraw();
   return rates_total;
}

//+------------------------------------------------------------------+
//  OBJECT HELPERS
//+------------------------------------------------------------------+
void MakeRect(string nm, datetime t1, double p1, datetime t2, double p2,
              color clr, bool fill, ENUM_LINE_STYLE st = STYLE_SOLID, int w = 1)
{
   if(ObjectFind(0, nm) >= 0) ObjectDelete(0, nm);
   ObjectCreate(0, nm, OBJ_RECTANGLE, 0, t1, p1, t2, p2);
   ObjectSetInteger(0, nm, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, nm, OBJPROP_FILL,  fill);
   ObjectSetInteger(0, nm, OBJPROP_STYLE, st);
   ObjectSetInteger(0, nm, OBJPROP_WIDTH, w);
   ObjectSetInteger(0, nm, OBJPROP_BACK,  true);
   ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, nm, OBJPROP_HIDDEN, true);
}

void MakeLine(string nm, datetime t1, double p1, datetime t2, double p2,
              color clr, ENUM_LINE_STYLE st, int w)
{
   if(ObjectFind(0, nm) >= 0) ObjectDelete(0, nm);
   ObjectCreate(0, nm, OBJ_TREND, 0, t1, p1, t2, p2);
   ObjectSetInteger(0, nm, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, nm, OBJPROP_STYLE, st);
   ObjectSetInteger(0, nm, OBJPROP_WIDTH, w);
   ObjectSetInteger(0, nm, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, nm, OBJPROP_HIDDEN, true);
}

void MakeText(string nm, datetime t, double p, string txt, color clr, int sz = 7)
{
   if(ObjectFind(0, nm) >= 0) ObjectDelete(0, nm);
   ObjectCreate(0, nm, OBJ_TEXT, 0, t, p);
   ObjectSetString(0,  nm, OBJPROP_TEXT, txt);
   ObjectSetInteger(0, nm, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, nm, OBJPROP_FONTSIZE, sz);
   ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, nm, OBJPROP_HIDDEN, true);
}

void MakeArrow(string nm, datetime t, double p, int code, color clr, int w = 2)
{
   if(ObjectFind(0, nm) >= 0) ObjectDelete(0, nm);
   ObjectCreate(0, nm, OBJ_ARROW, 0, t, p);
   ObjectSetInteger(0, nm, OBJPROP_ARROWCODE, code);
   ObjectSetInteger(0, nm, OBJPROP_COLOR, clr);
   ObjectSetInteger(0, nm, OBJPROP_WIDTH, w);
   ObjectSetInteger(0, nm, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, nm, OBJPROP_HIDDEN, true);
}

//+------------------------------------------------------------------+
//  CORE — DRAW THE 6 OC CANDLES PER DAY
//+------------------------------------------------------------------+
struct OCDef {
   int    hour;       // hour the candle starts
   string label;      // displayed label
   bool   show;       // user toggle
   color  clr;        // colour
   ENUM_LINE_STYLE style;
};

void DrawOCLevels(const datetime &time[],
                  const double   &high[],
                  const double   &low[],
                  int total, int idx0)
{
   OCDef defs[6];
   defs[0].hour = InpAsianOpenH;   defs[0].label = "ASIA OC";   defs[0].show = InpShowAsianOpen;   defs[0].clr = InpAsianOpenClr;   defs[0].style = InpOpenStyle;
   defs[1].hour = InpAsianCloseH;  defs[1].label = "ASIA CC";   defs[1].show = InpShowAsianClose;  defs[1].clr = InpAsianCloseClr;  defs[1].style = InpCloseStyle;
   defs[2].hour = InpLondonOpenH;  defs[2].label = "LDN  OC";   defs[2].show = InpShowLondonOpen;  defs[2].clr = InpLondonOpenClr;  defs[2].style = InpOpenStyle;
   defs[3].hour = InpLondonCloseH; defs[3].label = "LDN  CC";   defs[3].show = InpShowLondonClose; defs[3].clr = InpLondonCloseClr; defs[3].style = InpCloseStyle;
   defs[4].hour = InpNYOpenH;      defs[4].label = "NY   OC";   defs[4].show = InpShowNYOpen;      defs[4].clr = InpNYOpenClr;      defs[4].style = InpOpenStyle;
   defs[5].hour = InpNYCloseH;     defs[5].label = "NY   CC";   defs[5].show = InpShowNYClose;     defs[5].clr = InpNYCloseClr;     defs[5].style = InpCloseStyle;

   long extend_secs = (long)InpExtendHours * 3600;

   for(int i = idx0; i < total; i++)
   {
      MqlDateTime mdt;
      TimeToStruct(time[i], mdt);
      if(mdt.min != 0) continue;        // only candles starting at minute 0

      for(int k = 0; k < 6; k++)
      {
         if(!defs[k].show) continue;
         if(mdt.hour != defs[k].hour) continue;

         string sid   = IntegerToString(time[i]) + "_" + IntegerToString(k);
         color  clr   = defs[k].clr;
         ENUM_LINE_STYLE st = defs[k].style;
         double hi    = high[i];
         double lo    = low[i];
         datetime end = time[i] + (datetime)extend_secs;

         // Highlight the actual candle
         if(InpHighlightCandle)
         {
            string bn = g_pfx + "BOX_" + sid;
            MakeRect(bn, time[i], hi, time[i] + 300, lo, clr, false, STYLE_SOLID, 2);
         }

         // High line
         string nh = g_pfx + "H_" + sid;
         MakeLine(nh, time[i], hi, end, hi, clr, st, InpLineWidth);

         // Low line
         string nl = g_pfx + "L_" + sid;
         MakeLine(nl, time[i], lo, end, lo, clr, st, InpLineWidth);

         // Labels
         if(InpShowLabels)
         {
            MakeText(g_pfx+"TH_"+sid, time[i], hi, defs[k].label+" H", clr, InpLabelFontSize);
            MakeText(g_pfx+"TL_"+sid, time[i], lo, defs[k].label+" L", clr, InpLabelFontSize);
         }
      }
   }
}

//+------------------------------------------------------------------+
//  FAIR VALUE GAPS
//+------------------------------------------------------------------+
void DrawFVGs(const datetime &time[], const double &open[], const double &high[],
              const double &low[],   const double &close[], int total, int idx0)
{
   int s = MathMax(idx0, total - InpExtraLookback);
   for(int i = s + 1; i < total - 1; i++)
   {
      // Bullish FVG
      if(high[i-1] < low[i+1])
      {
         string nm = g_pfx + "BFVG_" + IntegerToString(i);
         MakeRect(nm, time[i-1], low[i+1], time[i+1]+300, high[i-1],
                  InpFVGBullClr, true);
      }
      // Bearish FVG
      if(low[i-1] > high[i+1])
      {
         string nm = g_pfx + "SFVG_" + IntegerToString(i);
         MakeRect(nm, time[i-1], low[i-1], time[i+1]+300, high[i+1],
                  InpFVGBearClr, true);
      }
   }
}

//+------------------------------------------------------------------+
//  ORDER BLOCKS
//+------------------------------------------------------------------+
void DrawOBs(const datetime &time[], const double &open[], const double &high[],
             const double &low[],   const double &close[], int total, int idx0)
{
   int s = MathMax(idx0, total - InpExtraLookback);
   int min_move = 3;
   int ext = 25;

   for(int i = s; i < total - min_move - 1; i++)
   {
      // Bullish OB: bearish candle then 3 bullish
      if(close[i] < open[i])
      {
         int bull = 0;
         for(int j = i+1; j <= i+min_move && j < total; j++)
            if(close[j] > open[j]) bull++;
         if(bull >= min_move)
         {
            datetime te = time[MathMin(i+ext, total-1)] + 300;
            MakeRect(g_pfx+"BOB_"+IntegerToString(i),
                     time[i], open[i], te, close[i],
                     InpOBBullClr, true);
         }
      }
      // Bearish OB
      if(close[i] > open[i])
      {
         int bear = 0;
         for(int j = i+1; j <= i+min_move && j < total; j++)
            if(close[j] < open[j]) bear++;
         if(bear >= min_move)
         {
            datetime te = time[MathMin(i+ext, total-1)] + 300;
            MakeRect(g_pfx+"SOB_"+IntegerToString(i),
                     time[i], close[i], te, open[i],
                     InpOBBearClr, true);
         }
      }
   }
}

//+------------------------------------------------------------------+
//  SWING POINTS
//+------------------------------------------------------------------+
void DrawSwings(const datetime &time[], const double &high[], const double &low[],
                int total, int idx0)
{
   int n = InpSwingN;
   for(int i = MathMax(idx0, n); i < total - n; i++)
   {
      bool sh = true;
      for(int j = 1; j <= n && sh; j++)
         if(high[i-j] >= high[i] || high[i+j] >= high[i]) sh = false;
      if(sh)
         MakeArrow(g_pfx+"SWH_"+IntegerToString(i), time[i], high[i]+_Point*20, 218, InpSwingHClr);

      bool sl = true;
      for(int j = 1; j <= n && sl; j++)
         if(low[i-j] <= low[i] || low[i+j] <= low[i]) sl = false;
      if(sl)
         MakeArrow(g_pfx+"SWL_"+IntegerToString(i), time[i], low[i]-_Point*20,  217, InpSwingLClr);
   }
}

//+------------------------------------------------------------------+
//  BREAKER BLOCKS  (broken OBs that flip direction)
//+------------------------------------------------------------------+
void DrawBreakers(const datetime &time[], const double &open[], const double &high[],
                  const double &low[],   const double &close[], int total, int idx0)
{
   int s = MathMax(idx0, total - InpExtraLookback);
   int min_move = 3, ext = 20;

   for(int i = s; i < total - min_move - 2; i++)
   {
      if(close[i] < open[i])
      {
         int bull = 0;
         for(int j = i+1; j <= i+min_move && j < total; j++)
            if(close[j] > open[j]) bull++;
         if(bull >= min_move)
         {
            double oblo = close[i];
            int brk = -1;
            for(int j = i+min_move+1; j < total; j++)
               if(close[j] < oblo) { brk = j; break; }
            if(brk > 0)
            {
               datetime te = time[MathMin(brk+ext, total-1)] + 300;
               MakeRect(g_pfx+"BRKB_"+IntegerToString(i),
                        time[i], open[i], te, oblo,
                        InpBreakerClr, false, STYLE_DASH);
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//  VOIDS
//+------------------------------------------------------------------+
void DrawVoids(const datetime &time[], const double &open[], const double &high[],
               const double &low[], const double &close[], const double &atr[],
               int total, int idx0)
{
   int ext = 30;
   for(int i = idx0; i < total - 1; i++)
   {
      double body = MathAbs(close[i] - open[i]);
      double a    = (i < ArraySize(atr)) ? atr[i] : 0;
      if(a <= 0) continue;
      if(body >= InpVoidATR * a)
      {
         double top = MathMax(open[i], close[i]);
         double bot = MathMin(open[i], close[i]);
         datetime te = time[MathMin(i+ext, total-1)] + 300;
         MakeRect(g_pfx+"VOID_"+IntegerToString(i),
                  time[i], top, te, bot,
                  InpVoidClr, false, STYLE_DOT);
      }
   }
}
//+------------------------------------------------------------------+
