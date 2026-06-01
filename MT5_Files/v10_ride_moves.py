#!/usr/bin/env python3
"""
v10_ride_moves.py — Test the user's ACTUAL claim about V10, their way:
  "if V10 can sell or buy for even 3 days or 2 weeks, we're not predicting,
   just riding the move and taking profit — like we did on gold."

So this does NOT test prediction. It tests PERSISTENCE — the exact property that
made the gold sustained-downtrend short pay (+5.13% on the 2022 bear). Plus the
one place a non-directional 'algorithm' could still hide: VOLATILITY clustering.

THREE tests on real V10 daily data (from MT5):
  1. MOVE PERSISTENCE: after N days in one direction, does the move continue over
     the next M days? (ride-the-move). Grid N x M. >50% / +ve = ridable.
  2. SPELL TEST (gold analog): contiguous runs on the same side of the 20-day MA;
     count, length, and the P/L of holding through each spell.
  3. VOL CLUSTERING: autocorrelation of |daily return| (the GARCH signature). If
     vol clusters, there's a tradeable volatility structure even if direction is random.

Each compared to a random-walk null built from V10's own shuffled returns.
INVOCATION: py v10_ride_moves.py
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import math, random, statistics as st
from datetime import datetime, timezone
import MetaTrader5 as mt5

SYMBOL = "Volatility 10 Index"


def load(tf, count):
    if not mt5.initialize():
        raise SystemExit(f"mt5.initialize failed: {mt5.last_error()}")
    mt5.symbol_select(SYMBOL, True)
    r = mt5.copy_rates_from_pos(SYMBOL, tf, 0, count)
    mt5.shutdown()
    if r is None or len(r) == 0:
        raise SystemExit(f"no rates: {mt5.last_error()}")
    return [float(x["close"]) for x in r]


def rets_of(closes):
    return [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]


def persistence(closes, label):
    """After N same-direction days, mean forward return over next M days."""
    r = rets_of(closes)
    print(f"  [{label}]  (mean fwd % return after N consecutive same-direction days)")
    print(f"   {'N\\M':>4}", *[f"{m:>9}d" for m in (3, 5, 10)])
    for N in (2, 3, 5):
        row = []
        for M in (3, 5, 10):
            fwds = []
            for i in range(N, len(r) - M):
                last = r[i - N:i]
                if all(x > 0 for x in last):       # N up days -> expect up if momentum
                    fwds.append(sum(r[i:i + M]) * 100)
                elif all(x < 0 for x in last):     # N down days -> expect down; flip sign
                    fwds.append(-sum(r[i:i + M]) * 100)
            m = st.mean(fwds) if fwds else 0
            se = (st.pstdev(fwds) / math.sqrt(len(fwds))) if len(fwds) > 1 else 0
            sig = "*" if abs(m) > 1.96 * se * 100 / 100 and m > 1.96 * se else " "
            row.append(f"{m:+7.2f}{sig}")
        print(f"   {N:>4}", *[f"{c:>10}" for c in row])
    print("   (+ = momentum continues/ridable; * = mean > 1.96 SE; ~0 = random)")


def spells(closes, label, win=20):
    """Contiguous runs on one side of the 20-day MA; P/L of riding each."""
    ma = [None] * len(closes)
    for i in range(win, len(closes)):
        ma[i] = st.mean(closes[i - win:i])
    runs, cur = [], None
    for i in range(win, len(closes)):
        side = 1 if closes[i] > ma[i] else -1
        if cur is None or cur["side"] != side:
            if cur is not None:
                runs.append(cur)
            cur = {"side": side, "start": i, "p0": closes[i], "len": 1}
        else:
            cur["len"] += 1
        cur["end"] = i; cur["p1"] = closes[i]
    if cur:
        runs.append(cur)
    longs = [r for r in runs if r["len"] >= 5]
    # P/L of riding each spell in its direction
    pls = [r["side"] * (r["p1"] / r["p0"] - 1) * 100 for r in longs]
    wins = sum(1 for x in pls if x > 0)
    lens = [r["len"] for r in runs]
    print(f"  [{label}]  spells={len(runs)}  median_len={st.median(lens):.0f}d  max={max(lens)}d  >=5d={len(longs)}")
    if pls:
        print(f"            ride each >=5d spell in its direction: {wins}/{len(longs)} profitable, "
              f"avg {st.mean(pls):+.2f}%, best {max(pls):+.2f}%, worst {min(pls):+.2f}%")


def vol_cluster(closes, label):
    """Autocorrelation of |returns| — the volatility-clustering (GARCH) fingerprint."""
    r = rets_of(closes)
    a = [abs(x) for x in r]
    m = st.mean(a); sd = st.pstdev(a)
    print(f"  [{label}]  autocorr of |return| (>>0 at lag1+ = vol clusters = tradeable vol structure):")
    out = []
    for lag in (1, 2, 3, 5, 10):
        n = len(a) - lag
        ac = sum((a[i] - m) * (a[i + lag] - m) for i in range(n)) / (n * sd * sd) if sd else 0
        out.append(f"lag{lag}={ac:+.3f}")
    print("            " + "  ".join(out))


def main():
    print("=" * 90)
    print("  V10 — CAN WE RIDE ITS MOVES? (persistence + spells + vol clustering)")
    print("=" * 90)
    print("Loading V10 D1 from MT5 …")
    closes = load(mt5.TIMEFRAME_D1, 3000)
    print(f"  {len(closes)} daily closes\n")

    # random-walk null: shuffle V10's own returns (keeps drift+vol, destroys structure)
    r = rets_of(closes)
    random.seed(7); random.shuffle(r)
    nullc = [closes[0]]
    for x in r:
        nullc.append(nullc[-1] * (1 + x))

    print("=== TEST 1: MOVE PERSISTENCE (ride-the-move) ===")
    persistence(closes, "V10 real")
    persistence(nullc, "NULL (shuffled)")

    print("\n=== TEST 2: SPELL TEST (gold analog — hold through the move) ===")
    spells(closes, "V10 real")
    spells(nullc, "NULL (shuffled)")
    print("   For reference, GOLD's big spells were ALL profitable shorts (2022 +5.13%, etc.)")

    print("\n=== TEST 3: VOLATILITY CLUSTERING (the hidden-algorithm steelman) ===")
    vol_cluster(closes, "V10 real")
    vol_cluster(nullc, "NULL (shuffled)")

    print("\n  READ: if V10 real beats the shuffled null on persistence/spells -> there's a")
    print("  ridable directional move. If |return| autocorr >>0 -> tradeable vol structure.")
    print("  If real ~= null ~= 0 everywhere -> the move you see is what randomness produces;")
    print("  riding it has no edge (the honest answer, in your own 'ride the move' framework).\n")


if __name__ == "__main__":
    main()
