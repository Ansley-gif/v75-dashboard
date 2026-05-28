//+------------------------------------------------------------------+
//|                                            SessionOCLevels.mq5  |
//|   ICT-style session indicator. For the CURRENT trading day only |
//|   (trading day = Asia open → next Asia open, i.e. 22:00→22:00). |
//|                                                                  |
//|   Per session draws:                                            |
//|     • Shaded box from session OPEN time to CLOSE time,          |
//|       vertically from session-high-so-far to session-low-so-far |
//|     • SOLID horizontal lines at OPEN-candle H + L                |
//|     • DASHED horizontal lines at CLOSE-candle H + L              |
//|     • Dotted vertical line at session END                        |
//|                                                                  |
//|   Auto-clears every new trading day so old levels never overlap |
//|   with the current day's levels.                                |
//+------------------------------------------------------------------+
#property copyright "V75 Trading Systems"
#property version   "2.00"
#property strict
#property indicator_chart_window
#property indicator_plots 0

//── INPUTS ────────────────────────────────────────────────────────
input group "═══ SESSION TIMES (UTC, hours) ═══"
input int    InpAsiaOpenH    = 22;
input int    InpAsiaCloseH   = 9;
input int    InpLondonOpenH  = 7;
input int    InpLondonCloseH = 16;
input int    InpNYOpenH      = 13;
input int    InpNYCloseH     = 22;

input group "═══ COLOURS ═══"
input color  InpAsiaColor    = clrDodgerBlue;
input color  InpAsiaBoxClr   = clrLightCyan;
input color  InpLondonColor  = clrLimeGreen;
input color  InpLondonBoxClr = clrHoneydew;
input color  InpNYColor      = clrOrange;
input color  InpNYBoxClr     = clrSeashell;

input group "═══ STYLE ═══"
input int    InpLineWidth    = 2;
input bool   InpShowBoxes    = true;
input bool   InpShowOCLines  = true;
input bool   InpShowCCLines  = true;
input bool   InpShowEndLines = true;

#define PFX "SOL_"

datetime g_tday_start = 0;          // current trading day start

//+------------------------------------------------------------------+
int OnInit()
{
   IndicatorSetString(INDICATOR_SHORTNAME, "Session OC/CC Levels v2");
   ObjectsDeleteAll(0, PFX);
   g_tday_start = 0;
   return INIT_SUCCEEDED;
}

void OnDeinit(const int r) { ObjectsDeleteAll(0, PFX); }

//+------------------------------------------------------------------+
int OnCalculate(const int rates_total, const int prev_calculated,
                const datetime &time[], const double &open[],
                const double &high[], const double &low[],
                const double &close[], const long &tick_volume[],
                const long &volume[], const int &spread[])
{
   if(rates_total < 2) return rates_total;

   datetime tday = ComputeTradingDayStart();

   // New trading day? wipe and start fresh
   if(tday != g_tday_start)
   {
      ObjectsDeleteAll(0, PFX);
      g_tday_start = tday;
   }

   // Draw each session for the CURRENT trading day
   DrawSession("ASIA", InpAsiaOpenH,   InpAsiaCloseH,   InpAsiaColor,   InpAsiaBoxClr,   tday);
   DrawSession("LDN",  InpLondonOpenH, InpLondonCloseH, InpLondonColor, InpLondonBoxClr, tday);
   DrawSession("NY",   InpNYOpenH,     InpNYCloseH,     InpNYColor,     InpNYBoxClr,     tday);

   return rates_total;
}

//+------------------------------------------------------------------+
//  Trading day starts at the most recent Asia-open hour (UTC).
//  e.g. if Asia opens at 22:00 and current UTC is 06:00 today,
//  trading day started yesterday at 22:00.
//+------------------------------------------------------------------+
datetime ComputeTradingDayStart()
{
   datetime now = TimeCurrent();
   MqlDateTime dt;
   TimeToStruct(now, dt);
   datetime today_asia = StructToTime(dt) - dt.hour*3600 - dt.min*60 - dt.sec
                       + (datetime)(InpAsiaOpenH * 3600);
   if(now < today_asia) return today_asia - 24*3600;
   return today_asia;
}

//+------------------------------------------------------------------+
//  Return the first time >= `after` whose hour-of-day == target_hour.
//+------------------------------------------------------------------+
datetime NextHourAtOrAfter(int target_hour, datetime after)
{
   MqlDateTime dt;
   TimeToStruct(after, dt);
   datetime day_start = StructToTime(dt) - dt.hour*3600 - dt.min*60 - dt.sec;
   datetime t = day_start + (datetime)(target_hour * 3600);
   while(t < after) t += 24*3600;
   return t;
}

//+------------------------------------------------------------------+
//  Compute high/low of all M5 bars between t1 and t2 (inclusive).
//+------------------------------------------------------------------+
void SessionHighLow(datetime t1, datetime t2, double &hi, double &lo)
{
   hi = 0; lo = DBL_MAX;
   int s1 = iBarShift(_Symbol, PERIOD_M5, t2, false);   // most recent
   int s2 = iBarShift(_Symbol, PERIOD_M5, t1, false);   // oldest
   if(s1 < 0 || s2 < 0) return;
   for(int i = s1; i <= s2; i++)
   {
      double h = iHigh(_Symbol, PERIOD_M5, i);
      double l = iLow (_Symbol, PERIOD_M5, i);
      if(h > hi) hi = h;
      if(l < lo) lo = l;
   }
   if(lo == DBL_MAX) lo = 0;
}

//+------------------------------------------------------------------+
//  Draw OPEN, CLOSE, box and vertical-end objects for one session.
//+------------------------------------------------------------------+
void DrawSession(string tag, int oh, int ch, color line_clr, color box_clr, datetime tday)
{
   datetime now   = TimeCurrent();
   datetime oc_t  = NextHourAtOrAfter(oh, tday);
   datetime cc_t  = NextHourAtOrAfter(ch, oc_t);  // close strictly after open

   // ── OPEN candle (solid lines) ───────────────────────────────
   if(InpShowOCLines && now >= oc_t)
   {
      int sh = iBarShift(_Symbol, PERIOD_M5, oc_t, true);
      if(sh >= 0)
      {
         double h = iHigh(_Symbol, PERIOD_M5, sh);
         double l = iLow (_Symbol, PERIOD_M5, sh);
         DrawHLine(PFX+tag+"_OC_H", h, oc_t, cc_t, line_clr, STYLE_SOLID);
         DrawHLine(PFX+tag+"_OC_L", l, oc_t, cc_t, line_clr, STYLE_SOLID);
         DrawText (PFX+tag+"_OC_LBL", tag+" OC", oc_t, h, line_clr);
      }
   }

   // ── CLOSE candle (dashed lines) ─────────────────────────────
   if(InpShowCCLines && now >= cc_t)
   {
      int sh = iBarShift(_Symbol, PERIOD_M5, cc_t, true);
      if(sh >= 0)
      {
         double h = iHigh(_Symbol, PERIOD_M5, sh);
         double l = iLow (_Symbol, PERIOD_M5, sh);
         // CC lines extend to end of trading day
         datetime end_t = tday + 24*3600;
         DrawHLine(PFX+tag+"_CC_H", h, cc_t, end_t, line_clr, STYLE_DASH);
         DrawHLine(PFX+tag+"_CC_L", l, cc_t, end_t, line_clr, STYLE_DASH);
         DrawText (PFX+tag+"_CC_LBL", tag+" CC", cc_t, h, line_clr);
      }
   }

   // ── Shaded session box ──────────────────────────────────────
   if(InpShowBoxes && now >= oc_t)
   {
      datetime box_end = (now < cc_t) ? now : cc_t;
      double hi, lo;
      SessionHighLow(oc_t, box_end, hi, lo);
      if(hi > 0 && lo > 0)
         DrawRect(PFX+tag+"_BOX", oc_t, lo, box_end, hi, box_clr);
   }

   // ── Vertical line at session END ────────────────────────────
   if(InpShowEndLines && now >= oc_t)
      DrawVLine(PFX+tag+"_END", cc_t, line_clr);
}

//+------------------------------------------------------------------+
//  Drawing primitives
//+------------------------------------------------------------------+
void DrawHLine(string name, double price, datetime t1, datetime t2,
               color clr, int style)
{
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_TREND, 0, t1, price, t2, price);
   else
   {
      ObjectMove(0, name, 0, t1, price);
      ObjectMove(0, name, 1, t2, price);
   }
   ObjectSetInteger(0, name, OBJPROP_COLOR,     clr);
   ObjectSetInteger(0, name, OBJPROP_STYLE,     style);
   ObjectSetInteger(0, name, OBJPROP_WIDTH,     InpLineWidth);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
   ObjectSetInteger(0, name, OBJPROP_BACK,      false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE,false);
}

void DrawVLine(string name, datetime t, color clr)
{
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_VLINE, 0, t, 0);
   else
      ObjectMove(0, name, 0, t, 0);
   ObjectSetInteger(0, name, OBJPROP_COLOR,     clr);
   ObjectSetInteger(0, name, OBJPROP_STYLE,     STYLE_DOT);
   ObjectSetInteger(0, name, OBJPROP_WIDTH,     1);
   ObjectSetInteger(0, name, OBJPROP_BACK,      true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE,false);
}

void DrawText(string name, string txt, datetime t, double price, color clr)
{
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_TEXT, 0, t, price);
   else
      ObjectMove(0, name, 0, t, price);
   ObjectSetString (0, name, OBJPROP_TEXT,       txt);
   ObjectSetInteger(0, name, OBJPROP_COLOR,      clr);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE,   8);
   ObjectSetInteger(0, name, OBJPROP_ANCHOR,     ANCHOR_LEFT_LOWER);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
}

void DrawRect(string name, datetime t1, double p1, datetime t2, double p2, color clr)
{
   if(ObjectFind(0, name) < 0)
      ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, p1, t2, p2);
   else
   {
      ObjectMove(0, name, 0, t1, p1);
      ObjectMove(0, name, 1, t2, p2);
   }
   ObjectSetInteger(0, name, OBJPROP_COLOR,     clr);
   ObjectSetInteger(0, name, OBJPROP_FILL,      true);
   ObjectSetInteger(0, name, OBJPROP_BACK,      true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE,false);
   ObjectSetInteger(0, name, OBJPROP_STYLE,     STYLE_SOLID);
   ObjectSetInteger(0, name, OBJPROP_WIDTH,     1);
}
//+------------------------------------------------------------------+
