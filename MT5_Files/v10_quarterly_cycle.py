#!/usr/bin/env python3
"""
v10_quarterly_cycle.py — FORWARD TEST of the user's EXACT claim, on unseen V10 data.

User's claim (verbatim foundation):
  "after every 3-4 months price changes direction... there is repetitiveness there.
   20/40/60 lookback and forward."

This is a precise, falsifiable claim. If price REVERSES every ~3-4 months, then:
  (A) past N-day return should be NEGATIVELY correlated with next N-day return
      (a down quarter precedes an up quarter) — tested at N = 20/40/60/90 (his numbers).
  (B) the TIME BETWEEN direction changes should cluster tightly around ~3-4 months
      (regular cycle = tradeable) rather than scatter (random walk wandering).
  (C) a 'bet the reversal after K months' strategy should PROFIT out-of-sample, net of spread.

HONEST DESIGN:
  - SAME candles the user's MT5 chart shows (symbol 'Volatility 10 Index', their feed).
  - IN-SAMPLE = older 65%; OUT-OF-SAMPLE = most recent 35% (the 'unseen' data he trades).
  - Everything compared to a random-walk NULL (V10's own shuffled returns) — because a
    random walk ALSO produces apparent multi-month 'trends/reversals'; the question is
    whether V10's are MORE regular / predictable than random wandering.

INVOCATION: py v10_quarterly_cycle.py
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import math, random, statistics as st
import MetaTrader5 as mt5

SYMBOL = "Volatility 10 Index"
SPREAD_PTS, POINT = 162, 0.001


def load_daily(count=3000):
    if not mt5.initialize():
        raise SystemExit(f"mt5.initialize failed: {mt5.last_error()}")
    mt5.symbol_select(SYMBOL, True)
    r = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_D1, 0, count)
    mt5.shutdown()
    if r is None or len(r) == 0:
        raise SystemExit("no rates")
    return [(int(x["time"]), float(x["close"])) for x in r]


def corr(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 5:
        return 0.0, 0
    xs2, ys2 = zip(*pairs)
    mx, my = st.mean(xs2), st.mean(ys2)
    num = sum((x - mx) * (y - my) for x, y in pairs)
    dx = sum((x - mx) ** 2 for x in xs2) ** 0.5
    dy = sum((y - my) ** 2 for y in ys2) ** 0.5
    return (num / (dx * dy) if dx and dy else 0.0), len(pairs)


def lookback_forward(closes, N):
    """past N-day return vs next N-day return. Negative corr = reversal (his claim)."""
    past, fwd = [], []
    for i in range(N, len(closes) - N):
        past.append(closes[i] / closes[i - N] - 1)
        fwd.append(closes[i + N] / closes[i] - 1)
    return corr(past, fwd)


def reversals(closes, roc_win=60):
    """Direction = sign of roc_win-day return. Return list of intervals (days) between flips."""
    sign = []
    for i in range(len(closes)):
        if i < roc_win:
            sign.append(0); continue
        sign.append(1 if closes[i] > closes[i - roc_win] else -1)
    flips = [i for i in range(roc_win + 1, len(sign)) if sign[i] != sign[i - 1] and sign[i] != 0]
    intervals = [flips[i] - flips[i - 1] for i in range(1, len(flips))]
    return intervals


def reversal_strategy(closes, hold=63, after=63):
    """His claim monetized: after price has run 'after' days in one direction, bet the
    REVERSAL, hold 'hold' days. Net of spread (% of price). Returns mean % per trade."""
    fr = SPREAD_PTS * POINT
    rets = []
    i = after
    while i < len(closes) - hold:
        run = closes[i] / closes[i - after] - 1
        entry = closes[i]
        exitp = closes[i + hold]
        if run > 0:      # ran up -> bet reversal DOWN (short)
            pl = (entry - exitp) / entry * 100 - fr / entry * 100
            rets.append(pl); i += hold
        elif run < 0:    # ran down -> bet reversal UP (long)
            pl = (exitp - entry) / entry * 100 - fr / entry * 100
            rets.append(pl); i += hold
        else:
            i += 1
    if not rets:
        return 0, 0.0, 0.0
    m = st.mean(rets)
    se = st.pstdev(rets) / math.sqrt(len(rets)) if len(rets) > 1 else 0
    return len(rets), m, se


def shuffle_walk(closes):
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    random.shuffle(rets)
    out = [closes[0]]
    for r in rets:
        out.append(out[-1] * (1 + r))
    return out


def main():
    import datetime as dt
    data = load_daily()
    times = [t for t, _ in data]
    closes = [c for _, c in data]
    split = int(len(closes) * 0.65)
    IS = closes[:split]
    OOS = closes[split:]
    d0, dsplit, d1 = (dt.datetime.utcfromtimestamp(times[0]).date(),
                      dt.datetime.utcfromtimestamp(times[split]).date(),
                      dt.datetime.utcfromtimestamp(times[-1]).date())
    print("=" * 90)
    print("  V10 QUARTERLY-CYCLE FORWARD TEST — the user's exact claim, on unseen data")
    print("=" * 90)
    print(f"  SAME candles as your MT5 chart: '{SYMBOL}', {len(closes)} daily bars")
    print(f"  IN-SAMPLE: {d0} -> {dsplit}   |   OUT-OF-SAMPLE (unseen): {dsplit} -> {d1}\n")

    print("=== CLAIM A: does a down quarter precede an up quarter? (reversal = NEGATIVE corr) ===")
    print("  Your 20/40/60(/90)-day lookback vs the same-length forward return:")
    print(f"  {'N days':>7} {'IN-SAMPLE corr':>16} {'OUT-OF-SAMPLE corr':>20} {'NULL(rand-walk)':>17}")
    random.seed(11)
    null_oos = shuffle_walk(OOS)
    for N in (20, 40, 60, 90):
        ci, ni = lookback_forward(IS, N)
        co, no = lookback_forward(OOS, N)
        cn, _ = lookback_forward(null_oos, N)
        print(f"  {N:>7} {ci:>+16.3f} {co:>+20.3f} {cn:>+17.3f}")
    print("  (his claim needs clearly NEGATIVE corr, consistent IS->OOS, and unlike the null)")

    print("\n=== CLAIM B: is the time between direction changes REGULAR (~3-4 months)? ===")
    iv = reversals(closes, 60)
    ivn = reversals(shuffle_walk(closes), 60)
    if iv:
        cv = st.pstdev(iv) / st.mean(iv) if st.mean(iv) else 0
        cvn = st.pstdev(ivn) / st.mean(ivn) if ivn and st.mean(ivn) else 0
        print(f"  V10 real : flips={len(iv)}  mean gap={st.mean(iv):.0f}d  median={st.median(iv):.0f}d  "
              f"min={min(iv)} max={max(iv)}  CV={cv:.2f}")
        print(f"  NULL walk: flips={len(ivn)}  mean gap={st.mean(ivn):.0f}d  median={st.median(ivn):.0f}d  "
              f"min={min(ivn)} max={max(ivn)}  CV={cvn:.2f}")
        print("  (3-4 months = ~63-84 trading days. REGULAR cycle = LOW CV (<~0.4) and unlike null.")
        print("   CV near/above 1.0 = exponential scatter = random wandering, NOT a clock.)")

    print("\n=== CLAIM C: MONETIZED — 'after ~3 months one way, bet the reversal' (OUT-OF-SAMPLE) ===")
    for after, hold in ((63, 63), (84, 42), (42, 42)):
        n, m, se = reversal_strategy(OOS, hold=hold, after=after)
        nn, mn, sen = reversal_strategy(null_oos, hold=hold, after=after)
        lo, hi = m - 1.96 * se, m + 1.96 * se
        verd = "PROFITS (CI>0)" if lo > 0 else ("loses (CI<0)" if hi < 0 else "break-even")
        print(f"  after {after}d, hold {hold}d:  V10 OOS n={n} mean={m:+.2f}% [{lo:+.2f},{hi:+.2f}] {verd}"
              f"   | null {mn:+.2f}%")

    print("\n  READ: your claim is TRUE if corr is clearly negative (IS and OOS, unlike null),")
    print("  reversal timing is REGULAR (low CV, unlike null), AND the reversal bet profits")
    print("  out-of-sample net of spread. If corr~0, CV~null, and the bet ~= null ~= 0,")
    print("  the 3-4 month 'cycle' is the same wandering a random walk produces.\n")


if __name__ == "__main__":
    main()
