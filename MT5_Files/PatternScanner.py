#!/usr/bin/env python3
"""
ICT Session Breakout Pattern Scanner
V75 Trading Systems

Fetches 1+ year of M5 candles from Deriv API and backtests 6 ICT-style
session breakout patterns, then prints a full statistical report.

Usage:
    pip install websockets
    python PatternScanner.py
    python PatternScanner.py --symbol R_75 --years 1 --tp 75 --sl 40
    python PatternScanner.py --symbol R_10 --years 2 --tp 50 --sl 30

Output:
    Console report (win rates, R:R, best days/hours, monthly breakdown)
    scanner_results.csv  (every trade row)
"""

import asyncio
import json
import time
import sys
import csv
import argparse
from datetime import datetime, timezone
from collections import defaultdict

try:
    import websockets
except ImportError:
    print("Missing dependency — run:  pip install websockets")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

DERIV_WS_URL    = "wss://ws.derivws.com/websockets/v3?app_id=1089"
CANDLES_PER_REQ = 4900   # just under Deriv's 5000-bar cap

# Session windows (UTC hours, half-open intervals [open, close))
SESSIONS = {
    "ASIAN":  (0,  8),
    "LONDON": (8,  17),
    "NY":     (13, 22),
}

DAYS_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# Broker-realistic defaults per symbol. Pulled from MT5 OnInit diagnostics on
# the live Deriv SVG account. When the scanner runs against one of these
# symbols WITHOUT --spread/--stops-level, the preset is auto-loaded so we
# can never accidentally produce an idealised "no broker friction" report.
# Add more rows as we verify other symbols against their broker OnInit logs.
BROKER_PRESETS = {
    "R_25": {"spread": 137, "stops_level": 423,   "point": 0.001},
    # "R_75": {"spread": ???, "stops_level": 10770, "point": 0.01},   # stops_level confirmed, spread TBD
}


# ─────────────────────────────────────────────────────────────────────────────
# DATA LAYER
# ─────────────────────────────────────────────────────────────────────────────

async def _fetch_batch(ws, symbol: str, count: int, end_epoch: int) -> list:
    req = {
        "ticks_history": symbol,
        "granularity": 300,       # M5 = 300 seconds
        "count": count,
        "end": end_epoch,
        "style": "candles",
        "adjust_start_time": 1,
    }
    await ws.send(json.dumps(req))
    raw = json.loads(await ws.recv())
    if "error" in raw:
        print(f"  API error: {raw['error']['message']}")
        return []
    return raw.get("candles", [])


async def fetch_history(symbol: str, years: float = 1.0) -> list:
    """
    Fetch ~years worth of M5 candles by batching Deriv API calls.
    Returns a list of bar dicts sorted oldest → newest.
    """
    total_bars = int(years * 365 * 24 * 12)   # ~105 k for 1 year
    batches    = (total_bars + CANDLES_PER_REQ - 1) // CANDLES_PER_REQ
    end_epoch  = int(time.time())
    collected  = []

    print(f"Fetching ≈{total_bars:,} M5 bars ({years:.1f} yr) for {symbol}…")

    async with websockets.connect(DERIV_WS_URL, ping_interval=30) as ws:
        for b in range(batches):
            bars = await _fetch_batch(ws, symbol, CANDLES_PER_REQ, end_epoch)
            if not bars:
                break

            collected = bars + collected          # prepend so oldest is first
            oldest_dt = datetime.utcfromtimestamp(bars[0]["epoch"]).strftime("%Y-%m-%d")
            print(f"  Batch {b+1}/{batches}: {len(bars)} bars  oldest={oldest_dt}")

            end_epoch = bars[0]["epoch"] - 1      # next batch ends just before this
            await asyncio.sleep(0.4)              # gentle rate limiting

            if len(bars) < CANDLES_PER_REQ:
                print("  Reached history limit.")
                break

    # Deduplicate and sort
    seen, unique = set(), []
    for bar in collected:
        if bar["epoch"] not in seen:
            seen.add(bar["epoch"])
            unique.append(bar)
    unique.sort(key=lambda x: x["epoch"])

    print(f"Total unique bars: {len(unique):,}  "
          f"({datetime.utcfromtimestamp(unique[0]['epoch']).strftime('%Y-%m-%d')} → "
          f"{datetime.utcfromtimestamp(unique[-1]['epoch']).strftime('%Y-%m-%d')})\n")
    return unique


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _hour(epoch):   return datetime.utcfromtimestamp(epoch).hour
def _minute(epoch): return datetime.utcfromtimestamp(epoch).minute
def _dow(epoch):    return datetime.utcfromtimestamp(epoch).weekday()   # 0=Mon
def _date(epoch):   return datetime.utcfromtimestamp(epoch).strftime("%Y-%m-%d")
def _month(epoch):  return datetime.utcfromtimestamp(epoch).strftime("%Y-%m")

def _atr(bars, i, period=14):
    """Simple ATR at bar i."""
    start = max(0, i - period + 1)
    vals  = []
    for j in range(start, i + 1):
        hi = bars[j]["high"]
        lo = bars[j]["low"]
        pc = bars[j-1]["close"] if j > 0 else bars[j]["open"]
        vals.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
    return sum(vals) / len(vals) if vals else 0.0


# ─────────────────────────────────────────────────────────────────────────────
# TRADE OBJECT
# ─────────────────────────────────────────────────────────────────────────────

class Trade:
    __slots__ = ("pattern", "direction", "session", "entry", "sl", "tp",
                 "entry_epoch", "dow", "hour",
                 "outcome", "exit_price", "bars_held", "r_multiple")

    def __init__(self, pattern, direction, session, entry, sl, tp, epoch, dow, hour):
        self.pattern     = pattern
        self.direction   = direction    # "BUY" | "SELL"
        self.session     = session
        self.entry       = entry
        self.sl          = sl
        self.tp          = tp
        self.entry_epoch = epoch
        self.dow         = dow
        self.hour        = hour
        self.outcome     = "OPEN"
        self.exit_price  = None
        self.bars_held   = 0
        self.r_multiple  = None

    def risk(self):   return abs(self.entry - self.sl)
    def reward(self): return abs(self.tp    - self.entry)


def _simulate(trade: Trade, bars: list, entry_idx: int, max_fwd: int = 200):
    """Walk forward from entry_idx; set trade.outcome = WIN | LOSS | OPEN.

    Same-bar tie-break: when a bar's range spans BOTH the TP and SL in the
    same candle, whichever level is CLOSER to entry is assumed to have been
    hit first.  For a typical SL < TP setup (e.g. 500:940) the SL is closer,
    so the trade is a LOSS — a conservative but realistic assumption for
    high-ATR instruments like V25 where M5 candles routinely exceed the
    combined SL+TP range.  The old code always checked TP first, silently
    awarding WIN on every same-bar hit and inflating win-rates by 20-30 pp.
    """
    risk = trade.risk()
    if risk <= 0:
        trade.outcome = "INVALID"
        return

    for i in range(entry_idx + 1, min(entry_idx + max_fwd, len(bars))):
        b = bars[i]
        trade.bars_held += 1

        if trade.direction == "BUY":
            tp_hit = b["high"] >= trade.tp
            sl_hit = b["low"]  <= trade.sl
            if tp_hit and sl_hit:
                # Both touched same bar: closer level to entry was hit first.
                # If TP is closer → WIN; if SL is closer (or equal) → LOSS.
                tp_hit = (trade.tp - trade.entry) < (trade.entry - trade.sl)
                sl_hit = not tp_hit
            if tp_hit:
                trade.outcome    = "WIN"
                trade.exit_price = trade.tp
                trade.r_multiple = trade.reward() / risk
                return
            if sl_hit:
                trade.outcome    = "LOSS"
                trade.exit_price = trade.sl
                trade.r_multiple = -1.0
                return
        else:  # SELL
            tp_hit = b["low"]  <= trade.tp
            sl_hit = b["high"] >= trade.sl
            if tp_hit and sl_hit:
                tp_hit = (trade.entry - trade.tp) < (trade.sl - trade.entry)
                sl_hit = not tp_hit
            if tp_hit:
                trade.outcome    = "WIN"
                trade.exit_price = trade.tp
                trade.r_multiple = trade.reward() / risk
                return
            if sl_hit:
                trade.outcome    = "LOSS"
                trade.exit_price = trade.sl
                trade.r_multiple = -1.0
                return

    trade.outcome    = "OPEN"
    trade.exit_price = bars[min(entry_idx + max_fwd, len(bars)-1)]["close"]


# ─────────────────────────────────────────────────────────────────────────────
# PATTERN 1 — SESSION H/L BREAKOUT  (the base strategy)
# ─────────────────────────────────────────────────────────────────────────────

def scan_session_breakout(bars, tp, sl, pt, init_bars=12):
    """
    Core ICT session breakout:
    First init_bars of each session DEFINE the range (e.g. 12 bars = 1 hour).
    After that, the range is FROZEN.  Any subsequent close beyond it = entry.
    One entry per level per session instance.
    """
    trades = []
    state  = {s: dict(id=None, hi=0.0, lo=1e9, n=0, frozen=False,
                      range_hi=0.0, range_lo=0.0,
                      hi_done=False, lo_done=False)
              for s in SESSIONS}

    for i, bar in enumerate(bars):
        h = _hour(bar["epoch"])
        d = _date(bar["epoch"])

        for sess, (h1, h2) in SESSIONS.items():
            if not (h1 <= h < h2):
                continue

            sid = f"{d}_{sess}"
            st  = state[sess]

            if sid != st["id"]:                         # new session instance
                st.update(id=sid, hi=bar["high"], lo=bar["low"], n=1,
                          frozen=False, range_hi=0.0, range_lo=0.0,
                          hi_done=False, lo_done=False)
                continue

            st["n"] += 1

            # Building phase — accumulate H/L for first init_bars
            if not st["frozen"]:
                if bar["high"] > st["hi"]: st["hi"] = bar["high"]
                if bar["low"]  < st["lo"]: st["lo"] = bar["low"]
                if st["n"] >= init_bars:
                    st["range_hi"] = st["hi"]
                    st["range_lo"] = st["lo"]
                    st["frozen"]   = True
                continue

            # Frozen phase — check for breakout of the locked range
            if not st["hi_done"] and bar["close"] > st["range_hi"]:
                e = bar["close"]
                t = Trade("SESS_BREAK", "BUY", sess, e,
                          e - sl*pt, e + tp*pt,
                          bar["epoch"], _dow(bar["epoch"]), h)
                _simulate(t, bars, i)
                trades.append(t)
                st["hi_done"] = True

            if not st["lo_done"] and bar["close"] < st["range_lo"]:
                e = bar["close"]
                t = Trade("SESS_BREAK", "SELL", sess, e,
                          e + sl*pt, e - tp*pt,
                          bar["epoch"], _dow(bar["epoch"]), h)
                _simulate(t, bars, i)
                trades.append(t)
                st["lo_done"] = True

    return trades


# ─────────────────────────────────────────────────────────────────────────────
# PATTERN 2 — LONDON BREAKOUT OF ASIAN RANGE
# ─────────────────────────────────────────────────────────────────────────────

def scan_london_asian_break(bars, tp, sl, pt):
    """
    Highest-probability ICT setup — 'London Killzone':
    Asian session (00:00-08:00) builds a consolidation range.
    At London open (08:00-10:00) the first close OUTSIDE the Asian range
    becomes an entry.  SL = opposite side of Asian range.
    """
    trades  = []
    asian   = defaultdict(lambda: dict(hi=0.0, lo=1e9, n=0, done=False))
    traded  = {}   # date → {hi_done, lo_done}

    for i, bar in enumerate(bars):
        h = _hour(bar["epoch"])
        d = _date(bar["epoch"])

        if 0 <= h < 8:
            a = asian[d]
            if bar["high"] > a["hi"]: a["hi"] = bar["high"]
            if bar["low"]  < a["lo"]: a["lo"] = bar["low"]
            a["n"] += 1
            if a["n"] >= 12: a["done"] = True

        elif 8 <= h < 10:
            a = asian[d]
            if not a["done"] or a["hi"] == 0:
                continue

            if d not in traded:
                traded[d] = dict(hi_done=False, lo_done=False)
            tr = traded[d]
            dow = _dow(bar["epoch"])

            if not tr["hi_done"] and bar["close"] > a["hi"]:
                e = bar["close"]
                # SL uses full Asian range width; TP fixed
                t = Trade("LDN_ASIAN", "BUY", "LONDON", e,
                          a["lo"] - sl*pt*0.5, e + tp*pt,
                          bar["epoch"], dow, h)
                _simulate(t, bars, i)
                trades.append(t)
                tr["hi_done"] = True

            if not tr["lo_done"] and bar["close"] < a["lo"]:
                e = bar["close"]
                t = Trade("LDN_ASIAN", "SELL", "LONDON", e,
                          a["hi"] + sl*pt*0.5, e - tp*pt,
                          bar["epoch"], dow, h)
                _simulate(t, bars, i)
                trades.append(t)
                tr["lo_done"] = True

    return trades


# ─────────────────────────────────────────────────────────────────────────────
# PATTERN 3 — NY OPEN REVERSAL  (Judas Swing)
# ─────────────────────────────────────────────────────────────────────────────

def scan_ny_reversal(bars, tp, sl, pt):
    """
    ICT 'Judas Swing' / NY reversal:
    Track the London session direction by 12:00 UTC.
    At NY open (13:00-15:00) look for price to REVERSE the London bias —
    sweeping London H/L before the real NY move unfolds.
    """
    trades    = []
    ldn_info  = {}    # date → {open, close_12, hi, lo}
    ny_traded = set()

    for i, bar in enumerate(bars):
        h   = _hour(bar["epoch"])
        d   = _date(bar["epoch"])
        dow = _dow(bar["epoch"])

        # Build London profile up to 12:00
        if 8 <= h <= 12:
            if d not in ldn_info:
                ldn_info[d] = dict(open=bar["open"], hi=bar["high"],
                                   lo=bar["low"], close_12=None)
            li = ldn_info[d]
            if bar["high"] > li["hi"]: li["hi"] = bar["high"]
            if bar["low"]  < li["lo"]: li["lo"] = bar["low"]
            if h == 12:
                li["close_12"] = bar["close"]

        elif 13 <= h < 15 and d not in ny_traded:
            if d not in ldn_info:
                continue
            li = ldn_info[d]
            c12 = li.get("close_12") or bar["open"]

            ldn_bull = c12 > li["open"]   # London closed higher than it opened

            # Reversal SELL: London was bullish → NY breaks down
            if ldn_bull and bar["close"] < bar["open"]:
                e = bar["close"]
                t = Trade("NY_REVERSAL", "SELL", "NY", e,
                          li["hi"] + sl*pt, e - tp*pt,
                          bar["epoch"], dow, h)
                _simulate(t, bars, i)
                trades.append(t)
                ny_traded.add(d)

            # Reversal BUY: London was bearish → NY breaks up
            elif not ldn_bull and bar["close"] > bar["open"]:
                e = bar["close"]
                t = Trade("NY_REVERSAL", "BUY", "NY", e,
                          li["lo"] - sl*pt, e + tp*pt,
                          bar["epoch"], dow, h)
                _simulate(t, bars, i)
                trades.append(t)
                ny_traded.add(d)

    return trades


# ─────────────────────────────────────────────────────────────────────────────
# PATTERN 4 — OPENING RANGE BREAKOUT  (ORB)
# ─────────────────────────────────────────────────────────────────────────────

def scan_orb(bars, tp, sl, pt, orb_bars=6):
    """
    Opening Range Breakout:
    First orb_bars M5 candles of each session (= 30 min) define the ORB.
    Entry on first close outside ORB hi/lo.  More precise than full-session H/L.
    """
    trades = []
    state  = {s: dict(id=None, hi=0.0, lo=1e9, n=0, hi_done=False, lo_done=False)
              for s in SESSIONS}

    for i, bar in enumerate(bars):
        h = _hour(bar["epoch"])
        d = _date(bar["epoch"])

        for sess, (h1, h2) in SESSIONS.items():
            if not (h1 <= h < h2):
                continue

            sid = f"{d}_{sess}"
            st  = state[sess]

            if sid != st["id"]:
                st.update(id=sid, hi=bar["high"], lo=bar["low"],
                          n=1, hi_done=False, lo_done=False)
                continue

            st["n"] += 1

            if st["n"] <= orb_bars:              # still building ORB
                if bar["high"] > st["hi"]: st["hi"] = bar["high"]
                if bar["low"]  < st["lo"]: st["lo"] = bar["low"]
                continue

            # ORB set — check for breakout
            if not st["hi_done"] and bar["close"] > st["hi"]:
                e = bar["close"]
                t = Trade("ORB", "BUY", sess, e,
                          st["lo"] - sl*pt*0.3, e + tp*pt,
                          bar["epoch"], _dow(bar["epoch"]), h)
                _simulate(t, bars, i)
                trades.append(t)
                st["hi_done"] = True

            if not st["lo_done"] and bar["close"] < st["lo"]:
                e = bar["close"]
                t = Trade("ORB", "SELL", sess, e,
                          st["hi"] + sl*pt*0.3, e - tp*pt,
                          bar["epoch"], _dow(bar["epoch"]), h)
                _simulate(t, bars, i)
                trades.append(t)
                st["lo_done"] = True

    return trades


# ─────────────────────────────────────────────────────────────────────────────
# PATTERN 5 — CONSOLIDATION SQUEEZE BREAKOUT
# ─────────────────────────────────────────────────────────────────────────────

def scan_consolidation_break(bars, tp, sl, pt, squeeze_n=8, max_range_atr=0.45):
    """
    Tight consolidation (squeeze) followed by explosive breakout.
    V75 compresses range before its big algorithmic moves — this pattern
    captures those breakouts early.
    squeeze_n   : number of bars defining the squeeze
    max_range_atr: max squeeze height as a fraction of ATR14
    """
    trades   = []
    used     = set()

    for i in range(squeeze_n, len(bars) - 1):
        chunk = bars[i - squeeze_n + 1: i + 1]
        hi    = max(b["high"] for b in chunk)
        lo    = min(b["low"]  for b in chunk)
        rng   = hi - lo
        atr_v = _atr(bars, i)
        if atr_v <= 0 or rng > max_range_atr * atr_v:
            continue

        next_bar = bars[i + 1]
        key      = bars[i]["epoch"]
        if key in used:
            continue

        h   = _hour(next_bar["epoch"])
        dow = _dow(next_bar["epoch"])

        if next_bar["close"] > hi:
            e = next_bar["close"]
            t = Trade("SQUEEZE", "BUY", "ANY", e,
                      lo - sl*pt, e + tp*pt,
                      next_bar["epoch"], dow, h)
            _simulate(t, bars, i + 1)
            trades.append(t)
            used.add(key)

        elif next_bar["close"] < lo:
            e = next_bar["close"]
            t = Trade("SQUEEZE", "SELL", "ANY", e,
                      hi + sl*pt, e - tp*pt,
                      next_bar["epoch"], dow, h)
            _simulate(t, bars, i + 1)
            trades.append(t)
            used.add(key)

    return trades


# ─────────────────────────────────────────────────────────────────────────────
# PATTERN 6 — PREVIOUS SESSION LEVEL RUN
# ─────────────────────────────────────────────────────────────────────────────

def scan_prev_session_run(bars, tp, sl, pt):
    """
    Previous Session Level Run:
    Institutional algos frequently drive price toward the prior session's H/L
    to collect resting liquidity.  Enter when price tags a prior-session level
    with momentum (close within 2 ticks).
    """
    trades   = []
    prev_hl  = {}   # sess → {hi, lo, date}
    cur_hl   = {}   # sess → {hi, lo, date, n}
    fired    = set()

    for i, bar in enumerate(bars):
        h   = _hour(bar["epoch"])
        d   = _date(bar["epoch"])
        dow = _dow(bar["epoch"])

        for sess, (h1, h2) in SESSIONS.items():
            # Update current session H/L
            if h1 <= h < h2:
                if sess not in cur_hl or cur_hl[sess].get("date") != d:
                    if sess in cur_hl and cur_hl[sess].get("n", 0) >= 12:
                        prev_hl[sess] = dict(hi=cur_hl[sess]["hi"],
                                             lo=cur_hl[sess]["lo"],
                                             date=cur_hl[sess]["date"])
                    cur_hl[sess] = dict(date=d, hi=bar["high"],
                                        lo=bar["low"], n=1)
                else:
                    c = cur_hl[sess]
                    if bar["high"] > c["hi"]: c["hi"] = bar["high"]
                    if bar["low"]  < c["lo"]: c["lo"] = bar["low"]
                    c["n"] += 1

            # Check if price is running into a previous session level
            if sess not in prev_hl:
                continue
            ps = prev_hl[sess]
            if ps.get("date") == d:
                continue   # same-day previous session — skip

            # Tolerance: 0.15 × ATR is the "reaction zone" around prev level
            atr_v  = _atr(bars, i)
            tol    = max(2 * pt, 0.15 * atr_v)
            key_hi = (d, sess, "HI")
            key_lo = (d, sess, "LO")

            # Tag of prev session HIGH → continuation BUY
            if key_hi not in fired and abs(bar["close"] - ps["hi"]) <= tol:
                e = bar["close"]
                t = Trade("PREV_SESS_RUN", "BUY", sess, e,
                          e - sl*pt, e + tp*pt,
                          bar["epoch"], dow, h)
                _simulate(t, bars, i)
                trades.append(t)
                fired.add(key_hi)

            # Tag of prev session LOW → continuation SELL
            if key_lo not in fired and abs(bar["close"] - ps["lo"]) <= tol:
                e = bar["close"]
                t = Trade("PREV_SESS_RUN", "SELL", sess, e,
                          e + sl*pt, e - tp*pt,
                          bar["epoch"], dow, h)
                _simulate(t, bars, i)
                trades.append(t)
                fired.add(key_lo)

    return trades


# ─────────────────────────────────────────────────────────────────────────────
# PATTERN 7 — OPENING + CLOSING CANDLE BREAKOUT  (the user's actual strategy)
# ─────────────────────────────────────────────────────────────────────────────

def scan_oc_candle_break(bars, tp, sl, pt, sl_mode="candle"):
    """
    Opening + Closing Candle Breakout — your actual strategy.

    For each session, mark TWO 5-min candles:
      - OPENING candle  : first M5 when the session opens (h1:00-h1:05 UTC)
      - CLOSING candle  : first M5 AFTER the session closes (h2:00-h2:05 UTC)

    Each candle's H and L become breakout levels valid for the next 24 hours.

    Entry : any subsequent M5 close ABOVE the H or BELOW the L
    SL    : sl_mode="candle" → breakout candle's opposite extreme (variable)
            sl_mode="fixed"  → fixed sl ticks from entry (locks R:R)
            sl_mode="tight"  → MIN of breakout candle extreme and fixed sl
    TP    : fixed tp ticks (default 75)

    Note: Asian-close (08:00-08:05) is the SAME candle as London-open,
    so that bar fires double weight institutionally — we still treat them
    as two separate levels for stat-tracking purposes.
    """
    trades = []

    # Each level: dict(price, side, kind, session, created, expires, used)
    levels = []

    for i, bar in enumerate(bars):
        h     = _hour(bar["epoch"])
        m     = _minute(bar["epoch"])
        d     = _date(bar["epoch"])
        dow   = _dow(bar["epoch"])
        epoch = bar["epoch"]

        # 1. Detect if this bar is any session's open or close candle
        for sess, (h1, h2) in SESSIONS.items():
            close_h = h2 % 24

            if m == 0 and h == h1:                           # OPEN candle
                exp = epoch + 24 * 3600
                levels.append(dict(price=bar["high"], side="HI",
                                   kind="OPEN", session=sess,
                                   created=epoch, expires=exp, used=False))
                levels.append(dict(price=bar["low"], side="LO",
                                   kind="OPEN", session=sess,
                                   created=epoch, expires=exp, used=False))

            if m == 0 and h == close_h:                     # CLOSE candle
                exp = epoch + 24 * 3600
                levels.append(dict(price=bar["high"], side="HI",
                                   kind="CLOSE", session=sess,
                                   created=epoch, expires=exp, used=False))
                levels.append(dict(price=bar["low"], side="LO",
                                   kind="CLOSE", session=sess,
                                   created=epoch, expires=exp, used=False))

        # 2. Check breakouts on every active level
        for lvl in levels:
            if lvl["used"]:
                continue
            if epoch <= lvl["created"]:           # don't trade defining bar
                continue
            if epoch > lvl["expires"]:
                lvl["used"] = True
                continue

            # Bullish break of HI
            if lvl["side"] == "HI" and bar["close"] > lvl["price"]:
                e = bar["close"]
                if sl_mode == "fixed":
                    sl_p = e - sl * pt
                elif sl_mode == "tight":
                    sl_p = max(bar["low"] - 2 * pt, e - sl * pt)   # whichever is closer to entry
                else:
                    sl_p = bar["low"] - 2 * pt
                ptn = f"OC_{lvl['kind']}"
                t   = Trade(ptn, "BUY", lvl["session"], e, sl_p,
                            e + tp * pt, epoch, dow, h)
                _simulate(t, bars, i)
                trades.append(t)
                lvl["used"] = True

            # Bearish break of LO
            elif lvl["side"] == "LO" and bar["close"] < lvl["price"]:
                e = bar["close"]
                if sl_mode == "fixed":
                    sl_p = e + sl * pt
                elif sl_mode == "tight":
                    sl_p = min(bar["high"] + 2 * pt, e + sl * pt)  # whichever is closer to entry
                else:
                    sl_p = bar["high"] + 2 * pt
                ptn = f"OC_{lvl['kind']}"
                t   = Trade(ptn, "SELL", lvl["session"], e, sl_p,
                            e - tp * pt, epoch, dow, h)
                _simulate(t, bars, i)
                trades.append(t)
                lvl["used"] = True

        # 3. Prune memory occasionally
        if i % 200 == 0 and len(levels) > 500:
            levels = [l for l in levels if not l["used"]]

    return trades


# ─────────────────────────────────────────────────────────────────────────────
# PATTERN 9 / 10 — OC CANDLE BREAKOUT with ICT KILLZONE SESSIONS
#   Session times from the user's "Trading Session ICT KillZone" indicator:
#       Asia   22:00 → 09:00  (UTC, overnight)
#       London 07:00 → 16:00
#       NY     13:00 → 22:00
#   Trigger:  "m5" = enter on first M5 close past level   (Pattern 9)
#             "h1" = enter only when an H1 candle closes past level  (Pattern 10)
# ─────────────────────────────────────────────────────────────────────────────

SESSIONS_ICT = {
    "ASIAN":  (22, 9),
    "LONDON": (7,  16),
    "NY":     (13, 22),
}


def scan_oc_break_ict(bars, tp, sl, pt, trigger="m5"):
    """
    M5 levels from each session's OC + CC candles.
    Entry trigger configurable: M5 close OR H1 close.
    Fixed SL/TP (matches Pattern 7B parameters).
    """
    trades = []
    levels = []

    for i, bar in enumerate(bars):
        h     = _hour(bar["epoch"])
        m     = _minute(bar["epoch"])
        d     = _date(bar["epoch"])
        dow   = _dow(bar["epoch"])
        epoch = bar["epoch"]

        # 1. Detect OC + CC candles (minute 0 of session open/close hour)
        for sess, (h1, h2) in SESSIONS_ICT.items():
            close_h = h2 % 24

            if m == 0 and h == h1:                          # OPEN candle
                exp = epoch + 24 * 3600
                levels.append(dict(price=bar["high"], side="HI",
                                   kind="OPEN", session=sess,
                                   created=epoch, expires=exp, used=False))
                levels.append(dict(price=bar["low"], side="LO",
                                   kind="OPEN", session=sess,
                                   created=epoch, expires=exp, used=False))

            if m == 0 and h == close_h:                     # CLOSE candle
                exp = epoch + 24 * 3600
                levels.append(dict(price=bar["high"], side="HI",
                                   kind="CLOSE", session=sess,
                                   created=epoch, expires=exp, used=False))
                levels.append(dict(price=bar["low"], side="LO",
                                   kind="CLOSE", session=sess,
                                   created=epoch, expires=exp, used=False))

        # 2. Trigger gate — H1 trigger only fires on M5 bars that complete
        #    an H1 candle (minute == 55, so this bar's close = H1 close)
        if trigger == "h1" and m != 55:
            continue

        # 3. Check breakouts on every active level
        for lvl in levels:
            if lvl["used"]:                       continue
            if epoch <= lvl["created"]:           continue
            if epoch > lvl["expires"]:
                lvl["used"] = True
                continue

            ptag = f"OC_ICT_{trigger.upper()}_{lvl['kind']}"

            # Bullish break of HI
            if lvl["side"] == "HI" and bar["close"] > lvl["price"]:
                e   = bar["close"]
                slp = e - sl * pt
                t   = Trade(ptag, "BUY", lvl["session"], e, slp,
                            e + tp * pt, epoch, dow, h)
                _simulate(t, bars, i)
                trades.append(t)
                lvl["used"] = True

            # Bearish break of LO
            elif lvl["side"] == "LO" and bar["close"] < lvl["price"]:
                e   = bar["close"]
                slp = e + sl * pt
                t   = Trade(ptag, "SELL", lvl["session"], e, slp,
                            e - tp * pt, epoch, dow, h)
                _simulate(t, bars, i)
                trades.append(t)
                lvl["used"] = True

        # Memory hygiene
        if i % 200 == 0 and len(levels) > 500:
            levels = [l for l in levels if not l["used"]]

    return trades


# ─────────────────────────────────────────────────────────────────────────────
# PATTERN 8 — OPEN+CLOSE CANDLE BOX FLIP  (the new strategy)
# ─────────────────────────────────────────────────────────────────────────────

def scan_oc_candle_flip(bars, tp, pt, hard_sl_mult=1.0):
    """
    'Box Flip with Hard SL' — each OC/CC candle defines a box (H, L).

    Per trade, four ways to exit (whichever fires first):
      1. WIN       — TP hit intra-bar (price reaches entry ± tp ticks)
      2. HARD_SL   — intra-bar wick past the hard SL
                       hard SL = box wall + (hard_sl_mult × box_height)
                       (above box.HIGH for SELL, below box.LOW for BUY)
      3. FLIP_LOSS — bar CLOSE past the opposite box wall
                       → close current trade and immediately open the opposite
      4. EXPIRED   — 24-hour box lifetime ended

    Box stays alive for 24h and can be re-entered many times.
    TP = fixed `tp` ticks. Risk reference (Trade.sl) = the HARD SL.
    """
    trades = []
    boxes  = []
    buf    = 2 * pt

    def open_pos(box, direction, bar, dow, h):
        e = bar["close"]
        box_height = box["high"] - box["low"]
        hard_offset = max(box_height * hard_sl_mult, 0) + buf
        if direction == "BUY":
            hard_sl = box["low"]  - hard_offset
            tp_p    = e + tp * pt
        else:
            hard_sl = box["high"] + hard_offset
            tp_p    = e - tp * pt

        t = Trade("OC_FLIP_" + box["kind"], direction, box["session"],
                  e, hard_sl, tp_p, bar["epoch"], dow, h)
        box["pos"]   = direction
        box["trade"] = t
        trades.append(t)

    def close_pos(box, outcome, exit_price, bars_held):
        t = box["trade"]
        if t is None: return
        t.outcome    = outcome
        t.exit_price = exit_price
        t.bars_held  = bars_held
        risk = abs(t.entry - t.sl)
        if risk <= 0:
            t.r_multiple = 0
        elif outcome == "WIN":
            t.r_multiple = abs(exit_price - t.entry) / risk
        elif outcome == "HARD_SL":
            t.r_multiple = -1.0
        else:  # FLIP_LOSS or EXPIRED — partial loss based on actual move
            move = (t.entry - exit_price) if t.direction == "SELL" \
                                          else (exit_price - t.entry)
            t.r_multiple = move / risk
        # Map non-standard outcomes to LOSS so _stats counts them
        if outcome in ("HARD_SL", "FLIP_LOSS"):
            t.outcome = "LOSS"
        box["pos"]   = None
        box["trade"] = None

    for i, bar in enumerate(bars):
        h     = _hour(bar["epoch"])
        m     = _minute(bar["epoch"])
        dow   = _dow(bar["epoch"])
        epoch = bar["epoch"]

        # 1. Create new boxes when on an OC or CC candle
        for sess, (h1, h2) in SESSIONS.items():
            close_h = h2 % 24
            if m == 0 and h == h1:
                boxes.append({"high": bar["high"], "low": bar["low"],
                              "kind": "OPEN",  "session": sess,
                              "created": epoch, "expires": epoch + 24 * 3600,
                              "open_idx": i, "pos": None, "trade": None})
            if m == 0 and h == close_h:
                boxes.append({"high": bar["high"], "low": bar["low"],
                              "kind": "CLOSE", "session": sess,
                              "created": epoch, "expires": epoch + 24 * 3600,
                              "open_idx": i, "pos": None, "trade": None})

        # 2. Process active boxes
        kept = []
        for box in boxes:
            if epoch > box["expires"]:
                if box["pos"]:
                    close_pos(box, "EXPIRED", bar["close"], i - box["open_idx"])
                continue

            if epoch <= box["created"]:
                kept.append(box)
                continue

            broke_high = bar["close"] > box["high"] + buf
            broke_low  = bar["close"] < box["low"]  - buf

            # ── Intra-bar exits for any open position ──
            if box["pos"] == "BUY":
                t = box["trade"]
                # Hard SL first (worst-case path)
                if bar["low"] <= t.sl:
                    close_pos(box, "HARD_SL", t.sl, i - box["open_idx"])
                elif bar["high"] >= t.tp:
                    close_pos(box, "WIN", t.tp, i - box["open_idx"])
            elif box["pos"] == "SELL":
                t = box["trade"]
                if bar["high"] >= t.sl:
                    close_pos(box, "HARD_SL", t.sl, i - box["open_idx"])
                elif bar["low"] <= t.tp:
                    close_pos(box, "WIN", t.tp, i - box["open_idx"])

            # ── Bar-close state transitions ──
            if box["pos"] is None:
                if broke_high:
                    open_pos(box, "BUY",  bar, dow, h)
                elif broke_low:
                    open_pos(box, "SELL", bar, dow, h)
            elif box["pos"] == "BUY" and broke_low:
                close_pos(box, "FLIP_LOSS", bar["close"], i - box["open_idx"])
                open_pos(box, "SELL", bar, dow, h)
            elif box["pos"] == "SELL" and broke_high:
                close_pos(box, "FLIP_LOSS", bar["close"], i - box["open_idx"])
                open_pos(box, "BUY", bar, dow, h)

            kept.append(box)

        boxes = kept

    # End: close any open positions at last bar
    last_bar = bars[-1]
    for box in boxes:
        if box["pos"]:
            close_pos(box, "EXPIRED", last_bar["close"], len(bars) - box["open_idx"])

    return trades


# ─────────────────────────────────────────────────────────────────────────────
# $-FRAME R-MULTIPLE POST-PROCESSOR
# ─────────────────────────────────────────────────────────────────────────────

def recompute_r_multiple_dollar(trades, configured_tp_ticks, spread_ticks,
                                slippage_ticks, pt):
    """Overwrite each trade's r_multiple so it reflects $-frame R-multiple,
    where 1R = the actual broker loss in ticks for that specific trade.

    The simulator detects WIN/LOSS correctly using bid-frame distances, but
    its native reward/risk ratio is *not* the dollars-out-of-account ratio
    the trader actually experiences. The trader's real loss on SL trigger is
    (entry_ask − bid_at_SL) = sim_sl_distance + spread + slippage ticks.
    The real profit on TP trigger is configured_tp ticks.

    Pattern 8 (OC_FLIP) has its own multi-outcome accounting and is skipped
    by callers (don't pass its trades here).
    """
    for t in trades:
        if t.outcome == "WIN":
            sim_sl_ticks      = abs(t.entry - t.sl) / pt
            actual_loss_ticks = sim_sl_ticks + spread_ticks + slippage_ticks
            if actual_loss_ticks > 0:
                t.r_multiple = configured_tp_ticks / actual_loss_ticks
        elif t.outcome == "LOSS":
            t.r_multiple = -1.0


# ─────────────────────────────────────────────────────────────────────────────
# STATISTICS ENGINE
# ─────────────────────────────────────────────────────────────────────────────

def _wr_str(tlist):
    c = [t for t in tlist if t.outcome in ("WIN", "LOSS")]
    if not c:
        return "    —    "
    w = sum(1 for t in c if t.outcome == "WIN")
    return f"{w/len(c)*100:5.1f}%  ({w}/{len(c)})"


def _stats(trades):
    done = [t for t in trades if t.outcome in ("WIN", "LOSS")]
    if not done:
        return None
    wins   = [t for t in done if t.outcome == "WIN"]
    losses = [t for t in done if t.outcome == "LOSS"]
    wr     = len(wins) / len(done)
    avg_rw = (sum(t.r_multiple for t in wins) / len(wins)) if wins else 0.0
    exp    = wr * avg_rw - (1 - wr) * 1.0
    avg_bh = sum(t.bars_held for t in done) / len(done)

    by_sess  = defaultdict(list)
    by_dow   = defaultdict(list)
    by_hour  = defaultdict(list)
    by_month = defaultdict(list)

    for t in done:
        by_sess[t.session].append(t)
        by_dow[t.dow].append(t)
        by_hour[t.hour].append(t)
        by_month[_month(t.entry_epoch)].append(t)

    return dict(
        n=len(done), wins=len(wins), losses=len(losses),
        open_cnt=len([t for t in trades if t.outcome == "OPEN"]),
        wr=wr, avg_rw=avg_rw, exp=exp, avg_bh=avg_bh,
        by_sess=by_sess, by_dow=by_dow, by_hour=by_hour, by_month=by_month,
    )


def print_report(title, trades):
    s = _stats(trades)
    if not s:
        print(f"\n  {title}: no completed trades.\n")
        return

    sep = "═" * 66
    print(f"\n{sep}")
    print(f"  {title}")
    print(sep)
    print(f"  Completed : {s['n']:4d}   Wins: {s['wins']}   Losses: {s['losses']}   "
          f"Still open: {s['open_cnt']}")
    print(f"  Win rate  : {s['wr']*100:5.1f}%")
    print(f"  Avg R/win : {s['avg_rw']:.2f}R")
    print(f"  Expectancy: {s['exp']:+.3f}R per trade  "
          f"({'POSITIVE ✓' if s['exp'] > 0 else 'NEGATIVE ✗'})")
    print(f"  Avg hold  : {s['avg_bh']:.1f} bars  ({s['avg_bh']*5:.0f} min)")

    # By session
    print(f"\n  ┌─ By Session ─────────────────────────────────┐")
    for sess in ["ASIAN", "LONDON", "NY", "ANY"]:
        tl = s["by_sess"].get(sess)
        if tl:
            print(f"  │  {sess:<8}  {_wr_str(tl)}")
    print(f"  └──────────────────────────────────────────────┘")

    # By direction
    buys  = [t for t in trades if t.direction == "BUY"]
    sells = [t for t in trades if t.direction == "SELL"]
    print(f"\n  ┌─ By Direction ───────────────────────────────┐")
    print(f"  │  BUY    {_wr_str(buys)}")
    print(f"  │  SELL   {_wr_str(sells)}")
    print(f"  └──────────────────────────────────────────────┘")

    # Pattern-7 specific: OC_OPEN vs OC_CLOSE
    open_trades  = [t for t in trades if t.pattern == "OC_OPEN"]
    close_trades = [t for t in trades if t.pattern == "OC_CLOSE"]
    if open_trades or close_trades:
        print(f"\n  ┌─ OPEN vs CLOSE candle ───────────────────────┐")
        print(f"  │  OPEN  candle  {_wr_str(open_trades)}")
        print(f"  │  CLOSE candle  {_wr_str(close_trades)}")
        print(f"  └──────────────────────────────────────────────┘")

    # By day of week
    print(f"\n  ┌─ By Day of Week ─────────────────────────────┐")
    for d in range(7):
        tl = s["by_dow"].get(d)
        if tl:
            print(f"  │  {DAYS_SHORT[d]}     {_wr_str(tl)}")
    print(f"  └──────────────────────────────────────────────┘")

    # Best hours (min 5 trades)
    print(f"\n  ┌─ Best Hours UTC (min 5 trades) ─────────────┐")
    hour_rows = []
    for h, tl in sorted(s["by_hour"].items()):
        c = [t for t in tl if t.outcome in ("WIN","LOSS")]
        if len(c) >= 5:
            wr = sum(1 for t in c if t.outcome=="WIN") / len(c)
            hour_rows.append((h, wr, len(c)))
    for h, wr, n in sorted(hour_rows, key=lambda x: x[1], reverse=True)[:8]:
        bar_v = "█" * int(wr * 10)
        print(f"  │  {h:02d}:00  {wr*100:5.1f}%  {bar_v:<10}  n={n}")
    print(f"  └──────────────────────────────────────────────┘")

    # Monthly
    print(f"\n  ┌─ Monthly breakdown ─────────────────────────┐")
    for mo, tl in sorted(s["by_month"].items()):
        c = [t for t in tl if t.outcome in ("WIN","LOSS")]
        if not c:
            continue
        wr   = sum(1 for t in c if t.outcome=="WIN") / len(c)
        netr = sum(t.r_multiple for t in c)
        bar_v = "▓" * int(wr * 10)
        print(f"  │  {mo}  {wr*100:5.1f}%  {bar_v:<10}  "
              f"Net R: {netr:+6.2f}  n={len(c)}")
    print(f"  └──────────────────────────────────────────────┘")


# ─────────────────────────────────────────────────────────────────────────────
# CSV EXPORT
# ─────────────────────────────────────────────────────────────────────────────

def export_csv(all_trades, path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pattern","direction","session","entry","sl","tp",
                    "outcome","r_multiple","bars_held","dow","hour",
                    "date","month","epoch"])
        for t in all_trades:
            if t.outcome in ("WIN","LOSS","OPEN"):
                w.writerow([
                    t.pattern, t.direction, t.session,
                    round(t.entry, 5), round(t.sl, 5), round(t.tp, 5),
                    t.outcome,
                    round(t.r_multiple, 3) if t.r_multiple is not None else "",
                    t.bars_held,
                    DAYS_SHORT[t.dow], t.hour,
                    _date(t.entry_epoch), _month(t.entry_epoch),
                    t.entry_epoch,
                ])
    print(f"\n  All trades exported → {path}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

async def run(args):
    # ── Resolve broker config (auto-load preset if user didn't override) ──
    spread      = args.spread
    slippage    = args.slippage
    stops_level = args.stops_level

    auto_loaded = False
    if args.symbol in BROKER_PRESETS and spread == 0 and stops_level == 0:
        preset      = BROKER_PRESETS[args.symbol]
        spread      = preset["spread"]
        stops_level = preset["stops_level"]
        # Only override point if user left it at the argparse default (0.01)
        if args.point == 0.01:
            args.point = preset["point"]
        auto_loaded = True

    # ── Loud warning if running with no broker friction ──
    if spread == 0 and stops_level == 0:
        print("\n" + "!" * 70)
        print("!" + " " * 68 + "!")
        print("!  WARNING: spread=0 and stops_level=0                              !")
        print("!  Results will be IDEALISED — do NOT use for deployment decisions  !")
        print("!  Pass --spread N --stops-level N or use a recognised symbol       !")
        print("!" + " " * 68 + "!")
        print("!" * 70 + "\n")

    # ── Compute the broker model ──
    configured_sl = args.sl
    configured_tp = args.tp
    pt            = args.point

    # Broker forces SL distance to at least stops_level + 2*spread + safety,
    # mirroring the EA's min_dist clamp. This is the ACTUAL ticks of loss per
    # SL trigger.
    broker_sl = max(configured_sl, stops_level + 2 * spread + 10)

    # Simulator-frame distances (bid-frame movement required from bar.close):
    #   - BUY entry at ASK = bid + spread + slippage_adverse
    #   - SL price = ASK - broker_sl  → bid-move-down = broker_sl - spread - slippage
    #   - TP price = ASK + configured_tp → bid-move-up = configured_tp + spread + slippage
    sim_sl_dist = max(1, broker_sl - spread - slippage)
    sim_tp_dist = configured_tp + spread + slippage

    # $-frame R:R on a winning trade (loss is always -1R = broker_sl ticks)
    dollar_rr = configured_tp / broker_sl if broker_sl > 0 else 0

    preset_tag = "  (auto-loaded preset)" if auto_loaded else ""
    print(f"""
+---------------------------------------------------------------------+
|  ICT Pattern Scanner — BROKER-REALISTIC SIM{preset_tag:<25}
+---------------------------------------------------------------------+
|  Symbol         : {args.symbol:<12}     History       : {args.years:.1f} year(s)
|  Configured SL  : {configured_sl:<6} ticks    Configured TP : {configured_tp:<6} ticks
|  Spread         : {spread:<6} ticks    Stops level   : {stops_level:<6} ticks
|  Slippage       : {slippage:<6} ticks    Point         : {pt}
|  ────────────────────────────────────────────────────────────────── |
|  Broker SL      : {broker_sl:<6} ticks    (actual ticks lost per stop)
|  Sim SL dist    : {sim_sl_dist:<6} ticks    Sim TP dist   : {sim_tp_dist:<6} ticks
|  $ R:R          : {dollar_rr:.3f}             1R = {broker_sl} ticks (broker fill)
+---------------------------------------------------------------------+""")

    bars = await fetch_history(args.symbol, args.years)
    if len(bars) < 500:
        print("Not enough data returned.  Check your connection and symbol.")
        return

    # The pattern functions take (tp, sl) as ticks. Pass simulator-frame
    # distances so trigger checks reflect bid-frame reality.
    eff_sl = sim_sl_dist
    eff_tp = sim_tp_dist

    # Aliases retained for old code paths inside the function
    tp = configured_tp
    sl = configured_sl

    print("Running pattern scans…\n")

    patterns = [
        ("1. SESSION H/L BREAKOUT",              scan_session_breakout(bars, eff_tp, eff_sl, pt)),
        ("2. LONDON BREAKOUT OF ASIAN RANGE",     scan_london_asian_break(bars, eff_tp, eff_sl, pt)),
        ("3. NY OPEN REVERSAL  (Judas Swing)",    scan_ny_reversal(bars, eff_tp, eff_sl, pt)),
        ("4. OPENING RANGE BREAKOUT  (30-min)",   scan_orb(bars, eff_tp, eff_sl, pt)),
        ("5. CONSOLIDATION SQUEEZE BREAKOUT",     scan_consolidation_break(bars, eff_tp, eff_sl, pt)),
        ("6. PREVIOUS SESSION LEVEL RUN",         scan_prev_session_run(bars, eff_tp, eff_sl, pt)),
        ("7A. OPEN+CLOSE CANDLE — SL=candle extreme",
                                                  scan_oc_candle_break(bars, eff_tp, eff_sl, pt, "candle")),
        ("7B. OPEN+CLOSE CANDLE — SL=fixed ticks",
                                                  scan_oc_candle_break(bars, eff_tp, eff_sl, pt, "fixed")),
        ("7C. OPEN+CLOSE CANDLE — SL=tighter of (candle, fixed)",
                                                  scan_oc_candle_break(bars, eff_tp, eff_sl, pt, "tight")),
        (f"8.  OC BOX FLIP — close-flip + hard SL (mult={args.hard_sl_mult})",
                                                  scan_oc_candle_flip(bars, eff_tp, pt, args.hard_sl_mult)),
        ("9.  OC + ICT SESSIONS, M5 trigger, fixed SL",
                                                  scan_oc_break_ict(bars, eff_tp, eff_sl, pt, "m5")),
        ("10. OC + ICT SESSIONS, H1 trigger, fixed SL",
                                                  scan_oc_break_ict(bars, eff_tp, eff_sl, pt, "h1")),
    ]

    for name, plist in patterns:
        done = sum(1 for t in plist if t.outcome in ("WIN","LOSS"))
        print(f"  {name:<44}  {len(plist):4d} signals  "
              f"({done} completed)")

    # ── Post-process r_multiple to $-frame for everything except Pattern 8 ──
    # Pattern 8 (OC_FLIP) has multi-outcome accounting (HARD_SL/FLIP_LOSS/EXPIRED)
    # done inline in close_pos(); leave its r_multiple alone.
    print(f"\n[$-frame remap] 1R = {broker_sl} ticks, win = +{dollar_rr:.3f}R "
          f"(for fixed-SL patterns; variable SL = per-trade calc)")
    for name, plist in patterns:
        if "BOX FLIP" in name:
            continue
        recompute_r_multiple_dollar(plist, configured_tp, spread, slippage, pt)

    # ── Detailed reports ─────────────────────────────────────────
    for name, plist in patterns:
        print_report(name, plist)

    # ── Summary table ─────────────────────────────────────────────
    print(f"\n{'═'*66}")
    print(f"  COMBINED SUMMARY — ALL 6 PATTERNS")
    print(f"{'═'*66}")
    print(f"  {'Pattern':<34}  {'N':>5}  {'Win%':>6}  {'Exp R':>7}")
    print(f"  {'─'*34}  {'─'*5}  {'─'*6}  {'─'*7}")

    all_trades = []
    for name, plist in patterns:
        all_trades.extend(plist)
        c = [t for t in plist if t.outcome in ("WIN","LOSS")]
        if not c:
            continue
        wr  = sum(1 for t in c if t.outcome=="WIN") / len(c)
        wrw = sum(t.r_multiple for t in c if t.outcome=="WIN")
        nw  = sum(1 for t in c if t.outcome=="WIN")
        arw = wrw / nw if nw else 0
        exp = wr * arw - (1 - wr)
        flag = " ✓" if exp > 0.05 else ("  " if exp >= 0 else " ✗")
        short = name.split(".")[-1].strip()[:34]
        print(f"  {short:<34}  {len(c):>5}  {wr*100:>5.1f}%  {exp:>+6.3f}R{flag}")

    print()
    export_csv(all_trades, args.csv)
    print("\nDone.\n")


def main():
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="ICT Session Breakout Pattern Scanner")
    ap.add_argument("--symbol", default="R_75",  help="Deriv symbol  (default: R_75)")
    ap.add_argument("--years",  default=1.0, type=float, help="Years of history  (default: 1)")
    ap.add_argument("--tp",     default=75,  type=int,   help="TP in ticks  (default: 75)")
    ap.add_argument("--sl",     default=40,  type=int,   help="SL in ticks  (default: 40)")
    ap.add_argument("--point",  default=0.01, type=float, help="Tick size  (default: 0.01)")
    ap.add_argument("--hard-sl-mult", dest="hard_sl_mult", default=1.0, type=float,
                    help="Pattern 8 hard-SL distance in BOX HEIGHTS beyond box wall  (default: 1.0)")
    ap.add_argument("--spread",      default=0,   type=int,
                    help="Broker spread in ticks  (default: 0; auto-loaded for known symbols)")
    ap.add_argument("--stops-level", dest="stops_level", default=0, type=int,
                    help="Broker stops_level in ticks  (default: 0; auto-loaded for known symbols)")
    ap.add_argument("--slippage",    default=2,   type=int,
                    help="Entry slippage in ticks (adverse fill beyond spread)  (default: 2)")
    ap.add_argument("--csv",    default="scanner_results.csv", help="CSV output path")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
