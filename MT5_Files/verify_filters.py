#!/usr/bin/env python3
"""
Verification checks for the Pattern 9 + SL=2000/TP=6000 candidate strategy.

Three checks:
  1. Hour-window expansion — is 13:00 a single-hour fluke or does 12:00-14:00 also work?
  2. 13:00 + 23:00 combo — does adding the second-best hour help or hurt?
  3. Drawdown profile — max DD, longest losing streak, equity curve per window.

The goal: confirm robustness before committing to a deployment config.
"""
import asyncio
import io
import sys
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import PatternScanner as PS

# ── Broker reality ────────────────────────────────────────────────────────
SPREAD       = 137
SLIPPAGE     = 2
STOPS_LEVEL  = 423
POINT        = 0.001
SYMBOL       = "R_25"
YEARS        = 1.0

# Strategy config (best from Phase A)
SL_TICKS = 2000
TP_TICKS = 6000

WINDOWS = [
    ("W1: 2025-09 to 2025-10", "2025-09-13", "2025-10-31"),
    ("W2: 2025-11 to 2025-12", "2025-11-01", "2025-12-31"),
    ("W3: 2026-01 to 2026-02", "2026-01-01", "2026-02-28"),
    ("W4: 2026-03 to 2026-04", "2026-03-01", "2026-04-30"),
]
WARMUP_DAYS = 2

HOUR_FILTERS = [
    ("13:00 only (baseline)",   {13}),
    ("23:00 only",              {23}),
    ("13 + 23",                 {13, 23}),
    ("12-13",                   {12, 13}),
    ("13-14",                   {13, 14}),
    ("12-14",                   {12, 13, 14}),
    ("11-15",                   {11, 12, 13, 14, 15}),
    ("NY session 13-21",        set(range(13, 22))),
    ("No filter (all hours)",   set(range(24))),
]


def slice_window(bars, start_str, end_str, warmup_days=WARMUP_DAYS):
    start_dt   = datetime.fromisoformat(start_str).replace(tzinfo=timezone.utc)
    end_dt     = datetime.fromisoformat(end_str + "T23:59:59").replace(tzinfo=timezone.utc)
    real_start = int(start_dt.timestamp())
    warm_start = real_start - warmup_days * 86400
    end_epoch  = int(end_dt.timestamp())
    return [b for b in bars if warm_start <= b["epoch"] <= end_epoch], real_start


def compute_eff(tp_ticks, sl_ticks):
    broker_sl = max(sl_ticks, STOPS_LEVEL + 2 * SPREAD + 10)
    sim_sl    = max(1, broker_sl - SPREAD - SLIPPAGE)
    sim_tp    = tp_ticks + SPREAD + SLIPPAGE
    return broker_sl, sim_sl, sim_tp


def stats(trades):
    done = [t for t in trades if t.outcome in ("WIN", "LOSS")]
    if not done:
        return None
    wins   = [t for t in done if t.outcome == "WIN"]
    wr     = len(wins) / len(done)
    avg_rw = sum(t.r_multiple for t in wins) / len(wins) if wins else 0.0
    exp    = wr * avg_rw - (1 - wr) * 1.0
    net_r  = sum(t.r_multiple for t in done)
    return dict(n=len(done), wr=wr, avg_rw=avg_rw, exp=exp, net_r=net_r)


def drawdown(trades_sorted):
    """Walk through trades chronologically. Return DD/streak stats."""
    done = [t for t in trades_sorted if t.outcome in ("WIN", "LOSS")]
    if not done:
        return None
    equity = peak = 0.0
    max_dd = 0.0
    win_streak = loss_streak = 0
    max_win_streak = max_loss_streak = 0
    for t in done:
        equity += t.r_multiple
        if t.r_multiple > 0:
            win_streak += 1
            loss_streak = 0
            max_win_streak = max(max_win_streak, win_streak)
        else:
            loss_streak += 1
            win_streak = 0
            max_loss_streak = max(max_loss_streak, loss_streak)
        peak   = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return dict(final_r=equity, max_dd_r=max_dd,
                max_loss_streak=max_loss_streak,
                max_win_streak=max_win_streak)


def filter_hours(trades, hours_set):
    return [t for t in trades if t.hour in hours_set]


def run_p9(bars_slice, real_start):
    _bs, sim_sl, sim_tp = compute_eff(TP_TICKS, SL_TICKS)
    trades = PS.scan_oc_break_ict(bars_slice, sim_tp, sim_sl, POINT, "m5")
    trades = [t for t in trades if t.entry_epoch >= real_start]
    PS.recompute_r_multiple_dollar(trades, TP_TICKS, SPREAD, SLIPPAGE, POINT)
    return trades


def flag(pos, avg, total_windows):
    if pos == total_windows and avg > 0.05: return " ✓✓"
    if pos >= total_windows - 1 and avg > 0.02: return " ✓"
    if pos >= total_windows // 2 and avg >= 0:  return "  "
    return " ✗"


async def main():
    print(f"Fetching {YEARS:.1f} year of {SYMBOL} M5 bars …")
    bars = await PS.fetch_history(SYMBOL, YEARS)
    print(f"Got {len(bars):,} bars.\n")

    # Pre-slice and pre-scan once per window (filters reuse the same trade list)
    print("Pre-scanning Pattern 9 with SL=2000/TP=6000 per window …")
    per_window = []   # list of (label, real_start, trades_for_window)
    for label, sd, ed in WINDOWS:
        sb, rs = slice_window(bars, sd, ed)
        trades = run_p9(sb, rs)
        per_window.append((label, rs, trades))
        n_done = sum(1 for t in trades if t.outcome in ("WIN", "LOSS"))
        print(f"  {label}: {n_done} completed trades (unfiltered)")
    print()

    win_hdr = "  ".join(f"{w[0][:13]:>13}" for w in WINDOWS)

    # ═══════════════════════════════════════════════════════════════════════
    # CHECK 1+2 — Hour-filter sweep (includes baseline, 23:00, combos, ranges)
    # ═══════════════════════════════════════════════════════════════════════
    print("=" * 110)
    print("CHECK 1+2 — Hour-filter sweep on Pattern 9 (SL=2000, TP=6000, $R:R=3.0)")
    print("=" * 110)
    print(f"{'Filter':<24}  {'N/win':>5}  {win_hdr}  {'Pos':>4}  {'Avg Exp':>8}  {'Avg Net':>8}")
    print("-" * 120)

    filter_results = {}  # filter_label → list of per-window result dicts
    for flabel, hours in HOUR_FILTERS:
        cells = []
        exps  = []
        nets  = []
        ns    = []
        for _, _, trades in per_window:
            filtered = filter_hours(trades, hours)
            s = stats(filtered)
            if s:
                cells.append(f"{s['wr']*100:3.0f}%/{s['exp']:+.2f}")
                exps.append(s['exp']); nets.append(s['net_r']); ns.append(s['n'])
            else:
                cells.append(f"{'—':>13}")
                exps.append(0); nets.append(0); ns.append(0)
        pos     = sum(1 for e in exps if e > 0)
        avg_exp = sum(exps) / len(exps) if exps else 0.0
        avg_net = sum(nets) / len(nets) if nets else 0.0
        avg_n   = sum(ns)   / len(ns)   if ns   else 0
        filter_results[flabel] = (pos, avg_exp, avg_net, avg_n, exps, nets)
        print(f"{flabel:<24}  {avg_n:>5.0f}  "
              + "  ".join(f"{c:>13}" for c in cells)
              + f"  {pos}/{len(WINDOWS):<2}  {avg_exp:>+6.3f}R  {avg_net:>+7.2f}R{flag(pos, avg_exp, len(WINDOWS))}")
    print()

    # Rank filters: 4/4 + highest avg first
    print("Filter ranking (best → worst):")
    ranked = sorted(filter_results.items(),
                    key=lambda kv: (-kv[1][0], -kv[1][1]))
    for fl, (pos, avg_e, avg_n_r, avg_n, _, _) in ranked[:5]:
        print(f"  {fl:<24}  {pos}/4 pos  avg exp {avg_e:+.3f}R  avg net {avg_n_r:+.2f}R/win  ~{avg_n:.0f} trades/2mo")
    print()

    # ═══════════════════════════════════════════════════════════════════════
    # CHECK 3 — Drawdown profile for top 3 filters
    # ═══════════════════════════════════════════════════════════════════════
    print("=" * 110)
    print("CHECK 3 — Drawdown profile per window for top filters")
    print("=" * 110)

    top_filters = [fl for fl, _ in ranked[:3]]
    for flabel in top_filters:
        hours = dict(HOUR_FILTERS)[flabel]
        print(f"\n▶ Filter: {flabel}")
        print(f"  {'Window':<26}  {'N':>4}  {'WR%':>5}  {'Net R':>7}  {'MaxDD R':>8}  {'LossStreak':>10}  {'WinStreak':>9}")
        print(f"  " + "-" * 88)
        for win_label, _, trades in per_window:
            filtered = sorted(filter_hours(trades, hours), key=lambda t: t.entry_epoch)
            s  = stats(filtered)
            dd = drawdown(filtered)
            if not s or not dd:
                print(f"  {win_label:<26}  (no trades)")
                continue
            print(f"  {win_label:<26}  {s['n']:>4}  {s['wr']*100:>4.1f}%  "
                  f"{dd['final_r']:>+6.2f}R  {dd['max_dd_r']:>7.2f}R  "
                  f"{dd['max_loss_streak']:>10}  {dd['max_win_streak']:>9}")

        # Continuous equity across all 4 windows back-to-back
        all_trades = []
        for _, _, trades in per_window:
            all_trades.extend(filter_hours(trades, hours))
        all_trades.sort(key=lambda t: t.entry_epoch)
        dd_all = drawdown(all_trades)
        s_all  = stats(all_trades)
        if dd_all and s_all:
            print(f"  {'COMBINED (8 mo)':<26}  {s_all['n']:>4}  {s_all['wr']*100:>4.1f}%  "
                  f"{dd_all['final_r']:>+6.2f}R  {dd_all['max_dd_r']:>7.2f}R  "
                  f"{dd_all['max_loss_streak']:>10}  {dd_all['max_win_streak']:>9}")
            # $ context: 1R = SL_TICKS ticks × point × 0.5 lot tick_value
            broker_sl = max(SL_TICKS, STOPS_LEVEL + 2 * SPREAD + 10)
            r_dollar  = broker_sl * POINT * 0.5     # 1R in $ at 0.5 lot
            print(f"    $-frame ($100 acct, 0.5 lot, 1R={broker_sl}t = ${r_dollar:.2f}):")
            print(f"      Net P/L:    ${dd_all['final_r'] * r_dollar:+.2f}  ({dd_all['final_r']*r_dollar:+.0f}% of $100)")
            print(f"      Max DD:     ${dd_all['max_dd_r'] * r_dollar:.2f}     ({dd_all['max_dd_r']*r_dollar:.0f}% of $100)")
            print(f"      Trade rate: {s_all['n'] / (4*2):.1f} trades/month  (~{s_all['n']*12/8:.0f}/year)")
    print()


if __name__ == "__main__":
    asyncio.run(main())
