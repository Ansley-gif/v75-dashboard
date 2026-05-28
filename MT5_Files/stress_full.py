#!/usr/bin/env python3
"""
Comprehensive cross-window stress test.

PHASE A: Pattern 9 with extended wide-SL configs across 4 windows
PHASE B: Pattern 9 best config — session + hour breakdown across windows
PHASE C: All patterns × focused configs × 4 windows — find survivors

One fetch, three phases, full picture of where edge actually lives.
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

# ── Non-overlapping ~2-month windows (UTC) ────────────────────────────────
WINDOWS = [
    ("W1: 2025-09 to 2025-10", "2025-09-13", "2025-10-31"),
    ("W2: 2025-11 to 2025-12", "2025-11-01", "2025-12-31"),
    ("W3: 2026-01 to 2026-02", "2026-01-01", "2026-02-28"),
    ("W4: 2026-03 to 2026-04", "2026-03-01", "2026-04-30"),
]
WARMUP_DAYS = 2


def slice_window(bars, start_str, end_str, warmup_days=WARMUP_DAYS):
    start_dt   = datetime.fromisoformat(start_str).replace(tzinfo=timezone.utc)
    end_dt     = datetime.fromisoformat(end_str + "T23:59:59").replace(tzinfo=timezone.utc)
    real_start = int(start_dt.timestamp())
    warm_start = real_start - warmup_days * 86400
    end_epoch  = int(end_dt.timestamp())
    sliced     = [b for b in bars if warm_start <= b["epoch"] <= end_epoch]
    return sliced, real_start


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
    return dict(n=len(done), wr=wr, avg_rw=avg_rw, exp=exp)


def run_scan(scan_fn, scan_kwargs, sliced_bars, real_start, tp_ticks, sl_ticks):
    _broker_sl, sim_sl, sim_tp = compute_eff(tp_ticks, sl_ticks)
    trades = scan_fn(sliced_bars, sim_tp, sim_sl, POINT, **scan_kwargs)
    trades = [t for t in trades if t.entry_epoch >= real_start]
    PS.recompute_r_multiple_dollar(trades, tp_ticks, SPREAD, SLIPPAGE, POINT)
    return trades


def flag(pos, avg):
    if pos >= 3 and avg > 0.02:  return " ✓"
    if pos >= 2 and avg >= 0:    return "  "
    return " ✗"


async def main():
    print(f"Fetching {YEARS:.1f} year of {SYMBOL} M5 bars …")
    bars = await PS.fetch_history(SYMBOL, YEARS)
    if len(bars) < 1000:
        print("Not enough data.")
        return
    print(f"Got {len(bars):,} bars.\n")

    sliced = []
    for label, sd, ed in WINDOWS:
        sb, rs = slice_window(bars, sd, ed)
        sliced.append((label, sb, rs))
        print(f"  {label}: {len(sb):,} bars")
    print()

    win_hdr = "  ".join(f"{w[0][:14]:>14}" for w in WINDOWS)

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE A — Pattern 9 extended wide-SL configs
    # ═══════════════════════════════════════════════════════════════════════
    print("=" * 110)
    print("PHASE A — Pattern 9 (OC + ICT, M5 trigger): extended wide-SL configs")
    print("=" * 110)
    print(f"{'Config':<14}  {'$R:R':>5}  {'BE%':>5}  {win_hdr}  {'Pos':>4}  {'Avg Exp':>9}")
    print("-" * 110)

    P9_CONFIGS = [
        (500,  940),     # production baseline
        (500,  1330),    # design R:R 1.88
        (2000, 4000),    # Step 3 winner
        (2500, 5000),    # NEW: wider
        (3000, 6000),    # NEW: wider still
        (4000, 8000),    # NEW: very wide
        (2000, 6000),    # NEW: wide SL + extra TP
        (3000, 9000),    # NEW: wide SL + much more TP
    ]

    p9_results = {}
    for sl_t, tp_t in P9_CONFIGS:
        broker_sl, _, _ = compute_eff(tp_t, sl_t)
        rr = tp_t / broker_sl if broker_sl > 0 else 0.0
        be = 1.0 / (1.0 + rr) if rr > 0 else 0.0
        cells = []
        exps  = []
        for _, sb, rs in sliced:
            trades = run_scan(PS.scan_oc_break_ict, {"trigger": "m5"}, sb, rs, tp_t, sl_t)
            s = stats(trades)
            if s:
                cells.append(f"{s['wr']*100:4.1f}%/{s['exp']:+.2f}")
                exps.append(s['exp'])
            else:
                cells.append(f"{'—':>14}")
                exps.append(0.0)
        pos = sum(1 for e in exps if e > 0)
        avg = sum(exps) / len(exps) if exps else 0.0
        p9_results[(sl_t, tp_t)] = (exps, pos, avg)
        cfg = f"SL={sl_t}/TP={tp_t}"
        print(f"{cfg:<14}  {rr:>5.2f}  {be*100:>4.1f}%  "
              + "  ".join(f"{c:>14}" for c in cells)
              + f"  {pos}/{len(WINDOWS):<2}  {avg:>+7.3f}R{flag(pos, avg)}")

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE B — Best Pattern 9 config: session + hour breakdown
    # ═══════════════════════════════════════════════════════════════════════
    # Pick "best" = most positive windows, tiebreak by avg
    best_cfg = max(p9_results.items(), key=lambda kv: (kv[1][1], kv[1][2]))
    best_sl, best_tp = best_cfg[0]
    print()
    print("=" * 110)
    print(f"PHASE B — Pattern 9 session/hour breakdown for best config SL={best_sl}/TP={best_tp}")
    print("=" * 110)

    # Get trades per window once
    per_window_trades = []
    for win_label, sb, rs in sliced:
        trades = run_scan(PS.scan_oc_break_ict, {"trigger": "m5"}, sb, rs, best_tp, best_sl)
        per_window_trades.append((win_label, trades))

    # ── By session ──
    print(f"\nBy ICT session (ASIAN 22-09 UTC, LONDON 07-16, NY 13-22 — overlap allowed)")
    print(f"  {'Session':<10}  {win_hdr}  {'Pos':>4}  {'Avg Exp':>9}")
    print("  " + "-" * 108)
    for sess in ["ASIAN", "LONDON", "NY"]:
        cells = []
        exps  = []
        for _, trades in per_window_trades:
            s = stats([t for t in trades if t.session == sess])
            if s:
                cells.append(f"{s['wr']*100:4.1f}%/{s['exp']:+.2f}")
                exps.append(s['exp'])
            else:
                cells.append(f"{'—':>14}")
                exps.append(0.0)
        pos = sum(1 for e in exps if e > 0)
        avg = sum(exps) / len(exps) if exps else 0.0
        print(f"  {sess:<10}  " + "  ".join(f"{c:>14}" for c in cells)
              + f"  {pos}/{len(WINDOWS):<2}  {avg:>+7.3f}R{flag(pos, avg)}")

    # ── By hour (UTC) ──
    print(f"\nBy UTC hour (showing only hours with >=8 trades in EVERY window)")
    print(f"  {'Hour':<5}  {win_hdr}  {'Pos':>4}  {'Avg Exp':>9}")
    print("  " + "-" * 108)

    candidate_hours = []
    for h in range(24):
        ok = True
        for _, trades in per_window_trades:
            n = sum(1 for t in trades if t.hour == h and t.outcome in ("WIN", "LOSS"))
            if n < 8:
                ok = False
                break
        if ok:
            candidate_hours.append(h)

    hour_survivors = []
    for h in candidate_hours:
        cells = []
        exps  = []
        for _, trades in per_window_trades:
            s = stats([t for t in trades if t.hour == h])
            if s:
                cells.append(f"n{s['n']:>2} {s['wr']*100:4.1f}%/{s['exp']:+.2f}")
                exps.append(s['exp'])
            else:
                cells.append(f"{'—':>14}")
                exps.append(0.0)
        pos = sum(1 for e in exps if e > 0)
        avg = sum(exps) / len(exps) if exps else 0.0
        f_  = flag(pos, avg)
        if pos >= 3 and avg > 0.05:
            hour_survivors.append((h, pos, avg))
        print(f"  {h:02d}:00  " + "  ".join(f"{c:>14}" for c in cells)
              + f"  {pos}/{len(WINDOWS):<2}  {avg:>+7.3f}R{f_}")

    if hour_survivors:
        print(f"\n  → Hours with >=3/4 positive windows AND avg > 0.05R:")
        for h, p, a in hour_survivors:
            print(f"      {h:02d}:00 UTC  ({p}/4 positive, avg {a:+.3f}R)")
    else:
        print("\n  → No individual hour is reliably positive across windows.")

    # ═══════════════════════════════════════════════════════════════════════
    # PHASE C — All patterns × focused configs × windows
    # ═══════════════════════════════════════════════════════════════════════
    print()
    print("=" * 110)
    print("PHASE C — All patterns × focused configs across 4 windows")
    print("=" * 110)

    PATTERNS = [
        ("P1 SESS_BREAK",  PS.scan_session_breakout, {}),
        ("P3 NY_REV",      PS.scan_ny_reversal,      {}),
        ("P4 ORB",         PS.scan_orb,              {}),
        ("P6 PREV_RUN",    PS.scan_prev_session_run, {}),
        ("P7A OC_CANDLE",  PS.scan_oc_candle_break,  {"sl_mode": "candle"}),
        ("P7B OC_FIXED",   PS.scan_oc_candle_break,  {"sl_mode": "fixed"}),
        ("P7C OC_TIGHT",   PS.scan_oc_candle_break,  {"sl_mode": "tight"}),
        ("P9 OC_ICT_M5",   PS.scan_oc_break_ict,     {"trigger": "m5"}),
        ("P10 OC_ICT_H1",  PS.scan_oc_break_ict,     {"trigger": "h1"}),
    ]

    CONFIGS_PC = [
        (500,  940),
        (500,  3000),
        (2000, 4000),
        (3000, 6000),
    ]

    win_hdr_pc = "  ".join(f"{w[0][:12]:>12}" for w in WINDOWS)
    print(f"{'Pattern':<16}  {'Config':<14}  {'$R:R':>5}  {win_hdr_pc}  {'Pos':>4}  {'Avg Exp':>9}")
    print("-" * 110)

    survivors = []

    for name, fn, kwargs in PATTERNS:
        for sl_t, tp_t in CONFIGS_PC:
            broker_sl, _, _ = compute_eff(tp_t, sl_t)
            rr = tp_t / broker_sl if broker_sl > 0 else 0.0
            cells = []
            exps  = []
            for _, sb, rs in sliced:
                trades = run_scan(fn, kwargs, sb, rs, tp_t, sl_t)
                s = stats(trades)
                if s:
                    cells.append(f"{s['wr']*100:3.0f}%/{s['exp']:+.2f}")
                    exps.append(s['exp'])
                else:
                    cells.append(f"{'—':>12}")
                    exps.append(0.0)
            pos = sum(1 for e in exps if e > 0)
            avg = sum(exps) / len(exps) if exps else 0.0
            cfg = f"SL={sl_t}/TP={tp_t}"
            print(f"{name:<16}  {cfg:<14}  {rr:>5.2f}  "
                  + "  ".join(f"{c:>12}" for c in cells)
                  + f"  {pos}/{len(WINDOWS):<2}  {avg:>+7.3f}R{flag(pos, avg)}")
            if pos >= 3 and avg > 0.02:
                survivors.append((name, cfg, rr, pos, avg))
        print("-" * 110)

    # ── Survivors ──
    print()
    print("=" * 110)
    print("SURVIVORS (>= 3/4 positive windows AND avg exp > 0.02R)")
    print("=" * 110)
    if not survivors:
        print("  None. No pattern × config combination shows reliable cross-window edge.")
    else:
        for name, cfg, rr, pos, avg in sorted(survivors, key=lambda x: (-x[3], -x[4])):
            print(f"  {name:<16}  {cfg:<14}  $R:R={rr:.2f}  {pos}/4 positive  avg={avg:+.3f}R")
    print()


if __name__ == "__main__":
    asyncio.run(main())
