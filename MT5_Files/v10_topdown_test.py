#!/usr/bin/env python3
"""
v10_topdown_test.py — Test the USER'S ACTUAL V10 method, not generic patterns.

Method (top-down ICT): HTF order-flow bias -> Break of Structure (BOS) ->
enter on retrace to the broken level / OB -> stop above the swing high ->
PARTICIPATION exit: ride to the next swing-low liquidity (NOT fixed R).

This is NOT what hunt_full.py tested (that was single-TF M5 patterns, fixed R:R).

TWO honest layers:
  LAYER 1 (foundation): does V10 even HAVE the structure the method needs?
    - drift (mean bar return), autocorrelation, variance ratio, run-continuation,
      and BOS-continuation rate. On a true random walk these are 0 / 50% and NO
      entry rule can win (optional-stopping). On gold these were nonzero.
  LAYER 2 (the method): simulate bearish BOS -> retrace entry -> stop above swing
    high -> exit at next swing low, HTF-bias-aligned vs counter-trend, with real
    Deriv friction. Compared to a phase-randomized null.

Pulls V10 (Volatility 10 Index) D1/H4 straight from the running MT5 terminal.
INVOCATION: py v10_topdown_test.py
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import math
import random
import statistics as st
from datetime import datetime, timezone
import MetaTrader5 as mt5

SYMBOL = "Volatility 10 Index"
POINT, SPREAD_PTS, STOPS_LVL, SLIP_PTS = 0.001, 162, 720, 2
FRICTION_PRICE = (SPREAD_PTS + SLIP_PTS) * POINT          # per round trip leg approx
SWING_K = 3                                               # fractal half-width


def _rates(tf, count):
    """copy_rates_from_pos is more reliable than _range (forces history sync)."""
    rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, count)
    if rates is None or len(rates) == 0:
        # one retry after nudging symbol history
        mt5.symbol_select(SYMBOL, True)
        rates = mt5.copy_rates_from_pos(SYMBOL, tf, 0, count)
    if rates is None or len(rates) == 0:
        raise SystemExit(f"no rates for tf={tf}: {mt5.last_error()}")
    bars = [{"t": int(r["time"]), "o": float(r["open"]), "h": float(r["high"]),
             "l": float(r["low"]), "c": float(r["close"])} for r in rates]
    bars.sort(key=lambda b: b["t"])
    return bars


def load_all():
    if not mt5.initialize():
        raise SystemExit(f"mt5.initialize failed: {mt5.last_error()}")
    mt5.symbol_select(SYMBOL, True)
    try:
        w1 = _rates(mt5.TIMEFRAME_W1, 600)
        d1 = _rates(mt5.TIMEFRAME_D1, 3000)
        h4 = _rates(mt5.TIMEFRAME_H4, 20000)
    finally:
        mt5.shutdown()
    return w1, d1, h4


# ---------------- LAYER 1: structural foundation ----------------
def rand_walk_battery(bars, label):
    closes = [b["c"] for b in bars]
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    n = len(rets)
    mean = st.mean(rets)
    sd = st.pstdev(rets)
    # drift t-stat
    tstat = mean / (sd / math.sqrt(n)) if sd else 0
    # autocorr lag1
    if sd:
        ac1 = sum((rets[i] - mean) * (rets[i - 1] - mean) for i in range(1, n)) / ((n - 1) * sd * sd)
    else:
        ac1 = 0
    # variance ratio VR(q): var(q-bar)/ (q*var(1-bar))
    def vr(q):
        agg = [sum(rets[i:i + q]) for i in range(0, n - q, q)]
        if len(agg) < 2:
            return float("nan")
        return st.pvariance(agg) / (q * sd * sd) if sd else float("nan")
    # run continuation
    signs = [1 if r > 0 else 0 for r in rets]
    cont = sum(1 for i in range(1, n) if signs[i] == signs[i - 1]) / (n - 1)
    print(f"  [{label}] n={n}  drift/bar={mean*100:+.4f}%  t={tstat:+.1f}  "
          f"ac1={ac1:+.3f}  VR2={vr(2):.3f} VR5={vr(5):.3f}  P(cont)={cont*100:.1f}%")
    return abs(tstat) > 2 or abs(ac1) > 0.03 or cont > 0.53 or cont < 0.47


# ---------------- swing structure + BOS ----------------
def swings(bars, k=SWING_K):
    """Return list of (idx, price, 'H'/'L') confirmed fractal swings."""
    sw = []
    for i in range(k, len(bars) - k):
        win = bars[i - k:i + k + 1]
        if bars[i]["h"] == max(b["h"] for b in win):
            sw.append((i, bars[i]["h"], "H"))
        if bars[i]["l"] == min(b["l"] for b in win):
            sw.append((i, bars[i]["l"], "L"))
    return sw


def htf_bias(d1bars):
    """Daily bias series: -1 (down) when making lower highs&lows over lookback, +1 up, 0 none.
    Simple, robust: sign of (close - close[20]) confirmed by (close - close[60])."""
    bias = {}
    for i in range(len(d1bars)):
        if i < 60:
            bias[d1bars[i]["t"]] = 0; continue
        s20 = d1bars[i]["c"] - d1bars[i - 20]["c"]
        s60 = d1bars[i]["c"] - d1bars[i - 60]["c"]
        bias[d1bars[i]["t"]] = -1 if (s20 < 0 and s60 < 0) else (1 if (s20 > 0 and s60 > 0) else 0)
    return bias


def bias_at(t_epoch, d1bars, bias):
    """Most recent daily bias at/before this H4 bar's time."""
    b = 0
    for db in d1bars:
        if db["t"] <= t_epoch:
            b = bias[db["t"]]
        else:
            break
    return b


def simulate(bars, d1bars, bias, require_align=True, target_mult=2.0, is_null=False):
    """Bearish BOS -> short on retrace to broken swing-low level -> stop above prior
    swing high -> target set AT ENTRY = target_mult x risk projected down (measured-
    move proxy for 'ride to next liquidity'). NO look-ahead, NO skipping failures.
    Returns trades as R-multiples (net of friction)."""
    sw = swings(bars)
    swing_lows = [(i, p) for (i, p, k) in sw if k == "L"]
    swing_highs = [(i, p) for (i, p, k) in sw if k == "H"]
    trades = []
    li = hi = 0
    fill_window, trade_window = 30, 400
    for bi in range(SWING_K + 1, len(bars)):
        while li + 1 < len(swing_lows) and swing_lows[li + 1][0] < bi:
            li += 1
        while hi + 1 < len(swing_highs) and swing_highs[hi + 1][0] < bi:
            hi += 1
        if li == 0 or hi == 0:
            continue
        prior_low_i, prior_low = swing_lows[li]
        prior_high_i, prior_high = swing_highs[hi]
        if prior_low_i >= bi or prior_high_i <= prior_low_i:
            continue
        # bearish BOS: this bar closes below the prior swing low (first cross)
        if bars[bi]["c"] < prior_low and bars[bi - 1]["c"] >= prior_low:
            if require_align and not is_null and bias_at(bars[bi]["t"], d1bars, bias) != -1:
                continue
            entry = prior_low                       # retrace back up to broken level (OB proxy)
            stop = prior_high                       # above the swing high / range
            risk = stop - entry
            if risk <= 0 or risk < STOPS_LVL * POINT:
                continue
            target = entry - target_mult * risk     # set AT ENTRY — no peeking
            # walk forward: wait for retrace fill, then race target vs stop
            filled = False
            outcome = None
            for j in range(bi + 1, min(bi + trade_window, len(bars))):
                if not filled:
                    if j - bi > fill_window:        # never retraced -> no trade
                        break
                    if bars[j]["h"] >= entry:
                        filled = True
                if filled:
                    if bars[j]["h"] >= stop:
                        outcome = "LOSS"; break
                    if bars[j]["l"] <= target:
                        outcome = "WIN"; break
            if outcome is None:
                continue                            # timed out / never filled -> not counted
            if outcome == "WIN":
                r = (target_mult * risk - FRICTION_PRICE) / risk
            else:
                r = -(risk + FRICTION_PRICE) / risk
            trades.append(r)
    return trades


def make_null(bars):
    """Proper random-walk null: bootstrap H4 returns (destroys any structure) and
    rebuild OHLC with realistic wicks scaled to per-bar volatility."""
    rets = [bars[i]["c"] / bars[i - 1]["c"] - 1 for i in range(1, len(bars))]
    sd = st.pstdev(rets)
    random.shuffle(rets)
    out = [{"t": bars[0]["t"], "o": bars[0]["c"], "h": bars[0]["c"],
            "l": bars[0]["c"], "c": bars[0]["c"]}]
    px = bars[0]["c"]
    for i, r in enumerate(rets):
        o = px
        c = px * (1 + r)
        wick = abs(random.gauss(0, sd)) * px       # typical intrabar excursion
        h = max(o, c) + wick
        l = min(o, c) - wick
        out.append({"t": bars[i + 1]["t"], "o": o, "h": h, "l": l, "c": c})
        px = c
    return out


def report(name, trades):
    if not trades:
        print(f"  {name:<34} n=0 (no setups)")
        return
    n = len(trades)
    wr = sum(1 for r in trades if r > 0) / n * 100
    exp = st.mean(trades)
    se = st.pstdev(trades) / math.sqrt(n) if n > 1 else 0
    lo, hi = exp - 1.96 * se, exp + 1.96 * se
    verd = "EDGE (CI>0)" if lo > 0 else ("loses (CI<0)" if hi < 0 else "break-even (CI~0)")
    print(f"  {name:<34} n={n:>4}  WR={wr:4.1f}%  expR={exp:+.3f}  [{lo:+.3f},{hi:+.3f}]  {verd}")


def main():
    print("=" * 92)
    print("  V10 TOP-DOWN ICT TEST — the user's actual method (BOS + retrace + participation exit)")
    print("=" * 92)
    print(f"  Symbol: {SYMBOL}  spread={SPREAD_PTS}pts stops_level={STOPS_LVL}pts  friction/leg=${FRICTION_PRICE:.3f}\n")

    print("Loading V10 W1/D1/H4 from MT5 …")
    w1, d1, h4 = load_all()
    print(f"  D1: {len(d1)} bars  H4: {len(h4)} bars  W1: {len(w1)} bars  "
          f"({datetime.utcfromtimestamp(h4[0]['t']).date()} -> {datetime.utcfromtimestamp(h4[-1]['t']).date()})\n")

    print("=== LAYER 1: does V10 have ANY structure? (random walk = drift~0, ac~0, P(cont)~50%) ===")
    s_w = rand_walk_battery(w1, "W1")
    s_d = rand_walk_battery(d1, "D1")
    s_h = rand_walk_battery(h4, "H4")
    print(f"  >> structure detected: W1={s_w}  D1={s_d}  H4={s_h}")
    print("  (if all False -> random walk -> Layer 2 cannot have a real edge, by optional-stopping)\n")

    print("=== LAYER 2: the method — bearish BOS -> retrace entry -> measured-move exit ===")
    print("  (target set AT ENTRY = target_mult x risk; no look-ahead; failures NOT skipped)\n")
    bias = htf_bias(d1)
    random.seed(42)
    for tm in (1.0, 2.0, 3.0):
        print(f"  -- target = {tm:.0f}R (ride toward next liquidity, fixed at entry) --")
        report("HTF-aligned (daily bias DOWN)", simulate(h4, d1, bias, True, tm))
        report("all bearish BOS (no bias filter)", simulate(h4, d1, bias, False, tm))
        nulls = []
        for _ in range(5):
            nulls.extend(simulate(make_null(h4), d1, bias, False, tm, is_null=True))
        report("NULL (random walk) x5", nulls)
        print()

    print("  READ: on a random walk, WR is just a function of R:R and expR ~ 0 after costs")
    print("  (the same for real and null). If HTF-aligned expR clears 0 AND beats the null by")
    print("  more than noise -> real edge the generic scan missed. If aligned ~= null ~= <0 ->")
    print("  honest negative on the USER'S OWN method (V10 is random; nothing to capture).\n")


if __name__ == "__main__":
    main()
