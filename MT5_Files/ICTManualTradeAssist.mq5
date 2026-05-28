//+------------------------------------------------------------------+
//|                                      ICTManualTradeAssist.mq5    |
//|   Manual-trading companion for ICTSessionsEA strategy.           |
//|                                                                  |
//|   Shows exactly what the EA sees so you can hand-trade the same  |
//|   setups: session boxes, OC/CC level lines with live ARMED state,|
//|   13:00 UTC trade-window highlight, status panel, SL/TP guides.  |
//|                                                                  |
//|   Default inputs mirror ICTSessionsEA defaults:                  |
//|     • Trade hour : 13:00 UTC (NY open)                           |
//|     • SL distance: 2000 ticks                                    |
//|     • TP distance: 6000 ticks                                    |
//|                                                                  |
//|   ARMED logic (matches EA exactly):                              |
//|     • Each OC/CC candle creates HI and LO levels                 |
//|     • A level is ARMED until a bar.close crosses past it         |
//|     • Once fired, level becomes UNARMED                          |
//|     • Re-arms when a bar.close goes back through to inside box   |
//+------------------------------------------------------------------+
#property copyright "V25 Trading Systems"
#property version   "1.00"
#property strict
#property indicator_chart_window
#property indicator_plots 0

//── INPUTS ────────────────────────────────────────────────────────
input group "═══ SESSION TIMES (UTC) ═══"
input int InpAsiaOpenH    = 22;
input int InpAsiaCloseH   = 9;
input int InpLondonOpenH  = 7;
input int InpLondonCloseH = 16;
input int InpNYOpenH      = 13;
input int InpNYCloseH     = 22;

input group "═══ TRADE WINDOW (matches EA InpHoursAllowed) ═══"
input int InpTradeHourUTC = 13;     // The single UTC hour to trade

input group "═══ STRATEGY PARAMS (match EA) ═══"
input int InpFixedSLTicks  = 2000;
input int InpTPTicks       = 6000;
input int InpLevelTTLHours = 24;

input group "═══ VISUAL TOGGLES ═══"
input bool InpShowBoxes        = true;
input bool InpShowOCCCLines    = true;
input bool InpShowArmedState   = true;   // ARMED=solid, UNARMED=dotted
input bool InpShowTradeWindow  = true;   // Vertical band on the trade hour
input bool InpShowStatusPanel  = true;
input bool InpShowSLTPGuides   = true;   // Horizontal guides from current bid

input group "═══ COLOURS ═══"
input color InpAsiaColor      = clrDodgerBlue;
input color InpAsiaBoxClr     = clrLightCyan;
input color InpLondonColor    = clrLimeGreen;
input color InpLondonBoxClr   = clrHoneydew;
input color InpNYColor        = clrOrange;
input color InpNYBoxClr       = clrSeashell;
input color InpUnarmedClr     = clrDimGray;
input color InpTradeWinClr    = C'220,255,220'; // pale green
input color InpSLGuideClr     = clrCrimson;
input color InpTPGuideClr     = clrForestGreen;
input color InpPanelOpenClr   = clrLime;
input color InpPanelClosedClr = clrGoldenrod;
input color InpPanelTextClr   = clrWhite;
input color InpPanelHdrClr    = clrAqua;

input group "═══ LAYOUT ═══"
input int InpPanelX = 10;
input int InpPanelY = 18;
input int InpPanelLineHeight = 14;
input int InpPanelFontSize   = 9;
input int InpLineWidth       = 2;

#define PFX "MTA_"
#define MAX_LEVELS 32
#define MAX_PANEL_LINES 16

//── STATE ─────────────────────────────────────────────────────────
struct Level
{
   string   tag;
   double   price;
   double   opp_extreme;
   bool     is_high;
   datetime created;
   datetime expires;
   color    sess_clr;
   bool     armed;
   bool     fired_today;
};

Level    g_levels[MAX_LEVELS];
int      g_n_levels         = 0;
datetime g_last_bar_done    = 0;
datetime g_tday_start       = 0;
int      g_signals_today    = 0;

//+------------------------------------------------------------------+
int OnInit()
{
   IndicatorSetString(INDICATOR_SHORTNAME, "ICT Manual Trade Assist");
   ObjectsDeleteAll(0, PFX);
   g_n_levels        = 0;
   g_last_bar_done   = 0;
   g_tday_start      = 0;
   g_signals_today   = 0;

   PrintFormat("[ICTMTA] init. Symbol=%s ChartTF=%d  Recommended TF: M5",
               _Symbol, (int)_Period);
   if(_Period != PERIOD_M5)
      PrintFormat("[ICTMTA] WARNING: chart timeframe is not M5. "
                  "Levels are read from M5 explicitly and will still work, "
                  "but session boxes may look stretched.");
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
   if(rates_total < 50) return rates_total;

   datetime tday = ComputeTradingDayStart();
   if(tday != g_tday_start)
   {
      g_tday_start    = tday;
      g_signals_today = 0;
      for(int i = 0; i < g_n_levels; i++) g_levels[i].fired_today = false;
   }

   datetime last_closed = iTime(_Symbol, _Period, 1);
   bool new_bar = (last_closed != g_last_bar_done);

   if(new_bar)
   {
      int n_before = g_n_levels;
      ScanForLevels();
      int n_added = g_n_levels - n_before;
      PruneExpired();
      ReplayArmedStates();
      RedrawSessionBoxes(tday);
      int n_drawn = RedrawLevels();
      if(n_added > 0 || g_last_bar_done == 0)
         PrintFormat("[ICTMTA] Scan: %d levels total (added %d). Drew %d level lines.",
                     g_n_levels, n_added, n_drawn);
      g_last_bar_done = last_closed;
   }

   // Cheap per-tick updates (price-dependent)
   if(InpShowTradeWindow) DrawTradeWindow(tday);
   if(InpShowStatusPanel) DrawStatusPanel();
   if(InpShowSLTPGuides)  DrawSLTPGuides();

   return rates_total;
}

//+------------------------------------------------------------------+
//  TRADING-DAY UTILITIES
//+------------------------------------------------------------------+
datetime ComputeTradingDayStart()
{
   datetime now = TimeCurrent();
   MqlDateTime dt; TimeToStruct(now, dt);
   datetime today_asia = StructToTime(dt) - dt.hour*3600 - dt.min*60 - dt.sec
                       + (datetime)(InpAsiaOpenH * 3600);
   if(now < today_asia) return today_asia - 24*3600;
   return today_asia;
}

datetime NextHourAtOrAfter(int target_hour, datetime after)
{
   MqlDateTime dt; TimeToStruct(after, dt);
   datetime day_start = StructToTime(dt) - dt.hour*3600 - dt.min*60 - dt.sec;
   datetime t = day_start + (datetime)(target_hour * 3600);
   while(t < after) t += 24*3600;
   return t;
}

bool IsInTradeWindow()
{
   MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
   return (dt.hour == InpTradeHourUTC);
}

//+------------------------------------------------------------------+
//  LEVEL DISCOVERY — walk last InpLevelTTLHours of M5 bars
//+------------------------------------------------------------------+
void ScanForLevels()
{
   datetime now    = TimeCurrent();
   datetime cutoff = now - InpLevelTTLHours * 3600;

   int oldest = iBarShift(_Symbol, PERIOD_M5, cutoff, false);
   if(oldest < 0) oldest = Bars(_Symbol, PERIOD_M5) - 1;

   for(int i = oldest; i >= 0; i--)
   {
      datetime bt = iTime(_Symbol, PERIOD_M5, i);
      if(bt <= 0) continue;
      MqlDateTime dt; TimeToStruct(bt, dt);
      if(dt.min != 0) continue;

      double h = iHigh(_Symbol, PERIOD_M5, i);
      double l = iLow (_Symbol, PERIOD_M5, i);

      if(dt.hour == InpAsiaOpenH)    TryAddPair(bt, "ASIA_OC", h, l, InpAsiaColor);
      if(dt.hour == InpAsiaCloseH)   TryAddPair(bt, "ASIA_CC", h, l, InpAsiaColor);
      if(dt.hour == InpLondonOpenH)  TryAddPair(bt, "LDN_OC",  h, l, InpLondonColor);
      if(dt.hour == InpLondonCloseH) TryAddPair(bt, "LDN_CC",  h, l, InpLondonColor);
      if(dt.hour == InpNYOpenH)      TryAddPair(bt, "NY_OC",   h, l, InpNYColor);
      if(dt.hour == InpNYCloseH)     TryAddPair(bt, "NY_CC",   h, l, InpNYColor);
   }
}

void TryAddPair(datetime created, string base_tag, double hi, double lo, color clr)
{
   // Disambiguate same-name levels from different days using a digits-only
   // suffix (MT5 object names tolerate dots, but some chart-state operations
   // treat the period as a delimiter — safer to avoid them in tags).
   MqlDateTime dt; TimeToStruct(created, dt);
   string suffix = StringFormat("_%02d%02d", dt.mon, dt.day);
   datetime ttl = created + (datetime)(InpLevelTTLHours * 3600);
   AddLevelOnce(base_tag + "_H" + suffix, hi, lo, true,  created, ttl, clr);
   AddLevelOnce(base_tag + "_L" + suffix, lo, hi, false, created, ttl, clr);
}

void AddLevelOnce(string tag, double price, double opp, bool is_high,
                  datetime created, datetime expires, color clr)
{
   for(int i = 0; i < g_n_levels; i++)
      if(g_levels[i].tag == tag) return;   // already known
   if(g_n_levels >= MAX_LEVELS) return;

   g_levels[g_n_levels].tag         = tag;
   g_levels[g_n_levels].price       = price;
   g_levels[g_n_levels].opp_extreme = opp;
   g_levels[g_n_levels].is_high     = is_high;
   g_levels[g_n_levels].created     = created;
   g_levels[g_n_levels].expires     = expires;
   g_levels[g_n_levels].sess_clr    = clr;
   g_levels[g_n_levels].armed       = true;
   g_levels[g_n_levels].fired_today = false;
   g_n_levels++;
}

void PruneExpired()
{
   datetime now = TimeCurrent();
   int w = 0;
   for(int r = 0; r < g_n_levels; r++)
   {
      if(g_levels[r].expires < now)
      {
         ObjectDelete(0, PFX + "LVL_" + g_levels[r].tag);
         ObjectDelete(0, PFX + "LVL_" + g_levels[r].tag + "_LBL");
         continue;
      }
      if(r != w) g_levels[w] = g_levels[r];
      w++;
   }
   g_n_levels = w;
}

//+------------------------------------------------------------------+
//  REPLAY ARMED STATE — walk from level.created to now, applying
//  fire/re-arm rules per closed M5 bar. Matches the EA's logic.
//+------------------------------------------------------------------+
void ReplayArmedStates()
{
   for(int i = 0; i < g_n_levels; i++)
   {
      Level lvl = g_levels[i];
      int from_shift = iBarShift(_Symbol, PERIOD_M5, lvl.created, false);
      if(from_shift < 0) continue;

      bool armed = true;
      bool fired_today = false;

      for(int s = from_shift - 1; s >= 1; s--)   // skip the defining bar itself, skip the live bar
      {
         double close_p = iClose(_Symbol, PERIOD_M5, s);
         datetime bt    = iTime (_Symbol, PERIOD_M5, s);
         if(close_p <= 0 || bt <= 0) continue;
         if(bt > lvl.expires) break;

         bool was_armed = armed;

         if(armed)
         {
            if(lvl.is_high && close_p > lvl.price) armed = false;
            else if(!lvl.is_high && close_p < lvl.price) armed = false;
         }
         else
         {
            if(lvl.is_high && close_p < lvl.price) armed = true;
            else if(!lvl.is_high && close_p > lvl.price) armed = true;
         }

         // Mark as fired-today if this transition happened inside trade window
         // and today's trading day.
         if(was_armed && !armed && bt >= g_tday_start)
         {
            MqlDateTime dt; TimeToStruct(bt, dt);
            if(dt.hour == InpTradeHourUTC) fired_today = true;
         }
      }

      g_levels[i].armed       = armed;
      g_levels[i].fired_today = fired_today;
   }

   // Recount today's signals from level flags
   g_signals_today = 0;
   for(int i = 0; i < g_n_levels; i++)
      if(g_levels[i].fired_today) g_signals_today++;
}

//+------------------------------------------------------------------+
//  DRAW — SESSION BOXES
//+------------------------------------------------------------------+
void RedrawSessionBoxes(datetime tday)
{
   if(!InpShowBoxes) return;
   DrawOneSessionBox("ASIA", InpAsiaOpenH,   InpAsiaCloseH,   InpAsiaBoxClr,   tday);
   DrawOneSessionBox("LDN",  InpLondonOpenH, InpLondonCloseH, InpLondonBoxClr, tday);
   DrawOneSessionBox("NY",   InpNYOpenH,     InpNYCloseH,     InpNYBoxClr,     tday);
}

void DrawOneSessionBox(string tag, int oh, int ch, color box_clr, datetime tday)
{
   datetime oc_t  = NextHourAtOrAfter(oh, tday);
   datetime cc_t  = NextHourAtOrAfter(ch, oc_t);
   datetime now   = TimeCurrent();
   if(now < oc_t) return;
   datetime box_end = (now < cc_t) ? now : cc_t;

   double hi, lo;
   SessionHighLow(oc_t, box_end, hi, lo);
   if(hi <= 0 || lo <= 0) return;

   DrawRect(PFX + tag + "_BOX", oc_t, lo, box_end, hi, box_clr);
}

void SessionHighLow(datetime t1, datetime t2, double &hi, double &lo)
{
   hi = 0; lo = DBL_MAX;
   int s1 = iBarShift(_Symbol, PERIOD_M5, t2, false);
   int s2 = iBarShift(_Symbol, PERIOD_M5, t1, false);
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
//  DRAW — LEVEL LINES with ARMED state
//+------------------------------------------------------------------+
int RedrawLevels()
{
   if(!InpShowOCCCLines) return 0;

   int drawn = 0;
   for(int i = 0; i < g_n_levels; i++)
   {
      Level lvl = g_levels[i];
      string name     = PFX + "LVL_" + lvl.tag;
      string lbl_name = name + "_LBL";

      bool   is_oc  = (StringFind(lvl.tag, "_OC") >= 0);
      color  clr;
      int    style;
      int    width;

      if(InpShowArmedState && !lvl.armed)
      {
         clr   = InpUnarmedClr;
         style = STYLE_DOT;
         width = 1;
      }
      else
      {
         clr   = lvl.sess_clr;
         style = is_oc ? STYLE_SOLID : STYLE_DASH;
         width = InpLineWidth;
      }

      // Extend the line to the right edge of the chart so it's always visible
      // (some charts/timeframes can drop trend lines whose endpoint is in the
      // future but close to current time)
      datetime line_t2 = lvl.expires;
      DrawHLine(name, lvl.price, lvl.created, line_t2, clr, style, width);

      string lbl = lvl.tag;
      if(InpShowArmedState) lbl += lvl.armed ? "  [ARMED]" : "  [UNARMED]";
      DrawText(lbl_name, lbl, lvl.created, lvl.price, clr);
      drawn++;
   }
   return drawn;
}

//+------------------------------------------------------------------+
//  DRAW — 13:00 UTC TRADE WINDOW
//+------------------------------------------------------------------+
void DrawTradeWindow(datetime tday)
{
   datetime ws = NextHourAtOrAfter(InpTradeHourUTC, tday);
   datetime we = ws + 3600;

   // Use a sane price range derived from current bid, NOT 0→1e9.
   // The earlier huge-rectangle approach was making MT5 silently drop
   // other chart objects (trend lines, rectangles) anchored to absolute
   // prices, because the renderer treats it as a non-finite anchor.
   double bid       = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double half_band = MathMax(bid * 0.5, 100.0);   // ±50% of bid, min ±100
   double top       = bid + half_band;
   double bot       = MathMax(bid - half_band, 0.01);

   string name = PFX + "TRADE_WIN";
   if(ObjectFind(0, name) < 0)
   {
      if(!ObjectCreate(0, name, OBJ_RECTANGLE, 0, ws, bot, we, top))
         PrintFormat("[ICTMTA] DrawTradeWindow create failed: err=%d", GetLastError());
   }
   else
   {
      ObjectMove(0, name, 0, ws, bot);
      ObjectMove(0, name, 1, we, top);
   }
   ObjectSetInteger(0, name, OBJPROP_COLOR,       InpTradeWinClr);
   ObjectSetInteger(0, name, OBJPROP_FILL,        true);
   ObjectSetInteger(0, name, OBJPROP_BACK,        true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE,  false);
   ObjectSetInteger(0, name, OBJPROP_STYLE,       STYLE_SOLID);
   ObjectSetInteger(0, name, OBJPROP_WIDTH,       1);
}

//+------------------------------------------------------------------+
//  DRAW — STATUS PANEL (top-left, stacked OBJ_LABELs)
//+------------------------------------------------------------------+
void DrawStatusPanel()
{
   string lines[MAX_PANEL_LINES];
   color  clrs [MAX_PANEL_LINES];
   for(int i = 0; i < MAX_PANEL_LINES; i++) { lines[i] = ""; clrs[i] = InpPanelTextClr; }

   bool open_now = IsInTradeWindow();
   string window_str;
   color  window_clr;
   if(open_now)
   {
      MqlDateTime dt; TimeToStruct(TimeCurrent(), dt);
      int mins_left = 60 - dt.min;
      window_str = StringFormat("  TRADE WINDOW OPEN  (%d min left)", mins_left);
      window_clr = InpPanelOpenClr;
   }
   else
   {
      datetime now = TimeCurrent();
      datetime next = NextHourAtOrAfter(InpTradeHourUTC, now);
      int secs = (int)(next - now);
      int h    = secs / 3600;
      int m    = (secs % 3600) / 60;
      window_str = StringFormat("  CLOSED — opens in %02dh %02dm", h, m);
      window_clr = InpPanelClosedClr;
   }

   double bid    = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double ask    = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   int    spread = (int)MathRound((ask - bid) / _Point);

   int line = 0;
   lines[line] = " ICT Manual Trade Assist";                clrs[line++] = InpPanelHdrClr;
   lines[line] = " " + TimeToString(TimeCurrent(), TIME_DATE|TIME_MINUTES) + " UTC"; clrs[line++] = InpPanelTextClr;
   lines[line] = window_str;                                clrs[line++] = window_clr;
   lines[line] = StringFormat(" Bid: %.*f   Spread: %d tk", _Digits, bid, spread); clrs[line++] = InpPanelTextClr;
   lines[line] = StringFormat(" Today: %d signals fired",   g_signals_today);      clrs[line++] = InpPanelTextClr;
   lines[line] = " ── Armed levels (dist to bid) ──";        clrs[line++] = InpPanelHdrClr;

   int shown = 0;
   for(int i = 0; i < g_n_levels && line < MAX_PANEL_LINES; i++)
   {
      if(!g_levels[i].armed) continue;
      int dist = (int)MathRound(MathAbs(bid - g_levels[i].price) / _Point);
      string dir = g_levels[i].is_high ? "↑" : "↓";
      lines[line] = StringFormat("  %s %s @ %.*f  (%d tk %s)",
                                 dir, g_levels[i].tag, _Digits, g_levels[i].price,
                                 dist,
                                 g_levels[i].is_high ? (bid < g_levels[i].price ? "below" : "ABOVE!")
                                                     : (bid > g_levels[i].price ? "above" : "BELOW!"));
      clrs[line] = g_levels[i].sess_clr;
      line++;
      shown++;
   }
   if(shown == 0 && line < MAX_PANEL_LINES)
   {
      lines[line] = "  (no armed levels)";
      clrs[line++] = InpUnarmedClr;
   }

   // Render: create/update used lines; delete unused ones so we don't leave
   // ghost "Label" text from MT5's OBJ_LABEL default
   for(int i = 0; i < MAX_PANEL_LINES; i++)
   {
      string name = PFX + "PNL_" + IntegerToString(i);
      if(lines[i] == "")
      {
         if(ObjectFind(0, name) >= 0) ObjectDelete(0, name);
         continue;
      }
      if(ObjectFind(0, name) < 0)
      {
         ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
         ObjectSetInteger(0, name, OBJPROP_CORNER,     CORNER_LEFT_UPPER);
         ObjectSetInteger(0, name, OBJPROP_ANCHOR,     ANCHOR_LEFT_UPPER);
         ObjectSetInteger(0, name, OBJPROP_XDISTANCE,  InpPanelX);
         ObjectSetInteger(0, name, OBJPROP_FONTSIZE,   InpPanelFontSize);
         ObjectSetString (0, name, OBJPROP_FONT,       "Consolas");
         ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
         ObjectSetInteger(0, name, OBJPROP_BACK,       false);
      }
      ObjectSetInteger(0, name, OBJPROP_YDISTANCE, InpPanelY + i * InpPanelLineHeight);
      ObjectSetString (0, name, OBJPROP_TEXT,      lines[i]);
      ObjectSetInteger(0, name, OBJPROP_COLOR,     clrs[i]);
   }
}

//+------------------------------------------------------------------+
//  DRAW — SL/TP GUIDES from current bid (both directions)
//+------------------------------------------------------------------+
void DrawSLTPGuides()
{
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double pt  = _Point;
   datetime now = TimeCurrent();
   datetime fwd = now + 4 * 3600;       // 4-hour forward projection

   // BUY scenario (entry at ASK ≈ bid + spread, but bid is close enough for visual)
   double buy_sl = bid - InpFixedSLTicks * pt;
   double buy_tp = bid + InpTPTicks      * pt;
   // SELL scenario
   double sell_sl = bid + InpFixedSLTicks * pt;
   double sell_tp = bid - InpTPTicks      * pt;

   DrawHLine(PFX+"G_BUY_SL",  buy_sl,  now, fwd, InpSLGuideClr, STYLE_DOT, 1);
   DrawHLine(PFX+"G_BUY_TP",  buy_tp,  now, fwd, InpTPGuideClr, STYLE_DOT, 1);
   DrawHLine(PFX+"G_SELL_SL", sell_sl, now, fwd, InpSLGuideClr, STYLE_DOT, 1);
   DrawHLine(PFX+"G_SELL_TP", sell_tp, now, fwd, InpTPGuideClr, STYLE_DOT, 1);

   DrawText(PFX+"G_BUY_SL_LBL",  "BUY SL  −"  + IntegerToString(InpFixedSLTicks) + "tk", fwd, buy_sl,  InpSLGuideClr);
   DrawText(PFX+"G_BUY_TP_LBL",  "BUY TP  +"  + IntegerToString(InpTPTicks)      + "tk", fwd, buy_tp,  InpTPGuideClr);
   DrawText(PFX+"G_SELL_SL_LBL", "SELL SL +"  + IntegerToString(InpFixedSLTicks) + "tk", fwd, sell_sl, InpSLGuideClr);
   DrawText(PFX+"G_SELL_TP_LBL", "SELL TP −"  + IntegerToString(InpTPTicks)      + "tk", fwd, sell_tp, InpTPGuideClr);
}

//+------------------------------------------------------------------+
//  DRAWING PRIMITIVES
//+------------------------------------------------------------------+
void DrawHLine(string name, double price, datetime t1, datetime t2,
               color clr, int style, int width)
{
   if(ObjectFind(0, name) < 0)
   {
      if(!ObjectCreate(0, name, OBJ_TREND, 0, t1, price, t2, price))
      {
         PrintFormat("[ICTMTA] DrawHLine(%s) create failed: err=%d  t1=%s t2=%s price=%.5f",
                     name, GetLastError(),
                     TimeToString(t1), TimeToString(t2), price);
         return;
      }
   }
   else
   {
      ObjectMove(0, name, 0, t1, price);
      ObjectMove(0, name, 1, t2, price);
   }
   ObjectSetInteger(0, name, OBJPROP_COLOR,      clr);
   ObjectSetInteger(0, name, OBJPROP_STYLE,      style);
   ObjectSetInteger(0, name, OBJPROP_WIDTH,      width);
   ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT,  false);
   ObjectSetInteger(0, name, OBJPROP_BACK,       false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN,     false);
}

void DrawText(string name, string txt, datetime t, double price, color clr)
{
   if(ObjectFind(0, name) < 0)
   {
      if(!ObjectCreate(0, name, OBJ_TEXT, 0, t, price))
      {
         PrintFormat("[ICTMTA] DrawText(%s) create failed: err=%d", name, GetLastError());
         return;
      }
   }
   else
      ObjectMove(0, name, 0, t, price);
   ObjectSetString (0, name, OBJPROP_TEXT,       txt);
   ObjectSetInteger(0, name, OBJPROP_COLOR,      clr);
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE,   8);
   ObjectSetInteger(0, name, OBJPROP_ANCHOR,     ANCHOR_LEFT_LOWER);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN,     false);
}

void DrawRect(string name, datetime t1, double p1, datetime t2, double p2, color clr)
{
   if(ObjectFind(0, name) < 0)
   {
      if(!ObjectCreate(0, name, OBJ_RECTANGLE, 0, t1, p1, t2, p2))
      {
         PrintFormat("[ICTMTA] DrawRect(%s) create failed: err=%d", name, GetLastError());
         return;
      }
   }
   else
   {
      ObjectMove(0, name, 0, t1, p1);
      ObjectMove(0, name, 1, t2, p2);
   }
   ObjectSetInteger(0, name, OBJPROP_COLOR,      clr);
   ObjectSetInteger(0, name, OBJPROP_FILL,       true);
   ObjectSetInteger(0, name, OBJPROP_BACK,       true);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
   ObjectSetInteger(0, name, OBJPROP_STYLE,      STYLE_SOLID);
   ObjectSetInteger(0, name, OBJPROP_WIDTH,      1);
   ObjectSetInteger(0, name, OBJPROP_HIDDEN,     false);
}
//+------------------------------------------------------------------+
