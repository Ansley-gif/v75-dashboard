#!/usr/bin/env python3
"""
Cross-Window Stability Test for Pattern 9 (and 7A) on V25.

Fetches data once, slices into non-overlapping ~2-month windows, then runs
the same set of TP/SL configs against each window. Reports per-window
expectancy + a stability summary so we can tell genuine edge from
single-window luck.
"""
import asyncio
import io
import sys
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import PatternScanner as PS

# ── Broker reality (V25 / R_25 on Deriv SVG) ──────────────────────────────
SPREAD       = 137
SLIPPAGE     = 2
STOPS_LEVEL  = 423
POINT        = 0.001
SYMBOL       = "R_25"
YEARS        = 1.0

# ── Configs to test (raw_sl_ticks, raw_tp_ticks) ──────────────────────────
CONFIGS = [
    (500,  940),     # current production (baseline negative)
    (500,  1330),    # design R:R 1.88 restored
    (500,  2000),    # sweep flat
    (500,  3000),    # sweep best winner
    (2000, 4000),    # sweep wide-SL winner
    (1500, 3000),    # extra mid-wide
]

# ── Non-overlapping ~2-month windows (UTC) ────────────────────────────────
WINDOWS = [
    ("W1: 2025-09-13 to 2025-10-31", "2025-09-13", "2025-10-31"),
    ("W2: 2025-11-01 to 2025-12-31", "2025-11-01", "2025-12-31"),
    ("W3: 2026-01-01 to 2026-02-28", "2026-01-01", "2026-02-28"),
    ("W4: 2026-03-01 to 2026-04-30", "2026-03-01", "2026-04-30"),
]

WARMUP_DAYS = 2   # extra bars before window start so OC levels exist


def slice_window(bars, start_str, end_str, warmup_days=WARMUP_DAYS):
    """Return (sliced_bars, real_start_epoch). sliced_bars includes warmup."""
    start_dt   = datetime.fromisoformat(start_str).replace(tzinfo=timezone.utc)
    end_dt     = datetime.fromisoformat(end_str + "T23:59:59").replace(tzinfo=timezone.utc)
    real_start = int(start_dt.timestamp())
    warm_start = real_start - warmup_days * 86400
    end_epoch  = int(end_dt.timestamp())
    sliced     = [b for b in bars if warm_start <= b["epoch"] <= end_epoch]
    return sliced, real_start


def run_pattern9(bars_slice, real_start, tp_ticks, sl_ticks):
    """Run Pattern 9 on a slice, post-process to $-frame, return stats dict."""
    broker_sl = max(sl_ticks, STOPS_LEVEL + 2 * SPREAD + 10)
    sim_sl    = max(1, broker_sl - SPREAD - SLIPPAGE)
    sim_tp    = tp_ticks + SPREAD + SLIPPAGE

    trades = PS.scan_oc_break_ict(bars_slice, sim_tp, sim_sl, POINT, "m5")
    trades = [t for t in trades if t.entry_epoch >= real_start]

    PS.recompute_r_multiple_dollar(trades, tp_ticks, SPREAD, SLIPPAGE, POINT)

    done = [t for t in trades if t.outcome in ("WIN", "LOSS")]
    if not done:
        return dict(n=0, wr=0.0, avg_rw=0.0, exp=0.0, net_r=0.0, broker_sl=broker_sl)

    wins   = [t for t in done if t.outcome == "WIN"]
    wr     = len(wins) / len(done)
    avg_rw = sum(t.r_multiple for t in wins) / len(wins) if wins else 0.0
    exp    = wr * avg_rw - (1 - wr) * 1.0
    net_r  = sum(t.r_multiple for t in done)
    return dict(n=len(done), wr=wr, avg_rw=avg_rw, exp=exp,
                net_r=net_r, broker_sl=broker_sl)


async def main():
    print(f"Fetching {YEARS:.1f} year(s) of {SYMBOL} M5 bars …")
    bars = await PS.fetch_history(SYMBOL, YEARS)
    if len(bars) < 1000:
        print("Not enough data.")
        return
    print(f"Got {len(bars):,} bars.")
    print(f"  Range: {datetime.utcfromtimestamp(bars[0]['epoch']):%Y-%m-%d} "
          f"→ {datetime.utcfromtimestamp(bars[-1]['epoch']):%Y-%m-%d}\n")

    # Pre-slice windows once
    sliced = []
    for label, sd, ed in WINDOWS:
        sb, rs = slice_window(bars, sd, ed)
        sliced.append((label, sb, rs))
        print(f"  {label}: {len(sb):,} bars (incl {WARMUP_DAYS}-day warmup)")
    print()

    # ── Per-window detail table ─────────────────────────────────────────
    print("=" * 100)
    print("PATTERN 9 — per-window detail")
    print("=" * 100)
    print(f"{'Window':<32}  {'Config':<14}  {'$R:R':>5}  "
          f"{'N':>5}  {'WR%':>6}  {'AvgRw':>6}  {'Exp R':>9}  {'Net R':>9}")
    print("-" * 100)

    # cache: config → list of per-window result dicts
    results = {cfg: [] for cfg in CONFIGS}

    for win_label, sb, rs in sliced:
        for sl_t, tp_t in CONFIGS:
            r  = run_pattern9(sb, rs, tp_t, sl_t)
            rr = tp_t / r["broker_sl"] if r["broker_sl"] > 0 else 0.0
            cfg = f"SL={sl_t}/TP={tp_t}"
            flag = " ✓" if r["exp"] > 0.05 else ("  " if r["exp"] >= 0 else " ✗")
            print(f"{win_label:<32}  {cfg:<14}  {rr:>5.2f}  "
                  f"{r['n']:>5}  {r['wr']*100:>5.1f}%  {r['avg_rw']:>5.2f}R  "
                  f"{r['exp']:>+7.3f}R{flag}  {r['net_r']:>+8.2f}R")
            results[(sl_t, tp_t)].append(r)
        print("-" * 100)

    # ── Stability summary ──────────────────────────────────────────────
    print()
    print("=" * 100)
    print("STABILITY SUMMARY  (positive windows / total)")
    print("=" * 100)
    print(f"{'Config':<14}  {'$R:R':>5}  {'BE WR%':>7}  "
          f"{'Pos wins':>9}  {'Avg Exp':>9}  {'Min Exp':>9}  {'Max Exp':>9}  Stability")
    print("-" * 100)

    for sl_t, tp_t in CONFIGS:
        rs   = results[(sl_t, tp_t)]
        rr   = tp_t / rs[0]["broker_sl"] if rs and rs[0]["broker_sl"] > 0 else 0.0
        be   = 1.0 / (1.0 + rr) if rr > 0 else 0.0
        exps = [r["exp"] for r in rs]
        wins = sum(1 for e in exps if e > 0)
        avg_e = sum(exps) / len(exps) if exps else 0
        min_e = min(exps) if exps else 0
        max_e = max(exps) if exps else 0
        cfg   = f"SL={sl_t}/TP={tp_t}"
        # 4/4 positive AND avg > 0.05 = stable; 3/4 = mixed; otherwise weak
        if wins == len(rs) and avg_e > 0.05:
            tag = "STABLE ✓"
        elif wins >= len(rs) - 1 and avg_e > 0:
            tag = "MIXED"
        else:
            tag = "WEAK"
        print(f"{cfg:<14}  {rr:>5.2f}  {be*100:>6.1f}%  "
              f"{wins:>4}/{len(rs):<4}  {avg_e:>+7.3f}R  "
              f"{min_e:>+7.3f}R  {max_e:>+7.3f}R  {tag}")

    print()


if __name__ == "__main__":
    asyncio.run(main())
