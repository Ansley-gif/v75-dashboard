#!/usr/bin/env python3
"""
v10_meanrev_extension.py — Chasing the quarterly mean-reversion whiff PROPERLY.

What v10_quarterly_cycle.py found: a faint NEGATIVE 60-90d autocorr in V10 (down
quarter -> up quarter), unlike the null — but irregular timing (CV~1.8) made a
fixed-time reversal bet break-even OOS.

This fixes the two weaknesses honestly:
  1. TRIGGER ON OVEREXTENSION, not elapsed time. Since timing is irregular, enter
     when price is stretched |z| >= Z_ENTRY from its quarterly mean, and bet the
     reversion back to the mean. This is the natural mean-reversion entry.
  2. POOL THE WHOLE VOLATILITY FAMILY for sample size AND as a structural check:
     a real mean-reversion in the construction should appear across ALL of them;
     V10-only would be small-sample luck.

Honest design: per-symbol OUT-OF-SAMPLE (last 35%), net of each symbol's REAL
spread, vs a per-symbol random-walk null (shuffled returns). Also reports the
60d lookback->forward corr per symbol (does Claim A replicate across the family?).

INVOCATION: py v10_meanrev_extension.py
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import math, random, statistics as st
import MetaTrader5 as mt5

SYMBOLS = ["Volatility 10 Index", "Volatility 25 Index", "Volatility 50 Index",
           "Volatility 75 Index", "Volatility 100 Index",
           "Volatility 10 (1s) Index", "Volatility 75 (1s) Index", "Volatility 100 (1s) Index"]
W = 63            # quarterly window (trading days)
Z_ENTRY = 2.0     # overextension threshold
STOP_EXT = 1.0    # adverse extension (z units) that stops us out
TIMECAP = 189     # max hold ~ 3 quarters
OOS_FRAC = 0.35


def load(sym, count=5000):
    mt5.symbol_select(sym, True)
    r = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_D1, 0, count)
    si = mt5.symbol_info(sym)
    if r is None or len(r) == 0:
        return None, None
    closes = [float(x["close"]) for x in r]
    spread_price = si.spread * si.point
    return closes, spread_price


def corr60(closes):
    past, fwd = [], []
    for i in range(60, len(closes) - 60):
        past.append(closes[i] / closes[i - 60] - 1)
        fwd.append(closes[i + 60] / closes[i] - 1)
    if len(past) < 5:
        return 0.0
    mx, my = st.mean(past), st.mean(fwd)
    num = sum((a - mx) * (b - my) for a, b in zip(past, fwd))
    dx = sum((a - mx) ** 2 for a in past) ** 0.5
    dy = sum((b - my) ** 2 for b in fwd) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


def meanrev(closes, spread_price):
    """Overextension mean-reversion in R units (net of spread). z vs W-day mean/std.
    Enter |z|>=Z_ENTRY betting reversion to mean; stop at STOP_EXT further; cap TIMECAP."""
    trades = []
    i = W
    while i < len(closes) - 1:
        win = closes[i - W:i]
        m, sd = st.mean(win), st.pstdev(win)
        if sd <= 0:
            i += 1; continue
        z = (closes[i] - m) / sd
        if abs(z) < Z_ENTRY:
            i += 1; continue
        entry = closes[i]
        if z > 0:                                   # overextended UP -> short to mean
            target = m
            stop = m + (z + STOP_EXT) * sd
            direction = -1
        else:                                       # overextended DOWN -> long to mean
            target = m
            stop = m - (-z + STOP_EXT) * sd
            direction = +1
        risk = abs(stop - entry)
        reward = abs(entry - target)
        if risk <= 0:
            i += 1; continue
        outcome = None
        for j in range(i + 1, min(i + TIMECAP, len(closes))):
            c = closes[j]
            if direction == -1:
                if c >= stop:
                    outcome = "LOSS"; break
                if c <= target:
                    outcome = "WIN"; break
            else:
                if c <= stop:
                    outcome = "LOSS"; break
                if c >= target:
                    outcome = "WIN"; break
            i = j
        if outcome == "WIN":
            trades.append((reward - spread_price) / risk)
        elif outcome == "LOSS":
            trades.append(-(risk + spread_price) / risk)
        i += 1
    return trades


def shuffle(closes):
    rets = [closes[k] / closes[k - 1] - 1 for k in range(1, len(closes))]
    random.shuffle(rets)
    out = [closes[0]]
    for r in rets:
        out.append(out[-1] * (1 + r))
    return out


def stats(tr):
    n = len(tr)
    if n == 0:
        return 0, 0.0, 0.0, 0.0
    m = st.mean(tr)
    wr = sum(1 for x in tr if x > 0) / n * 100
    se = st.pstdev(tr) / math.sqrt(n) if n > 1 else 0
    return n, wr, m, se


def main():
    if not mt5.initialize():
        raise SystemExit(f"init failed {mt5.last_error()}")
    print("=" * 96)
    print("  QUARTERLY MEAN-REVERSION — overextension trigger, whole vol family, OOS, net of spread")
    print("=" * 96)
    print(f"  z vs {W}d mean; enter |z|>={Z_ENTRY}, target=mean, stop=+{STOP_EXT}z, cap {TIMECAP}d; "
          f"OOS=last {int(OOS_FRAC*100)}%\n")
    print(f"  {'symbol':28s} {'60d corr':>9} {'OOS n':>6} {'OOS WR':>7} {'OOS expR':>9} {'95% CI':>17} {'NULL expR':>10}")
    print("  " + "-" * 92)

    pooled_real, pooled_null = [], []
    random.seed(5)
    for sym in SYMBOLS:
        closes, spread_price = load(sym)
        if closes is None or len(closes) < 500:
            print(f"  {sym:28s}  (insufficient data)")
            continue
        split = int(len(closes) * (1 - OOS_FRAC))
        oos = closes[split - W:]                    # keep W warmup before OOS start
        c60 = corr60(closes)
        real = meanrev(oos, spread_price)
        null = meanrev(shuffle(oos), spread_price)
        pooled_real += real
        pooled_null += null
        n, wr, m, se = stats(real)
        nn, wrn, mn, sen = stats(null)
        lo, hi = m - 1.96 * se, m + 1.96 * se
        flag = "EDGE" if lo > 0 else ("lose" if hi < 0 else "~0")
        print(f"  {sym:28s} {c60:>+9.3f} {n:>6} {wr:>6.1f}% {m:>+9.3f} [{lo:>+6.2f},{hi:>+6.2f}] {mn:>+10.3f} {flag}")

    mt5.shutdown()
    print("  " + "-" * 92)
    n, wr, m, se = stats(pooled_real)
    nn, wrn, mn, sen = stats(pooled_null)
    lo, hi = m - 1.96 * se, m + 1.96 * se
    lon, hin = mn - 1.96 * sen, mn + 1.96 * sen
    print(f"  {'POOLED (all symbols, OOS)':28s} {'':>9} {n:>6} {wr:>6.1f}% {m:>+9.3f} [{lo:>+6.2f},{hi:>+6.2f}] {mn:>+10.3f}")
    print(f"  {'POOLED NULL':28s} {'':>9} {nn:>6} {wrn:>6.1f}% {mn:>+9.3f} [{lon:>+6.2f},{hin:>+6.2f}]")
    print()
    print("  READ: real edge if (a) 60d corr is consistently NEGATIVE across the family,")
    print("  (b) pooled OOS expR CI lower bound > 0, AND (c) pooled real clearly beats the null.")
    print("  If pooled real ~= null ~= 0 -> the whiff was V10 small-sample luck; no structural")
    print("  mean-reversion to trade. If real > null with CI>0 -> a real family-wide edge.\n")


if __name__ == "__main__":
    main()
