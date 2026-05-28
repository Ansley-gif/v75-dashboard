#!/usr/bin/env python3
"""
TP/SL Sweep for Pattern 9 on V25 — fetches data once, tests many combos.

Goal: find a TP/SL configuration where Pattern 9 has positive expectancy
under realistic Deriv broker conditions (spread + stops_level).
"""
import asyncio
import io
import sys

# Force UTF-8 stdout so the scanner's unicode chars don't crash on Windows cp1252
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Reuse the scanner's existing primitives
import PatternScanner as PS

# Broker reality (from MT5 OnInit log)
SPREAD       = 137   # ticks
STOPS_LEVEL  = 423   # ticks
POINT        = 0.001
SYMBOL       = "R_25"
YEARS        = 1.0

# Configurations: (raw_sl_ticks, raw_tp_ticks)
CONFIGS = [
    (500, 940),      # current production
    (500, 1500),     # bigger TP, same SL
    (500, 2000),     # 4:1 nominal
    (500, 3000),     # 6:1 nominal
    (800, 1600),     # 2:1 nominal, SL above stops floor
    (1000, 2000),    # wider absolute
    (1500, 3000),    # much wider
    (2000, 4000),    # extreme width
    (300, 940),      # smaller SL (will be floored to 707)
    (300, 1500),
]


async def main():
    print(f"Fetching {YEARS} year(s) of {SYMBOL} M5 bars …")
    bars = await PS.fetch_history(SYMBOL, YEARS)
    print(f"Got {len(bars):,} bars.\n")

    print(f"{'raw_sl':>7} {'raw_tp':>7} {'eff_sl':>7} {'eff_tp':>7} "
          f"{'trades':>7} {'WR%':>6} {'avg_Rw':>7} {'exp_R':>9} {'net_R':>9}")
    print("-" * 80)

    for raw_sl, raw_tp in CONFIGS:
        eff_sl = max(raw_sl, STOPS_LEVEL + 2 * SPREAD + 10)
        eff_tp = max(1, raw_tp - SPREAD)

        trades = PS.scan_oc_break_ict(bars, eff_tp, eff_sl, POINT, trigger="m5")
        done   = [t for t in trades if t.outcome in ("WIN", "LOSS")]
        if not done:
            print(f"{raw_sl:>7} {raw_tp:>7} {eff_sl:>7} {eff_tp:>7}  no trades")
            continue

        wins   = [t for t in done if t.outcome == "WIN"]
        wr     = len(wins) / len(done)
        avg_rw = sum(t.r_multiple for t in wins) / len(wins) if wins else 0.0
        exp    = wr * avg_rw - (1 - wr) * 1.0
        net_r  = sum(t.r_multiple for t in done)

        flag   = " ✓" if exp > 0.05 else ("  " if exp >= 0 else " ✗")
        print(f"{raw_sl:>7} {raw_tp:>7} {eff_sl:>7} {eff_tp:>7} "
              f"{len(done):>7} {wr*100:>5.1f}% {avg_rw:>6.2f}R "
              f"{exp:>+7.3f}R{flag} {net_r:>+8.2f}R")


if __name__ == "__main__":
    asyncio.run(main())
