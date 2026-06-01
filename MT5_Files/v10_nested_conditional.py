#!/usr/bin/env python3
"""
v10_nested_conditional.py — Test the NESTING, not the layers in isolation.

User's point: "the quarterly moves are a basis. it's about what happens on the
weekly/daily/4h/1h AFTER that." i.e. quarterly sets the bias; the edge is in how
the LOWER timeframes behave inside that bias.

For that to be tradeable, ONE thing must be true: once the quarterly bias is known
(price overextended -> expect reversion), the LOWER timeframes must move in the
bias direction MORE than 50% of the time. If daily/4h stay 50/50 regardless of the
quarterly context, no lower-TF precision (OB/FVG/BOS) can help — there's nothing to
be precise about. If they tilt above 50%, the nesting is real and we build on it.

THE DECISIVE MEASUREMENT (this is "what happens after the quarterly shift"):
  conditional on quarterly |z|>=Z (bias = revert toward mean), what fraction of the
  next daily / next-5-daily / next-4H moves go in the bias direction? vs 50% and vs
  the unconditional base rate. Then monetized OOS, net of spread, vs null.

Pools the volatility family for sample. SAME candles as the user's MT5 charts.
INVOCATION: py v10_nested_conditional.py
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import math, random, statistics as st
import MetaTrader5 as mt5

SYMBOLS = ["Volatility 10 Index", "Volatility 25 Index", "Volatility 50 Index",
           "Volatility 100 Index", "Volatility 10 (1s) Index", "Volatility 100 (1s) Index"]
W = 63          # quarterly window
Z = 2.0         # overextension that defines the quarterly bias
OOS_FRAC = 0.35


def pull(sym, tf, count):
    mt5.symbol_select(sym, True)
    r = mt5.copy_rates_from_pos(sym, tf, 0, count)
    if r is None or len(r) == 0:
        return None
    return [(int(x["time"]), float(x["close"])) for x in r]


def quarterly_bias_series(daily_closes):
    """For each daily index, bias = -sign(z) when |z|>=Z (revert to mean), else 0."""
    bias = [0] * len(daily_closes)
    for i in range(W, len(daily_closes)):
        win = daily_closes[i - W:i]
        m, sd = st.mean(win), st.pstdev(win)
        if sd <= 0:
            continue
        z = (daily_closes[i] - m) / sd
        if z >= Z:
            bias[i] = -1     # overextended up -> expect DOWN
        elif z <= -Z:
            bias[i] = +1     # overextended down -> expect UP
    return bias


def cond_continuation(closes, bias, horizon):
    """P(forward move over `horizon` goes in the bias direction | bias != 0).
    Returns (n, hit_rate%, base_rate%) where base = same horizon, all bars."""
    hits = n = 0
    base_hits = base_n = 0
    for i in range(W, len(closes) - horizon):
        fwd = closes[i + horizon] - closes[i]
        base_n += 1
        if fwd > 0:
            base_hits += 1
        if bias[i] != 0:
            n += 1
            if (fwd > 0 and bias[i] > 0) or (fwd < 0 and bias[i] < 0):
                hits += 1
    if n == 0:
        return 0, 0.0, 0.0
    return n, hits / n * 100, base_hits / base_n * 100


def monetize(closes, bias, spread_price, horizon):
    """Trade in the quarterly bias direction, hold `horizon` bars, net spread. R-ish % units."""
    rets = []
    i = W
    while i < len(closes) - horizon:
        if bias[i] != 0:
            entry = closes[i]; exitp = closes[i + horizon]
            pl = bias[i] * (exitp - entry) / entry * 100 - spread_price / entry * 100
            rets.append(pl); i += horizon
        else:
            i += 1
    if not rets:
        return 0, 0.0, 0.0
    m = st.mean(rets); se = st.pstdev(rets) / math.sqrt(len(rets)) if len(rets) > 1 else 0
    return len(rets), m, se


def shuffle(closes):
    r = [closes[k] / closes[k - 1] - 1 for k in range(1, len(closes))]
    random.shuffle(r)
    out = [closes[0]]
    for x in r:
        out.append(out[-1] * (1 + x))
    return out


def main():
    if not mt5.initialize():
        raise SystemExit("init failed")
    random.seed(3)
    print("=" * 96)
    print("  NESTED TEST — does the quarterly bias TILT the lower timeframes? (daily + 4H)")
    print("=" * 96)
    print(f"  Quarterly bias from {W}d z (|z|>={Z}, revert-to-mean). OOS=last {int(OOS_FRAC*100)}%.")
    print(f"  KEY: if conditional continuation > base rate AND > 50%, the nesting is real.\n")

    pooled = {"d1_1": [], "d1_5": [], "h4_6": []}   # (n_dir_hits style via monetize)
    print(f"  {'symbol':26s} | {'DAILY next-1d':>20} | {'DAILY next-5d':>20} | {'4H next-6 (1d)':>20}")
    print(f"  {'':26s} | {'cond%  base%':>20} | {'cond%  base%':>20} | {'cond%  base%':>20}")
    print("  " + "-" * 92)
    money = {"d1": [], "d1_null": [], "h4": [], "h4_null": []}
    for sym in SYMBOLS:
        d = pull(sym, mt5.TIMEFRAME_D1, 5000)
        h = pull(sym, mt5.TIMEFRAME_H4, 20000)
        si = mt5.symbol_info(sym); spread_price = si.spread * si.point
        if not d or not h:
            print(f"  {sym:26s}  (no data)"); continue
        dc = [c for _, c in d]
        # map quarterly bias (daily) onto H4 by day
        dbias = quarterly_bias_series(dc)
        day_bias = {t // 86400: dbias[i] for i, (t, _) in enumerate(d)}
        hc = [c for _, c in h]
        hbias = [day_bias.get(t // 86400, 0) for t, _ in h]
        # OOS slices
        ds = int(len(dc) * (1 - OOS_FRAC)); hs = int(len(hc) * (1 - OOS_FRAC))
        dc_o, db_o = dc[ds - W:], dbias[ds - W:]
        hc_o, hb_o = hc[hs - W:], hbias[hs - W:]

        n1, c1, b1 = cond_continuation(dc_o, db_o, 1)
        n5, c5, b5 = cond_continuation(dc_o, db_o, 5)
        nh, ch, bh = cond_continuation(hc_o, hb_o, 6)
        print(f"  {sym:26s} | {c1:5.1f}% {b1:5.1f}% (n{n1:<4})| {c5:5.1f}% {b5:5.1f}% (n{n5:<4})| "
              f"{ch:5.1f}% {bh:5.1f}% (n{nh:<4})")

        # monetize daily (hold 5) and h4 (hold 6) OOS, real vs null
        _, md, _ = monetize(dc_o, db_o, spread_price, 5)
        dn = shuffle(dc_o)
        _, mdn, _ = monetize(dn, db_o, spread_price, 5)
        money["d1"].append(md); money["d1_null"].append(mdn)
    mt5.shutdown()

    print("  " + "-" * 92)
    print("\n=== MONETIZED (trade the quarterly bias on the daily, hold 5d, OOS, net spread) ===")
    if money["d1"]:
        mr = st.mean(money["d1"]); mn = st.mean(money["d1_null"])
        print(f"  mean per-symbol trade return:  REAL {mr:+.3f}%   NULL {mn:+.3f}%")
        print(f"  per symbol REAL: " + "  ".join(f"{x:+.2f}" for x in money['d1']))
        print(f"  per symbol NULL: " + "  ".join(f"{x:+.2f}" for x in money['d1_null']))

    print("\n  READ: nesting is REAL only if conditional continuation beats BOTH 50% and the")
    print("  base rate, consistently across symbols, AND the monetized version beats the null.")
    print("  If cond% ~= base% ~= 50% -> the quarterly bias does NOT tilt the lower timeframes;")
    print("  they stay 50/50 inside a known bias, so OB/FVG precision has nothing to work with.\n")


if __name__ == "__main__":
    main()
