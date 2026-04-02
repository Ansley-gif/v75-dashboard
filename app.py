"""
V75 Behavioral Dashboard - Phase 1
Solid Gold Performance

A statistical behavior dashboard for Deriv's Volatility 75 Index.
Unlike macro-driven instruments, V75 is algorithmically generated.
We don't ask "what's moving price?" — we ask "how is this market behaving?"

Architecture:
- Flask web app with SQLite storage
- Deriv WebSocket API for real-time + historical data
- Multi-timeframe candle aggregation (1m, 5m, 15m, 1H, 4H)
- Market Regime Classification Engine
- Phase 1: Data pipeline + Market Regime Panel
"""

import os
import json
import time
import sqlite3
import threading
import logging
import asyncio
import websockets
import numpy as np
import pandas as pd
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, jsonify, request, send_from_directory
from functools import wraps
from collections import deque

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

APP_PORT = int(os.environ.get("V75_PORT", 8085))
DERIV_APP_ID = os.environ.get("DERIV_APP_ID", "1089")  # Default public app ID
DERIV_API_TOKEN = os.environ.get("DERIV_API_TOKEN", "")
DERIV_WS_URL = f"wss://ws.derivws.com/websockets/v3?app_id={DERIV_APP_ID}"
V75_SYMBOL = "R_75"  # Deriv symbol for Volatility 75

DB_PATH = os.path.join(os.path.dirname(__file__), "v75_data.db")

# Telegram notifications
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
TELEGRAM_ENABLED = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
# Only forward these severities (skip 'info' to avoid spam)
TELEGRAM_SEVERITIES = {"critical", "warning"}

# Timeframes we track (in seconds)
TIMEFRAMES = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
}

# Regime classification thresholds
REGIME_CONFIG = {
    "adx_trend_threshold": 25,       # ADX above this = trending
    "adx_weak_threshold": 15,        # ADX below this = no trend
    "atr_expansion_ratio": 1.5,      # Current ATR / Avg ATR above this = expanding
    "atr_compression_ratio": 0.6,    # Current ATR / Avg ATR below this = compressing
    "hurst_trend_threshold": 0.55,   # Hurst above this = trending
    "hurst_mr_threshold": 0.45,      # Hurst below this = mean-reverting
    "regime_lookback": 50,           # Bars for regime calculation
    "atr_period": 14,
    "adx_period": 14,
}

# V75-specific meta-analysis configuration
# V75 is an algorithmic synthetic index — traditional market thresholds don't apply
V75_META_CONFIG = {
    # ADX: V75 routinely produces ADX 100-400+. Traditional "25 = trending" is meaningless here.
    "adx_strong_trend": 200,
    "adx_extreme": 500,           # Above this = possible anomaly
    "adx_normal_range": (50, 400),

    # Hurst is still valid but V75 skews higher
    "hurst_trend": 0.58,
    "hurst_mr": 0.42,

    # Timeframe roles in hierarchical analysis
    "tf_roles": {
        "1h": "bias",        # Directional truth
        "15m": "structure",  # Confirms or leads bias
        "5m": "timing",      # Entry signals (may disagree temporarily — normal)
        "1m": "execution",   # Noise level — never use for conflict detection
    },

    # Additive alignment scoring weights (must sum to 100)
    "weights": {
        "tendency_accuracy": 35,
        "tf_hierarchy": 25,
        "regime_confidence": 20,
        "setup_alignment": 15,
        "alert_health": 5,
    },

    # Spike pattern tracking
    "spike_config": {
        "min_compressions_for_spike": 2,
        "spike_probability_base": 0.30,
        "spike_probability_per_compression": 0.15,
    },
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "v75_dashboard.log")),
    ],
)
log = logging.getLogger("v75")

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db():
    """Get a thread-local database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db():
    """Initialize database tables."""
    conn = get_db()
    # Candles table - stores OHLCV for all timeframes
    conn.execute("""
        CREATE TABLE IF NOT EXISTS candles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timeframe TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            tick_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(timeframe, timestamp)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_candles_tf_ts
        ON candles(timeframe, timestamp DESC)
    """)

    # Regime history - stores classified regimes over time
    conn.execute("""
        CREATE TABLE IF NOT EXISTS regime_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timeframe TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            regime TEXT NOT NULL,
            adx REAL,
            atr_ratio REAL,
            hurst REAL,
            autocorrelation REAL,
            confidence REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(timeframe, timestamp)
        )
    """)

    # Trades table - for Phase 3 performance tracking
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_time TEXT NOT NULL,
            exit_time TEXT,
            direction TEXT NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL,
            stop_loss REAL,
            take_profit REAL,
            position_size REAL,
            pnl REAL,
            regime_at_entry TEXT,
            setup_type TEXT,
            timeframe TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Trade log - Phase 3 performance tracker (full schema)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trade_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_time INTEGER NOT NULL,
            exit_time INTEGER,
            direction TEXT NOT NULL DEFAULT 'long',
            entry_price REAL NOT NULL,
            exit_price REAL,
            stop_loss REAL,
            take_profit REAL,
            pnl_points REAL DEFAULT 0,
            pnl_pct REAL DEFAULT 0,
            r_multiple REAL DEFAULT 0,
            result TEXT DEFAULT 'pending',
            regime TEXT DEFAULT '',
            sub_regime TEXT DEFAULT '',
            timeframe TEXT DEFAULT '',
            setup_type TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            risk_amount REAL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_trade_log_time
        ON trade_log(entry_time DESC)
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            alert_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'info',
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            timeframe TEXT DEFAULT '',
            data TEXT DEFAULT '{}',
            dismissed INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_alerts_time
        ON alerts(timestamp DESC)
    """)

    # --- Agent Memory System ---

    # Conversation history — remembers what was discussed
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            context_summary TEXT DEFAULT ''
        )
    """)

    # Agent observations — things the agent notices over time
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            category TEXT NOT NULL,
            observation TEXT NOT NULL,
            data TEXT DEFAULT '{}',
            relevance_score REAL DEFAULT 0.5,
            expires_at INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_agent_obs_cat
        ON agent_observations(category, timestamp DESC)
    """)

    # Statistical baselines — weekly snapshots for drift detection
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_baselines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start INTEGER NOT NULL,
            timeframe TEXT NOT NULL,
            avg_adx REAL, avg_hurst REAL, avg_atr_ratio REAL, avg_autocorr REAL,
            regime_distribution TEXT DEFAULT '{}',
            avg_streak_length REAL, avg_bb_width REAL,
            setup_success_rates TEXT DEFAULT '{}',
            sample_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(week_start, timeframe)
        )
    """)

    # Trade lessons — patterns the agent learns from trade outcomes
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_trade_lessons (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            lesson TEXT NOT NULL,
            evidence TEXT DEFAULT '{}',
            confidence REAL DEFAULT 0.5,
            times_confirmed INTEGER DEFAULT 1
        )
    """)

    # Scheduled reports — tracks when reports were last sent
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            report_type TEXT NOT NULL,
            content TEXT NOT NULL,
            sent_telegram INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
    log.info("Database initialized")


# ---------------------------------------------------------------------------
# Technical Indicators
# ---------------------------------------------------------------------------

def calc_ema(series, period):
    """Exponential Moving Average."""
    series = np.array(series, dtype=float)
    if len(series) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = np.zeros(len(series))
    ema[period - 1] = np.mean(series[:period])
    for i in range(period, len(series)):
        ema[i] = (series[i] - ema[i - 1]) * multiplier + ema[i - 1]
    return ema


def calc_ema_series(series, period):
    """Return full EMA array (with zeros for warmup period)."""
    return calc_ema(series, period)


def calc_rsi(closes, period=14):
    """
    Relative Strength Index.
    Returns (current_rsi, rsi_array) or (None, None).
    """
    closes = np.array(closes, dtype=float)
    if len(closes) < period + 2:
        return None, None

    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    rsi_values = np.full(len(closes), 50.0)

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_values[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi_values[i + 1] = 100 - (100 / (1 + rs))

    return float(rsi_values[-1]), rsi_values


def calc_sma(series, period):
    """Simple Moving Average — returns array with NaN for warmup."""
    series = np.array(series, dtype=float)
    if len(series) < period:
        return None
    sma = np.full(len(series), np.nan)
    for i in range(period - 1, len(series)):
        sma[i] = np.mean(series[i - period + 1:i + 1])
    return sma


def calc_bollinger_bands(closes, period=20, num_std=2):
    """
    Full Bollinger Bands — returns (upper, middle, lower, width, pct_b) arrays.
    pct_b = where price sits within the bands (0 = lower, 1 = upper).
    """
    closes = np.array(closes, dtype=float)
    if len(closes) < period:
        return None

    middle = calc_sma(closes, period)
    if middle is None:
        return None

    std = np.full(len(closes), np.nan)
    for i in range(period - 1, len(closes)):
        std[i] = np.std(closes[i - period + 1:i + 1], ddof=1)

    upper = middle + num_std * std
    lower = middle - num_std * std

    # Bandwidth (normalized)
    width = np.where(middle > 0, (upper - lower) / middle * 100, 0)

    # %B — where price is relative to bands
    band_range = upper - lower
    pct_b = np.where(band_range > 0, (closes - lower) / band_range, 0.5)

    return {
        "upper": upper,
        "lower": lower,
        "middle": middle,
        "width": width,
        "pct_b": pct_b,
    }


def calc_atr(highs, lows, closes, period=14):
    """Average True Range."""
    if len(closes) < period + 1:
        return None
    highs = np.array(highs, dtype=float)
    lows = np.array(lows, dtype=float)
    closes = np.array(closes, dtype=float)

    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1])
        )
    )
    if len(tr) < period:
        return None
    atr = np.mean(tr[-period:])
    return float(atr)


def calc_adx(highs, lows, closes, period=14):
    """Average Directional Index — measures trend strength."""
    n = len(closes)
    if n < period * 2 + 1:
        return None

    highs = np.array(highs, dtype=float)
    lows = np.array(lows, dtype=float)
    closes = np.array(closes, dtype=float)

    # True Range
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(
            np.abs(highs[1:] - closes[:-1]),
            np.abs(lows[1:] - closes[:-1])
        )
    )

    # Directional Movement
    up_move = highs[1:] - highs[:-1]
    down_move = lows[:-1] - lows[1:]

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    # Smoothed averages using Wilder's smoothing
    def wilder_smooth(data, period):
        smoothed = np.zeros(len(data))
        smoothed[period - 1] = np.sum(data[:period])
        for i in range(period, len(data)):
            smoothed[i] = smoothed[i - 1] - (smoothed[i - 1] / period) + data[i]
        return smoothed

    atr_smooth = wilder_smooth(tr, period)
    plus_dm_smooth = wilder_smooth(plus_dm, period)
    minus_dm_smooth = wilder_smooth(minus_dm, period)

    # Directional Indicators
    plus_di = np.zeros(len(tr))
    minus_di = np.zeros(len(tr))

    valid = atr_smooth > 0
    plus_di[valid] = 100 * plus_dm_smooth[valid] / atr_smooth[valid]
    minus_di[valid] = 100 * minus_dm_smooth[valid] / atr_smooth[valid]

    # DX
    di_sum = plus_di + minus_di
    di_diff = np.abs(plus_di - minus_di)
    dx = np.zeros(len(tr))
    valid_di = di_sum > 0
    dx[valid_di] = 100 * di_diff[valid_di] / di_sum[valid_di]

    # ADX = smoothed DX
    adx_values = wilder_smooth(dx[period - 1:], period)
    if len(adx_values) == 0:
        return None

    adx = adx_values[-1]
    return float(adx) if adx > 0 else None


def calc_hurst(series, max_lag=20):
    """
    Hurst Exponent via Rescaled Range analysis.
    H > 0.5 = trending (persistent)
    H = 0.5 = random walk
    H < 0.5 = mean-reverting (anti-persistent)
    """
    series = np.array(series, dtype=float)
    if len(series) < max_lag * 2:
        return None

    lags = range(2, max_lag + 1)
    rs_values = []

    for lag in lags:
        # Split into chunks
        n_chunks = len(series) // lag
        if n_chunks < 1:
            continue

        rs_chunk = []
        for i in range(n_chunks):
            chunk = series[i * lag:(i + 1) * lag]
            mean_chunk = np.mean(chunk)
            deviations = chunk - mean_chunk
            cumulative = np.cumsum(deviations)
            R = np.max(cumulative) - np.min(cumulative)
            S = np.std(chunk, ddof=1)
            if S > 0:
                rs_chunk.append(R / S)

        if rs_chunk:
            rs_values.append((np.log(lag), np.log(np.mean(rs_chunk))))

    if len(rs_values) < 3:
        return None

    x = np.array([v[0] for v in rs_values])
    y = np.array([v[1] for v in rs_values])

    # Linear regression to get Hurst exponent
    slope, _ = np.polyfit(x, y, 1)
    return float(np.clip(slope, 0, 1))


def calc_autocorrelation(series, lag=1):
    """Autocorrelation at given lag — measures if returns predict next returns."""
    series = np.array(series, dtype=float)
    if len(series) < lag + 10:
        return None
    returns = np.diff(series) / series[:-1]
    if len(returns) < lag + 2:
        return None
    n = len(returns)
    mean_r = np.mean(returns)
    denom = np.sum((returns - mean_r) ** 2)
    if denom == 0:
        return 0.0
    numer = np.sum((returns[:n - lag] - mean_r) * (returns[lag:] - mean_r))
    return float(numer / denom)


def calc_bollinger_bandwidth(closes, period=20):
    """Bollinger Band Width — measures compression/expansion."""
    if len(closes) < period:
        return None
    closes = np.array(closes[-period:], dtype=float)
    sma = np.mean(closes)
    std = np.std(closes, ddof=1)
    if sma == 0:
        return None
    bandwidth = (2 * 2 * std) / sma * 100  # 2 std devs
    return float(bandwidth)


def calc_streak_info(closes):
    """Analyze consecutive candle direction streaks."""
    if len(closes) < 3:
        return {"current_streak": 0, "direction": "none", "avg_streak": 0, "max_streak": 0}

    closes = np.array(closes, dtype=float)
    directions = np.sign(np.diff(closes))

    # Current streak
    current_dir = directions[-1]
    current_streak = 1
    for i in range(len(directions) - 2, -1, -1):
        if directions[i] == current_dir:
            current_streak += 1
        else:
            break

    # All streaks
    streaks = []
    s = 1
    for i in range(1, len(directions)):
        if directions[i] == directions[i - 1]:
            s += 1
        else:
            streaks.append(s)
            s = 1
    streaks.append(s)

    return {
        "current_streak": int(current_streak),
        "direction": "bullish" if current_dir > 0 else "bearish" if current_dir < 0 else "flat",
        "avg_streak": float(np.mean(streaks)) if streaks else 0,
        "max_streak": int(np.max(streaks)) if streaks else 0,
        "streak_std": float(np.std(streaks)) if len(streaks) > 1 else 0,
    }


# ---------------------------------------------------------------------------
# Regime Classification Engine
# ---------------------------------------------------------------------------

def classify_regime(candles_df, config=REGIME_CONFIG):
    """
    Classify the current market regime for V75.

    Returns dict with:
        regime: "trending" | "ranging" | "expanding" | "choppy"
        sub_regime: more specific classification
        confidence: 0-100
        metrics: all underlying values
    """
    if len(candles_df) < config["regime_lookback"]:
        return {
            "regime": "insufficient_data",
            "sub_regime": "waiting",
            "confidence": 0,
            "metrics": {},
        }

    closes = candles_df["close"].values
    highs = candles_df["high"].values
    lows = candles_df["low"].values

    # Calculate all indicators
    adx = calc_adx(highs, lows, closes, config["adx_period"])
    atr_current = calc_atr(highs, lows, closes, config["atr_period"])
    atr_long = calc_atr(highs, lows, closes, config["regime_lookback"])
    hurst = calc_hurst(closes)
    autocorr = calc_autocorrelation(closes)
    bb_width = calc_bollinger_bandwidth(closes)
    streak = calc_streak_info(closes)

    atr_ratio = (atr_current / atr_long) if (atr_current and atr_long and atr_long > 0) else 1.0

    # Scoring system — each indicator votes
    trend_score = 0
    range_score = 0
    expand_score = 0
    chop_score = 0

    # ADX vote
    if adx is not None:
        if adx >= config["adx_trend_threshold"]:
            trend_score += 2
        elif adx <= config["adx_weak_threshold"]:
            range_score += 1
            chop_score += 1
        else:
            range_score += 0.5

    # ATR ratio vote
    if atr_ratio >= config["atr_expansion_ratio"]:
        expand_score += 2
    elif atr_ratio <= config["atr_compression_ratio"]:
        range_score += 2
    else:
        pass  # neutral

    # Hurst vote
    if hurst is not None:
        if hurst >= config["hurst_trend_threshold"]:
            trend_score += 2
        elif hurst <= config["hurst_mr_threshold"]:
            range_score += 1.5
        else:
            chop_score += 1

    # Autocorrelation vote
    if autocorr is not None:
        if abs(autocorr) > 0.3:
            trend_score += 1
        elif abs(autocorr) < 0.1:
            chop_score += 1.5

    # Determine regime by highest score
    scores = {
        "trending": trend_score,
        "ranging": range_score,
        "expanding": expand_score,
        "choppy": chop_score,
    }
    regime = max(scores, key=scores.get)
    max_score = scores[regime]
    total_score = sum(scores.values())
    confidence = (max_score / total_score * 100) if total_score > 0 else 0

    # Sub-regime classification
    sub_regime = regime
    if regime == "trending":
        # Determine direction
        sma_20 = np.mean(closes[-20:])
        sma_50 = np.mean(closes[-min(50, len(closes)):])
        if closes[-1] > sma_20 > sma_50:
            sub_regime = "trending_up"
        elif closes[-1] < sma_20 < sma_50:
            sub_regime = "trending_down"
        else:
            sub_regime = "trending_mixed"
    elif regime == "ranging":
        if atr_ratio <= config["atr_compression_ratio"]:
            sub_regime = "compressing"
        else:
            sub_regime = "ranging_normal"
    elif regime == "expanding":
        if streak["current_streak"] >= 3:
            sub_regime = "breakout_run"
        else:
            sub_regime = "volatility_spike"

    return {
        "regime": regime,
        "sub_regime": sub_regime,
        "confidence": round(confidence, 1),
        "metrics": {
            "adx": round(adx, 2) if adx else None,
            "atr_current": round(atr_current, 4) if atr_current else None,
            "atr_ratio": round(atr_ratio, 3),
            "hurst": round(hurst, 3) if hurst else None,
            "autocorrelation": round(autocorr, 4) if autocorr else None,
            "bb_width": round(bb_width, 4) if bb_width else None,
            "streak": streak,
        },
        "scores": {k: round(v, 1) for k, v in scores.items()},
    }


# ---------------------------------------------------------------------------
# Tendency Engine (Phase 2 — Panel B)
# ---------------------------------------------------------------------------
# Replaces manual seasonal/quarterly chart analysis with statistical profiling.
# Every time dimension is measured: hour, weekday, month, quarter, session.
# Each bucket gets a directional bias, volatility profile, trend quality score,
# and statistical significance (z-score) so you know what's real vs noise.
# ---------------------------------------------------------------------------

def _bucket_candle_stats(timestamps, opens, highs, lows, closes, bucket_fn, bucket_labels):
    """
    Core engine: groups candles by a time-bucket function, then calculates
    statistical profiles for each bucket.

    bucket_fn: takes a datetime → returns bucket key (e.g. hour, weekday)
    bucket_labels: dict mapping bucket key → display label
    """
    from collections import defaultdict
    import math

    buckets = defaultdict(lambda: {"returns": [], "ranges": [], "closes": []})

    for i in range(1, len(closes)):
        ts = datetime.fromtimestamp(timestamps[i], tz=timezone.utc)
        key = bucket_fn(ts)
        ret = (closes[i] - closes[i - 1]) / closes[i - 1] if closes[i - 1] != 0 else 0
        rng = (highs[i] - lows[i]) / closes[i] if closes[i] != 0 else 0
        buckets[key]["returns"].append(ret)
        buckets[key]["ranges"].append(rng)
        buckets[key]["closes"].append(closes[i])

    # Global stats for z-score calculation
    all_returns = []
    for b in buckets.values():
        all_returns.extend(b["returns"])
    global_mean = float(np.mean(all_returns)) if all_returns else 0
    global_std = float(np.std(all_returns)) if len(all_returns) > 1 else 1

    result = []
    for key in sorted(bucket_labels.keys()):
        data = buckets.get(key)
        if not data or len(data["returns"]) < 3:
            result.append({
                "bucket": key,
                "label": bucket_labels[key],
                "sample_size": 0,
                "avg_return_pct": 0,
                "volatility": 0,
                "bullish_pct": 0,
                "bearish_pct": 0,
                "z_score": 0,
                "significance": "none",
                "trend_quality": 0,
                "avg_range_pct": 0,
            })
            continue

        rets = np.array(data["returns"])
        ranges = np.array(data["ranges"])
        n = len(rets)
        avg_ret = float(np.mean(rets))
        vol = float(np.std(rets))
        bullish_pct = float(np.sum(rets > 0) / n * 100)
        bearish_pct = float(np.sum(rets < 0) / n * 100)
        avg_range = float(np.mean(ranges))

        # Z-score: how far this bucket's mean is from the global mean
        se = global_std / math.sqrt(n) if n > 0 and global_std > 0 else 1
        z = (avg_ret - global_mean) / se if se > 0 else 0

        # Significance bands
        if abs(z) >= 2.58:
            sig = "very_high"     # 99% confidence
        elif abs(z) >= 1.96:
            sig = "high"          # 95% confidence
        elif abs(z) >= 1.645:
            sig = "moderate"      # 90% confidence
        else:
            sig = "low"

        # Trend quality: directional consistency × magnitude
        # High = strong bias in one direction. Low = choppy/mixed.
        directional_bias = abs(bullish_pct - 50) / 50  # 0-1
        if vol > 0:
            sharpe_like = abs(avg_ret) / vol
        else:
            sharpe_like = 0
        trend_quality = float(np.clip(directional_bias * 0.5 + min(sharpe_like, 1) * 0.5, 0, 1))

        result.append({
            "bucket": key,
            "label": bucket_labels[key],
            "sample_size": n,
            "avg_return_pct": round(avg_ret * 100, 5),
            "volatility": round(vol * 100, 5),
            "bullish_pct": round(bullish_pct, 1),
            "bearish_pct": round(bearish_pct, 1),
            "z_score": round(float(z), 3),
            "significance": sig,
            "trend_quality": round(trend_quality, 3),
            "avg_range_pct": round(avg_range * 100, 5),
        })

    return result


def calc_hourly_tendency(timestamps, opens, highs, lows, closes):
    """Profile each hour of the day (0-23 UTC)."""
    labels = {h: f"{h:02d}:00" for h in range(24)}
    return _bucket_candle_stats(
        timestamps, opens, highs, lows, closes,
        bucket_fn=lambda dt: dt.hour,
        bucket_labels=labels,
    )


def calc_weekday_tendency(timestamps, opens, highs, lows, closes):
    """Profile each day of the week (Mon=0 .. Sun=6)."""
    day_names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
    return _bucket_candle_stats(
        timestamps, opens, highs, lows, closes,
        bucket_fn=lambda dt: dt.weekday(),
        bucket_labels=day_names,
    )


def calc_monthly_tendency(timestamps, opens, highs, lows, closes):
    """
    Seasonal tendency per calendar month — statistical replacement for
    manual color-coded seasonal zones on monthly charts.
    """
    month_names = {
        1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
        7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
    }
    return _bucket_candle_stats(
        timestamps, opens, highs, lows, closes,
        bucket_fn=lambda dt: dt.month,
        bucket_labels=month_names,
    )


def calc_quarterly_tendency(timestamps, opens, highs, lows, closes):
    """
    Quarterly cycle analysis — detects behavioral patterns across Q1-Q4
    and within-quarter phases (early/mid/late).
    Replaces manual quarterly shift lines on charts.
    """
    # Quarterly buckets
    q_labels = {1: "Q1", 2: "Q2", 3: "Q3", 4: "Q4"}
    quarterly = _bucket_candle_stats(
        timestamps, opens, highs, lows, closes,
        bucket_fn=lambda dt: (dt.month - 1) // 3 + 1,
        bucket_labels=q_labels,
    )

    # Within-quarter phase: early (month 1), mid (month 2), late (month 3)
    phase_labels = {
        "Q1_early": "Q1 Early (Jan)", "Q1_mid": "Q1 Mid (Feb)", "Q1_late": "Q1 Late (Mar)",
        "Q2_early": "Q2 Early (Apr)", "Q2_mid": "Q2 Mid (May)", "Q2_late": "Q2 Late (Jun)",
        "Q3_early": "Q3 Early (Jul)", "Q3_mid": "Q3 Mid (Aug)", "Q3_late": "Q3 Late (Sep)",
        "Q4_early": "Q4 Early (Oct)", "Q4_mid": "Q4 Mid (Nov)", "Q4_late": "Q4 Late (Dec)",
    }

    def quarter_phase(dt):
        q = (dt.month - 1) // 3 + 1
        phase_idx = (dt.month - 1) % 3
        phase = ["early", "mid", "late"][phase_idx]
        return f"Q{q}_{phase}"

    phases = _bucket_candle_stats(
        timestamps, opens, highs, lows, closes,
        bucket_fn=quarter_phase,
        bucket_labels=phase_labels,
    )

    # Quarter transition detection: compare last 5 days of quarter vs first 5 days
    transitions = []
    for i in range(1, len(closes)):
        ts = datetime.fromtimestamp(timestamps[i], tz=timezone.utc)
        # Last 5 days of a quarter month (Mar, Jun, Sep, Dec)
        if ts.month in (3, 6, 9, 12) and ts.day >= 26:
            transitions.append({"type": "pre_shift", "return": (closes[i] - closes[i-1]) / closes[i-1] if closes[i-1] else 0})
        # First 5 days of a quarter month (Jan, Apr, Jul, Oct)
        elif ts.month in (1, 4, 7, 10) and ts.day <= 5:
            transitions.append({"type": "post_shift", "return": (closes[i] - closes[i-1]) / closes[i-1] if closes[i-1] else 0})

    pre_rets = [t["return"] for t in transitions if t["type"] == "pre_shift"]
    post_rets = [t["return"] for t in transitions if t["type"] == "post_shift"]

    shift_analysis = {
        "pre_shift_avg_return": round(float(np.mean(pre_rets)) * 100, 5) if pre_rets else 0,
        "pre_shift_volatility": round(float(np.std(pre_rets)) * 100, 5) if len(pre_rets) > 1 else 0,
        "post_shift_avg_return": round(float(np.mean(post_rets)) * 100, 5) if post_rets else 0,
        "post_shift_volatility": round(float(np.std(post_rets)) * 100, 5) if len(post_rets) > 1 else 0,
        "pre_shift_samples": len(pre_rets),
        "post_shift_samples": len(post_rets),
    }

    return {
        "quarterly": quarterly,
        "phases": phases,
        "shift_analysis": shift_analysis,
    }


def calc_session_tendency(timestamps, opens, highs, lows, closes):
    """
    Session-based analysis. Even though V75 is synthetic 24/7,
    the algorithm may exhibit different behavior patterns aligned
    with global trading sessions.
    """
    session_labels = {
        "asian":       "Asian (00-08 UTC)",
        "london":      "London (08-16 UTC)",
        "new_york":    "New York (13-21 UTC)",
        "late_ny":     "Late NY / Off-hours (21-00 UTC)",
        "ldn_ny_overlap": "LDN/NY Overlap (13-16 UTC)",
    }

    def session_bucket(dt):
        h = dt.hour
        if 13 <= h < 16:
            return "ldn_ny_overlap"
        elif 0 <= h < 8:
            return "asian"
        elif 8 <= h < 16:
            return "london"
        elif 16 <= h < 21:
            return "new_york"
        else:
            return "late_ny"

    return _bucket_candle_stats(
        timestamps, opens, highs, lows, closes,
        bucket_fn=session_bucket,
        bucket_labels=session_labels,
    )


def calc_rolling_tendency(timestamps, closes, windows=(20, 40, 60)):
    """
    Rolling directional bias over 20/40/60-bar windows.
    Replaces manual liquidity projection lines with measured momentum.
    """
    closes = np.array(closes, dtype=float)
    results = {}

    for w in windows:
        if len(closes) < w + 1:
            results[f"{w}_bar"] = {
                "return_pct": 0, "direction": "neutral",
                "strength": 0, "consistency": 0,
            }
            continue

        window_closes = closes[-w:]
        window_rets = np.diff(window_closes) / window_closes[:-1]

        total_return = (window_closes[-1] - window_closes[0]) / window_closes[0]
        bullish_bars = float(np.sum(window_rets > 0))
        consistency = bullish_bars / len(window_rets) if len(window_rets) > 0 else 0.5

        # Direction and strength
        if total_return > 0.001:
            direction = "bullish"
        elif total_return < -0.001:
            direction = "bearish"
        else:
            direction = "neutral"

        # Strength: magnitude × consistency (0-1 scale)
        vol = float(np.std(window_rets)) if len(window_rets) > 1 else 0.001
        magnitude = min(abs(total_return) / (vol * np.sqrt(w) + 1e-10), 1.0)
        dir_consistency = abs(consistency - 0.5) * 2  # 0 = even split, 1 = all one direction
        strength = float(np.clip(magnitude * 0.6 + dir_consistency * 0.4, 0, 1))

        results[f"{w}_bar"] = {
            "return_pct": round(float(total_return) * 100, 4),
            "direction": direction,
            "strength": round(strength, 3),
            "consistency": round(float(consistency) * 100, 1),
            "bullish_bars": int(bullish_bars),
            "total_bars": len(window_rets),
        }

    return results


def calc_current_tendency_summary(hourly, weekday, session, rolling):
    """
    Synthesize all tendency data into a single actionable summary:
    'Right now, what does the tendency data say?'
    """
    now = datetime.now(timezone.utc)
    current_hour = now.hour
    current_day = now.weekday()

    # Find current hour's profile
    hour_profile = next((h for h in hourly if h["bucket"] == current_hour), None)
    day_profile = next((d for d in weekday if d["bucket"] == current_day), None)

    # Current session
    if 13 <= current_hour < 16:
        sess_key = "ldn_ny_overlap"
    elif 0 <= current_hour < 8:
        sess_key = "asian"
    elif 8 <= current_hour < 16:
        sess_key = "london"
    elif 16 <= current_hour < 21:
        sess_key = "new_york"
    else:
        sess_key = "late_ny"
    session_profile = next((s for s in session if s["bucket"] == sess_key), None)

    # Score the current window (simple composite)
    scores = []
    if hour_profile and hour_profile["sample_size"] > 0:
        scores.append(hour_profile["trend_quality"])
    if day_profile and day_profile["sample_size"] > 0:
        scores.append(day_profile["trend_quality"])
    if session_profile and session_profile["sample_size"] > 0:
        scores.append(session_profile["trend_quality"])

    # Directional consensus
    biases = []
    for p in [hour_profile, day_profile, session_profile]:
        if p and p["sample_size"] > 0:
            if p["bullish_pct"] > 55:
                biases.append("bullish")
            elif p["bearish_pct"] > 55:
                biases.append("bearish")
            else:
                biases.append("neutral")

    # Rolling momentum consensus
    rolling_dirs = [v["direction"] for v in rolling.values()]

    # Overall tendency
    bullish_votes = biases.count("bullish") + rolling_dirs.count("bullish")
    bearish_votes = biases.count("bearish") + rolling_dirs.count("bearish")
    total_votes = len(biases) + len(rolling_dirs)

    if total_votes == 0:
        tendency = "neutral"
        tendency_strength = 0
    elif bullish_votes > bearish_votes:
        tendency = "bullish"
        tendency_strength = round(bullish_votes / total_votes, 2)
    elif bearish_votes > bullish_votes:
        tendency = "bearish"
        tendency_strength = round(bearish_votes / total_votes, 2)
    else:
        tendency = "neutral"
        tendency_strength = 0

    return {
        "current_hour": hour_profile,
        "current_day": day_profile,
        "current_session": session_profile,
        "rolling_momentum": rolling,
        "tendency": tendency,
        "tendency_strength": tendency_strength,
        "window_quality": round(float(np.mean(scores)), 3) if scores else 0,
        "consensus_detail": {
            "time_biases": biases,
            "rolling_biases": rolling_dirs,
            "bullish_votes": bullish_votes,
            "bearish_votes": bearish_votes,
        },
    }


# ---------------------------------------------------------------------------
# Setup Scanner Engine (Phase 2 — Panel C)
# ---------------------------------------------------------------------------
# Detects 5 specific trade setups and scores each for:
#   - Confidence (0-100): how cleanly the pattern is formed
#   - Regime compatibility: how well it fits the current market regime
#   - Composite score: confidence × regime compatibility
#   - Specific entry/invalidation context
# ---------------------------------------------------------------------------

# Setup-regime compatibility matrix:
# Each setup type has regimes where it works best, works okay, or is dangerous
SETUP_REGIME_COMPAT = {
    "compression_breakout": {
        "best":    ["ranging", "compressing"],      # compression precedes breakout
        "okay":    ["choppy", "ranging_normal"],
        "avoid":   ["trending", "trending_up", "trending_down", "expanding", "breakout_run"],
    },
    "pullback_to_trend": {
        "best":    ["trending", "trending_up", "trending_down"],
        "okay":    ["trending_mixed"],
        "avoid":   ["ranging", "choppy", "compressing", "expanding"],
    },
    "mean_reversion": {
        "best":    ["ranging", "ranging_normal", "choppy"],
        "okay":    ["compressing"],
        "avoid":   ["trending", "trending_up", "trending_down", "expanding", "breakout_run"],
    },
    "streak_exhaustion": {
        "best":    ["trending", "trending_up", "trending_down", "breakout_run"],
        "okay":    ["expanding", "volatility_spike"],
        "avoid":   ["ranging", "choppy", "compressing"],
    },
    "order_block_touch": {
        "best":    ["trending", "trending_up", "trending_down", "ranging_normal"],
        "okay":    ["expanding", "trending_mixed"],
        "avoid":   ["choppy", "volatility_spike"],
    },
}


def score_regime_compatibility(setup_type, regime, sub_regime):
    """
    Score how compatible a detected setup is with the current regime.
    Returns 0.0-1.0 (1.0 = ideal conditions).
    """
    compat = SETUP_REGIME_COMPAT.get(setup_type, {})
    best = compat.get("best", [])
    okay = compat.get("okay", [])
    avoid = compat.get("avoid", [])

    # Check sub_regime first (more specific), then regime
    for label in [sub_regime, regime]:
        if label in best:
            return 1.0
        if label in okay:
            return 0.6
        if label in avoid:
            return 0.2

    return 0.5  # unknown regime → neutral


def detect_compression_breakout(closes, highs, lows, bb_data, atr_current, atr_long):
    """
    Compression Breakout: Bollinger Bands squeeze to historical tight →
    price breaks outside band. The tighter the squeeze, the bigger the move.

    Detection logic:
    1. BB width drops below 20th percentile of recent history → compression phase
    2. Price closes outside upper or lower band → breakout trigger
    3. ATR ratio confirms expansion is beginning
    """
    if bb_data is None or len(closes) < 40:
        return None

    width = bb_data["width"]
    pct_b = bb_data["pct_b"]
    upper = bb_data["upper"]
    lower = bb_data["lower"]

    # Get recent valid widths
    valid_widths = width[~np.isnan(width)]
    if len(valid_widths) < 20:
        return None

    current_width = float(valid_widths[-1])
    width_percentile = float(np.sum(valid_widths < current_width) / len(valid_widths) * 100)

    # Is compressed? (below 25th percentile)
    is_compressed = width_percentile < 25

    # Breakout detection: price at or beyond bands
    current_pct_b = float(pct_b[-1])
    prev_pct_b = float(pct_b[-2]) if len(pct_b) > 1 else 0.5
    breakout_up = current_pct_b > 0.95 and closes[-1] > upper[-1]
    breakout_down = current_pct_b < 0.05 and closes[-1] < lower[-1]
    breakout = breakout_up or breakout_down

    # ATR expansion starting?
    atr_ratio = (atr_current / atr_long) if (atr_current and atr_long and atr_long > 0) else 1.0
    expansion_starting = atr_ratio > 0.85

    if not is_compressed and not breakout:
        return None

    # Confidence scoring
    confidence = 0

    # Tighter compression = higher confidence (max 35 pts)
    if width_percentile < 5:
        confidence += 35
    elif width_percentile < 10:
        confidence += 30
    elif width_percentile < 15:
        confidence += 25
    elif width_percentile < 25:
        confidence += 18

    # Breakout happening = big confidence boost (max 35 pts)
    if breakout:
        confidence += 35
        # Strength of breakout
        if breakout_up and current_pct_b > 1.1:
            confidence += 10  # strong breakout
        elif breakout_down and current_pct_b < -0.1:
            confidence += 10
    else:
        # Just compressed, no breakout yet — potential setup
        confidence += 5

    # ATR expansion confirmation (max 15 pts)
    if atr_ratio > 1.3:
        confidence += 15
    elif atr_ratio > 1.1:
        confidence += 10
    elif expansion_starting:
        confidence += 5

    # Volume of squeeze (how long compressed — measured by consecutive tight candles)
    squeeze_bars = 0
    for i in range(len(valid_widths) - 1, max(0, len(valid_widths) - 20), -1):
        if np.sum(valid_widths[:i+1] < valid_widths[i]) / (i + 1) * 100 < 30:
            squeeze_bars += 1
        else:
            break
    if squeeze_bars >= 8:
        confidence += 5

    confidence = min(confidence, 100)

    direction = "bullish" if breakout_up else "bearish" if breakout_down else "pending"
    stage = "breakout" if breakout else "compression"

    return {
        "type": "compression_breakout",
        "name": "Compression Breakout",
        "active": True,
        "stage": stage,
        "direction": direction,
        "confidence": confidence,
        "details": {
            "bb_width": round(current_width, 4),
            "width_percentile": round(width_percentile, 1),
            "pct_b": round(current_pct_b, 3),
            "atr_ratio": round(atr_ratio, 3),
            "squeeze_bars": squeeze_bars,
        },
        "context": f"BB width at {width_percentile:.0f}th pctl"
                   + (f" — {'BULLISH' if breakout_up else 'BEARISH'} breakout in progress"
                      if breakout else " — squeeze building, watch for break"),
    }


def detect_pullback_to_trend(closes, highs, lows, adx_value):
    """
    Pullback to Trend: In a trending market (ADX > 25), price pulls back
    to the 20 EMA and finds support/resistance — classic continuation entry.

    Detection logic:
    1. ADX > 25 confirms trend exists
    2. Determine direction via 20 EMA vs 50 EMA
    3. Price has retraced to touch or penetrate 20 EMA zone
    4. Candle shows rejection (wick) at the EMA
    """
    if len(closes) < 55 or adx_value is None:
        return None

    closes_arr = np.array(closes, dtype=float)
    highs_arr = np.array(highs, dtype=float)
    lows_arr = np.array(lows, dtype=float)

    ema20 = calc_ema(closes_arr, 20)
    ema50 = calc_ema(closes_arr, 50)
    if ema20 is None or ema50 is None:
        return None

    current_close = closes_arr[-1]
    current_ema20 = float(ema20[-1])
    current_ema50 = float(ema50[-1])

    # Trend must be present
    if adx_value < 22:
        return None

    # Determine trend direction
    if current_ema20 > current_ema50:
        trend_dir = "bullish"
    elif current_ema20 < current_ema50:
        trend_dir = "bearish"
    else:
        return None

    # Distance from 20 EMA (as % of price)
    ema_dist_pct = (current_close - current_ema20) / current_ema20 * 100

    # Pullback zone: price should be near the 20 EMA
    # For bullish trend: price should be within -0.3% to +0.5% of EMA
    # For bearish trend: price should be within -0.5% to +0.3% of EMA
    if trend_dir == "bullish":
        in_zone = -0.4 <= ema_dist_pct <= 0.5
        # Wick rejection: low touches EMA zone but close is above
        wick_rejection = lows_arr[-1] <= current_ema20 * 1.002 and current_close > current_ema20
    else:
        in_zone = -0.5 <= ema_dist_pct <= 0.4
        wick_rejection = highs_arr[-1] >= current_ema20 * 0.998 and current_close < current_ema20

    if not in_zone:
        return None

    # Confidence scoring
    confidence = 0

    # ADX strength (max 30 pts)
    if adx_value > 40:
        confidence += 30
    elif adx_value > 30:
        confidence += 25
    elif adx_value > 25:
        confidence += 18
    else:
        confidence += 12

    # Proximity to EMA (max 25 pts — closer = better)
    abs_dist = abs(ema_dist_pct)
    if abs_dist < 0.1:
        confidence += 25
    elif abs_dist < 0.2:
        confidence += 20
    elif abs_dist < 0.3:
        confidence += 15
    else:
        confidence += 8

    # Wick rejection (max 25 pts)
    if wick_rejection:
        confidence += 25

    # EMA slope alignment (max 15 pts)
    if len(ema20) > 3:
        ema_slope = (ema20[-1] - ema20[-3]) / ema20[-3] * 100
        if trend_dir == "bullish" and ema_slope > 0.05:
            confidence += 15
        elif trend_dir == "bearish" and ema_slope < -0.05:
            confidence += 15
        elif abs(ema_slope) > 0.02:
            confidence += 8

    # Recent retracement depth (max 5 pts bonus)
    # Check if price came from a recent swing away from EMA
    recent_max_dist = max(abs((closes_arr[-i] - ema20[-i]) / ema20[-i] * 100)
                         for i in range(1, min(6, len(closes_arr))))
    if recent_max_dist > 0.3:
        confidence += 5  # confirms actual pullback, not just hugging

    confidence = min(confidence, 100)

    return {
        "type": "pullback_to_trend",
        "name": "Pullback to Trend",
        "active": True,
        "stage": "rejection" if wick_rejection else "approaching",
        "direction": trend_dir,
        "confidence": confidence,
        "details": {
            "adx": round(adx_value, 1),
            "ema20": round(current_ema20, 2),
            "ema50": round(current_ema50, 2),
            "ema_distance_pct": round(ema_dist_pct, 3),
            "wick_rejection": wick_rejection,
        },
        "context": f"{'Bullish' if trend_dir == 'bullish' else 'Bearish'} trend (ADX {adx_value:.0f})"
                   + (f" — wick rejection at 20 EMA" if wick_rejection else f" — price at 20 EMA zone ({ema_dist_pct:+.2f}%)"),
    }


def detect_mean_reversion(closes, highs, lows, rsi_value, hurst_value, bb_data):
    """
    Mean Reversion: RSI extreme + Hurst < 0.5 confirms mean-reverting regime.
    Price at Bollinger Band extreme provides the entry context.

    Detection logic:
    1. Hurst < 0.5 confirms anti-persistent / mean-reverting behavior
    2. RSI at extreme (< 25 or > 75)
    3. Price at BB band extreme (%B < 0.05 or > 0.95)
    """
    if rsi_value is None or hurst_value is None or bb_data is None:
        return None

    if len(closes) < 30:
        return None

    # Hurst must confirm mean-reversion tendency
    if hurst_value >= 0.50:
        return None

    pct_b = float(bb_data["pct_b"][-1])

    # RSI extreme check
    rsi_oversold = rsi_value < 28
    rsi_overbought = rsi_value > 72
    if not (rsi_oversold or rsi_overbought):
        return None

    direction = "bullish" if rsi_oversold else "bearish"

    # Confidence scoring
    confidence = 0

    # Hurst mean-reversion strength (max 30 pts)
    if hurst_value < 0.3:
        confidence += 30
    elif hurst_value < 0.4:
        confidence += 22
    else:
        confidence += 14

    # RSI extremity (max 30 pts)
    if rsi_value < 15 or rsi_value > 85:
        confidence += 30
    elif rsi_value < 20 or rsi_value > 80:
        confidence += 25
    elif rsi_value < 25 or rsi_value > 75:
        confidence += 18
    else:
        confidence += 12

    # BB confirmation (max 25 pts)
    if direction == "bullish" and pct_b < 0.05:
        confidence += 25
    elif direction == "bearish" and pct_b > 0.95:
        confidence += 25
    elif direction == "bullish" and pct_b < 0.15:
        confidence += 15
    elif direction == "bearish" and pct_b > 0.85:
        confidence += 15
    else:
        confidence += 5

    # Divergence check: price making lower low but RSI making higher low (or vice versa)
    # Simplified: compare last 5 candle RSI trend vs price trend
    if len(closes) >= 5:
        price_change = closes[-1] - closes[-5]
        # A rough divergence signal
        if direction == "bullish" and price_change < 0 and rsi_value > 20:
            confidence += 10  # bearish price but RSI not as extreme → divergence
        elif direction == "bearish" and price_change > 0 and rsi_value < 80:
            confidence += 10

    confidence = min(confidence, 100)

    return {
        "type": "mean_reversion",
        "name": "Mean Reversion",
        "active": True,
        "stage": "extreme",
        "direction": direction,
        "confidence": confidence,
        "details": {
            "rsi": round(rsi_value, 1),
            "hurst": round(hurst_value, 3),
            "pct_b": round(pct_b, 3),
        },
        "context": f"RSI {'oversold' if rsi_oversold else 'overbought'} ({rsi_value:.0f})"
                   + f" | Hurst {hurst_value:.2f} confirms mean-reversion"
                   + f" | Price at {'lower' if pct_b < 0.5 else 'upper'} BB ({pct_b:.2f})",
    }


def detect_streak_exhaustion(closes, streak_info):
    """
    Streak Exhaustion: Current directional streak exceeds 2 standard deviations
    of normal streak length → likely exhaustion / reversal imminent.

    Detection logic:
    1. Current streak length > mean + 2σ of historical streaks
    2. Longer the streak beyond threshold, higher the exhaustion probability
    """
    if not streak_info or streak_info["avg_streak"] == 0:
        return None

    current = streak_info["current_streak"]
    avg = streak_info["avg_streak"]
    std = streak_info.get("streak_std", 0)
    max_streak = streak_info["max_streak"]
    direction = streak_info["direction"]

    if direction == "flat":
        return None

    # Exhaustion threshold: mean + 1.5σ (more sensitive) to catch early
    threshold_early = avg + 1.5 * std if std > 0 else avg * 2
    threshold_strong = avg + 2.0 * std if std > 0 else avg * 2.5

    if current < threshold_early:
        return None

    # Confidence scoring
    confidence = 0

    # How far beyond threshold (max 40 pts)
    if std > 0:
        z_streak = (current - avg) / std
        if z_streak >= 3.0:
            confidence += 40
        elif z_streak >= 2.5:
            confidence += 35
        elif z_streak >= 2.0:
            confidence += 28
        else:
            confidence += 18
    else:
        if current >= avg * 3:
            confidence += 35
        elif current >= avg * 2.5:
            confidence += 25
        else:
            confidence += 15

    # Approaching historical max (max 25 pts)
    if max_streak > 0:
        pct_of_max = current / max_streak
        if pct_of_max >= 0.9:
            confidence += 25
        elif pct_of_max >= 0.75:
            confidence += 18
        elif pct_of_max >= 0.6:
            confidence += 10

    # Momentum fading: check if recent candle ranges are shrinking (max 20 pts)
    if len(closes) >= current + 1:
        streak_closes = closes[-(current + 1):]
        streak_returns = [abs(streak_closes[i+1] - streak_closes[i]) / streak_closes[i]
                         for i in range(len(streak_closes) - 1)]
        if len(streak_returns) >= 3:
            first_half = np.mean(streak_returns[:len(streak_returns)//2])
            second_half = np.mean(streak_returns[len(streak_returns)//2:])
            if first_half > 0 and second_half / first_half < 0.6:
                confidence += 20  # momentum clearly fading
            elif first_half > 0 and second_half / first_half < 0.8:
                confidence += 10

    # Absolute streak length bonus (max 15 pts)
    if current >= 8:
        confidence += 15
    elif current >= 6:
        confidence += 10
    elif current >= 5:
        confidence += 5

    confidence = min(confidence, 100)

    # Reversal direction is opposite to streak
    reversal_dir = "bearish" if direction == "bullish" else "bullish"

    return {
        "type": "streak_exhaustion",
        "name": "Streak Exhaustion",
        "active": True,
        "stage": "exhausting",
        "direction": reversal_dir,  # expected reversal direction
        "confidence": confidence,
        "details": {
            "current_streak": current,
            "streak_direction": direction,
            "avg_streak": round(avg, 1),
            "streak_std": round(std, 2),
            "max_streak": max_streak,
            "z_score": round((current - avg) / std, 2) if std > 0 else 0,
        },
        "context": f"{current}-bar {direction} streak"
                   + f" (avg {avg:.1f} ± {std:.1f}, max {max_streak})"
                   + f" — exhaustion signal, watch for {reversal_dir} reversal",
    }


def detect_order_block_touch(closes, highs, lows, volumes=None):
    """
    Order Block Touch: Identifies institutional reaction zones (large-body
    candles followed by displacement) and detects when price returns to test them.

    Detection logic:
    1. Scan recent history for "order blocks" — large candles that created
       a strong move away (displacement)
    2. Check if current price has returned to that zone
    3. Higher confidence if price wicks into zone but doesn't close through it
    """
    if len(closes) < 50:
        return None

    closes_arr = np.array(closes, dtype=float)
    highs_arr = np.array(highs, dtype=float)
    lows_arr = np.array(lows, dtype=float)

    # Calculate candle bodies
    opens_approx = np.roll(closes_arr, 1)  # approximate open as previous close
    opens_approx[0] = closes_arr[0]
    bodies = np.abs(closes_arr - opens_approx)
    ranges = highs_arr - lows_arr

    # Average body and range for calibration
    avg_body = np.mean(bodies[-50:])
    avg_range = np.mean(ranges[-50:])

    if avg_body == 0 or avg_range == 0:
        return None

    # Scan for order blocks (look back 10-40 candles)
    order_blocks = []

    for i in range(max(10, len(closes) - 40), len(closes) - 3):
        body_i = bodies[i]
        is_bullish_ob = closes_arr[i] > opens_approx[i]
        is_bearish_ob = closes_arr[i] < opens_approx[i]

        # Must be a large candle (> 1.5x average body)
        if body_i < avg_body * 1.5:
            continue

        # Must have displacement after it (next 1-3 candles continue strongly)
        displacement = 0
        for j in range(1, min(4, len(closes) - i)):
            displacement += closes_arr[i + j] - closes_arr[i + j - 1]

        if is_bullish_ob and displacement > avg_range * 1.0:
            # Bullish OB — zone is the low to open of the OB candle
            ob_top = max(opens_approx[i], closes_arr[i])
            ob_bottom = lows_arr[i]
            order_blocks.append({
                "type": "bullish",
                "top": ob_top,
                "bottom": ob_bottom,
                "candle_idx": i,
                "strength": body_i / avg_body,
                "displacement": displacement / avg_range,
            })
        elif is_bearish_ob and displacement < -avg_range * 1.0:
            # Bearish OB — zone is the high to open of the OB candle
            ob_top = highs_arr[i]
            ob_bottom = min(opens_approx[i], closes_arr[i])
            order_blocks.append({
                "type": "bearish",
                "top": ob_top,
                "bottom": ob_bottom,
                "candle_idx": i,
                "strength": body_i / avg_body,
                "displacement": abs(displacement) / avg_range,
            })

    if not order_blocks:
        return None

    # Check if current price is at any order block
    current_price = closes_arr[-1]
    current_high = highs_arr[-1]
    current_low = lows_arr[-1]

    best_ob = None
    best_confidence = 0

    for ob in order_blocks:
        # Is price in or near the OB zone?
        zone_height = ob["top"] - ob["bottom"]
        zone_margin = zone_height * 0.3  # 30% margin outside the zone

        in_zone = (ob["bottom"] - zone_margin) <= current_price <= (ob["top"] + zone_margin)
        wick_into = (current_low <= ob["top"] and current_low >= ob["bottom"]) or \
                    (current_high >= ob["bottom"] and current_high <= ob["top"])

        if not (in_zone or wick_into):
            continue

        # Confidence scoring
        confidence = 0

        # OB strength (max 25 pts)
        if ob["strength"] > 3:
            confidence += 25
        elif ob["strength"] > 2:
            confidence += 20
        else:
            confidence += 14

        # Displacement strength (max 20 pts)
        if ob["displacement"] > 2:
            confidence += 20
        elif ob["displacement"] > 1.5:
            confidence += 15
        else:
            confidence += 10

        # First touch is best (max 20 pts)
        bars_since = len(closes) - 1 - ob["candle_idx"]
        if bars_since > 5:  # must be a real return, not the immediate aftermath
            confidence += 20
        elif bars_since > 3:
            confidence += 12

        # Wick rejection (max 20 pts)
        if wick_into:
            if ob["type"] == "bullish" and current_price > (ob["bottom"] + ob["top"]) / 2:
                confidence += 20  # wicked in but closed above midpoint
            elif ob["type"] == "bearish" and current_price < (ob["bottom"] + ob["top"]) / 2:
                confidence += 20
            else:
                confidence += 10

        # Precise zone touch vs. just near (max 15 pts)
        if ob["bottom"] <= current_price <= ob["top"]:
            confidence += 15
        else:
            confidence += 5

        confidence = min(confidence, 100)

        if confidence > best_confidence:
            best_confidence = confidence
            best_ob = ob
            best_ob["confidence"] = confidence
            best_ob["wick_rejection"] = wick_into

    if best_ob is None:
        return None

    direction = best_ob["type"]  # bullish OB → expect bullish bounce

    return {
        "type": "order_block_touch",
        "name": "Order Block Touch",
        "active": True,
        "stage": "testing",
        "direction": direction,
        "confidence": best_ob["confidence"],
        "details": {
            "ob_type": best_ob["type"],
            "ob_top": round(best_ob["top"], 2),
            "ob_bottom": round(best_ob["bottom"], 2),
            "ob_strength": round(best_ob["strength"], 2),
            "displacement": round(best_ob["displacement"], 2),
            "wick_rejection": best_ob["wick_rejection"],
            "bars_since_ob": len(closes) - 1 - best_ob["candle_idx"],
        },
        "context": f"Price testing {'bullish' if direction == 'bullish' else 'bearish'} OB"
                   + f" at {best_ob['bottom']:.2f}-{best_ob['top']:.2f}"
                   + (" — wick rejection" if best_ob["wick_rejection"] else " — in zone"),
    }


def scan_all_setups(closes, highs, lows, regime_data):
    """
    Master scanner: runs all 5 detectors, scores regime compatibility,
    and returns sorted list of active setups.
    """
    closes_arr = np.array(closes, dtype=float)
    highs_arr = np.array(highs, dtype=float)
    lows_arr = np.array(lows, dtype=float)

    regime = regime_data.get("regime", "unknown")
    sub_regime = regime_data.get("sub_regime", "unknown")

    # Pre-compute shared indicators
    bb = calc_bollinger_bands(closes_arr, 20, 2)
    atr_current = calc_atr(highs_arr, lows_arr, closes_arr, 14)
    atr_long = calc_atr(highs_arr, lows_arr, closes_arr, 50)
    adx = calc_adx(highs_arr, lows_arr, closes_arr, 14)
    hurst = calc_hurst(closes_arr)
    rsi_val, _ = calc_rsi(closes_arr, 14)
    streak = calc_streak_info(closes_arr)

    # Run all detectors (each wrapped to prevent one failure from killing the scan)
    detectors = [
        ("compression_breakout", lambda: detect_compression_breakout(closes_arr, highs_arr, lows_arr, bb, atr_current, atr_long)),
        ("pullback_to_trend", lambda: detect_pullback_to_trend(closes_arr, highs_arr, lows_arr, adx)),
        ("mean_reversion", lambda: detect_mean_reversion(closes_arr, highs_arr, lows_arr, rsi_val, hurst, bb)),
        ("streak_exhaustion", lambda: detect_streak_exhaustion(closes_arr, streak)),
        ("order_block_touch", lambda: detect_order_block_touch(closes_arr, highs_arr, lows_arr)),
    ]

    raw_setups = []
    for name, fn in detectors:
        try:
            raw_setups.append(fn())
        except Exception as e:
            log.warning(f"Detector {name} failed: {e}")
            raw_setups.append(None)

    active_setups = []
    for setup in raw_setups:
        if setup is None:
            continue

        # Score regime compatibility
        compat = score_regime_compatibility(setup["type"], regime, sub_regime)
        composite = round(setup["confidence"] * compat, 1)

        setup["regime_compatibility"] = round(compat, 2)
        setup["composite_score"] = composite
        setup["regime_label"] = f"{regime}/{sub_regime}"

        # Compatibility tag
        if compat >= 0.9:
            setup["regime_tag"] = "IDEAL"
        elif compat >= 0.5:
            setup["regime_tag"] = "OKAY"
        else:
            setup["regime_tag"] = "CAUTION"

        active_setups.append(setup)

    # Sort by composite score descending
    active_setups.sort(key=lambda s: s["composite_score"], reverse=True)

    return active_setups


# ---------------------------------------------------------------------------
# Risk Module (Phase 3 — Panel D)
# ---------------------------------------------------------------------------
# ATR-based stop calculator, volatility-adjusted position sizing,
# trade frequency governor, and drawdown-aware risk scaling.
# ---------------------------------------------------------------------------

RISK_CONFIG = {
    "default_account_balance": 1000.0,    # overridden by user input
    "default_risk_pct": 1.0,              # % of account per trade
    "max_risk_pct": 5.0,                  # hard cap
    "min_risk_pct": 0.25,                 # floor
    "atr_stop_multipliers": {
        "tight": 1.0,
        "normal": 1.5,
        "wide": 2.0,
    },
    "vol_scaling": {
        # When ATR ratio > threshold, scale risk DOWN by this factor
        "high_vol_threshold": 1.4,
        "high_vol_scale": 0.5,
        "elevated_vol_threshold": 1.15,
        "elevated_vol_scale": 0.75,
        "low_vol_threshold": 0.7,
        "low_vol_scale": 1.25,            # slightly larger in low vol
    },
    "frequency_governor": {
        "max_trades_per_session": 3,       # per 8-hour session
        "max_trades_per_day": 6,
        "cooldown_after_loss_streak": 2,   # pause X trades after 3 consecutive losses
    },
}


def calc_atr_stop(highs, lows, closes, multiplier="normal", atr_period=14):
    """
    Calculate ATR-based stop-loss distance.
    Returns stop distance in price units and as % of current price.
    """
    atr = calc_atr(
        np.array(highs, dtype=float),
        np.array(lows, dtype=float),
        np.array(closes, dtype=float),
        atr_period,
    )
    if atr is None or atr == 0:
        return {"stop_distance": 0, "stop_pct": 0, "atr": 0, "multiplier": multiplier}

    mult = RISK_CONFIG["atr_stop_multipliers"].get(multiplier, 1.5)
    stop_dist = atr * mult
    current_price = float(closes[-1]) if len(closes) > 0 else 1
    stop_pct = (stop_dist / current_price) * 100 if current_price > 0 else 0

    return {
        "stop_distance": round(float(stop_dist), 2),
        "stop_pct": round(float(stop_pct), 4),
        "atr": round(float(atr), 4),
        "multiplier": multiplier,
        "mult_value": mult,
        "current_price": round(current_price, 2),
        "stop_long": round(current_price - stop_dist, 2),
        "stop_short": round(current_price + stop_dist, 2),
    }


def calc_position_size(account_balance, risk_pct, stop_distance, current_price):
    """
    Calculate position size based on account balance, risk %, and stop distance.
    Returns lot size / units and dollar risk.
    """
    if stop_distance <= 0 or current_price <= 0:
        return {
            "risk_amount": 0, "position_units": 0,
            "position_lots": 0, "effective_risk_pct": 0,
        }

    risk_amount = account_balance * (risk_pct / 100)
    # For synthetic indices: position_units = risk_amount / stop_distance
    position_units = risk_amount / stop_distance
    # Standard lot for V75 = 1 unit per 0.01 lot (approximate)
    position_lots = position_units

    return {
        "risk_amount": round(float(risk_amount), 2),
        "position_units": round(float(position_units), 4),
        "position_lots": round(float(position_lots), 4),
        "effective_risk_pct": round(float(risk_pct), 2),
    }


def calc_volatility_adjusted_risk(base_risk_pct, highs, lows, closes):
    """
    Scale risk % based on current volatility relative to average.
    High vol → smaller position. Low vol → slightly larger.
    """
    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)
    c = np.array(closes, dtype=float)

    atr_current = calc_atr(h, l, c, 14)
    atr_long = calc_atr(h, l, c, 50)

    if atr_current is None or atr_long is None or atr_long == 0:
        return {
            "adjusted_risk_pct": base_risk_pct,
            "vol_condition": "unknown",
            "scale_factor": 1.0,
            "atr_ratio": 1.0,
        }

    atr_ratio = float(atr_current / atr_long)
    vs = RISK_CONFIG["vol_scaling"]

    if atr_ratio >= vs["high_vol_threshold"]:
        scale = vs["high_vol_scale"]
        condition = "HIGH — reduce size"
    elif atr_ratio >= vs["elevated_vol_threshold"]:
        scale = vs["elevated_vol_scale"]
        condition = "ELEVATED — caution"
    elif atr_ratio <= vs["low_vol_threshold"]:
        scale = vs["low_vol_scale"]
        condition = "LOW — compression"
    else:
        scale = 1.0
        condition = "NORMAL"

    adjusted = base_risk_pct * scale
    adjusted = max(RISK_CONFIG["min_risk_pct"], min(adjusted, RISK_CONFIG["max_risk_pct"]))

    return {
        "adjusted_risk_pct": round(float(adjusted), 2),
        "base_risk_pct": round(float(base_risk_pct), 2),
        "vol_condition": condition,
        "scale_factor": round(float(scale), 2),
        "atr_ratio": round(float(atr_ratio), 3),
        "atr_current": round(float(atr_current), 4),
        "atr_long": round(float(atr_long), 4),
    }


def calc_trade_frequency_status(conn):
    """
    Trade frequency governor: checks recent trade count against limits.
    Returns whether trading is allowed and reason if not.
    """
    now = datetime.now(timezone.utc)

    # Count trades in current session (last 8 hours)
    session_start = int((now - timedelta(hours=8)).timestamp())
    session_trades = conn.execute(
        "SELECT COUNT(*) FROM trade_log WHERE entry_time >= ?",
        (session_start,),
    ).fetchone()[0]

    # Count trades today
    day_start = int(now.replace(hour=0, minute=0, second=0).timestamp())
    day_trades = conn.execute(
        "SELECT COUNT(*) FROM trade_log WHERE entry_time >= ?",
        (day_start,),
    ).fetchone()[0]

    # Check for loss streak
    recent_trades = conn.execute(
        "SELECT result FROM trade_log ORDER BY entry_time DESC LIMIT 5",
    ).fetchall()
    consecutive_losses = 0
    for t in recent_trades:
        if t["result"] == "loss":
            consecutive_losses += 1
        else:
            break

    gov = RISK_CONFIG["frequency_governor"]
    allowed = True
    reasons = []

    if session_trades >= gov["max_trades_per_session"]:
        allowed = False
        reasons.append(f"Session limit reached ({session_trades}/{gov['max_trades_per_session']})")

    if day_trades >= gov["max_trades_per_day"]:
        allowed = False
        reasons.append(f"Daily limit reached ({day_trades}/{gov['max_trades_per_day']})")

    if consecutive_losses >= 3:
        allowed = False
        reasons.append(f"Loss streak cooldown ({consecutive_losses} consecutive losses)")

    return {
        "allowed": allowed,
        "session_trades": int(session_trades),
        "session_limit": gov["max_trades_per_session"],
        "day_trades": int(day_trades),
        "day_limit": gov["max_trades_per_day"],
        "consecutive_losses": consecutive_losses,
        "reasons": reasons,
    }


def calc_risk_summary(highs, lows, closes, account_balance, risk_pct, stop_type, conn):
    """
    Full risk module output: combines stop calc, position sizing,
    vol adjustment, and frequency governor into one response.
    """
    # ATR stop
    stop = calc_atr_stop(highs, lows, closes, multiplier=stop_type)

    # Vol-adjusted risk
    vol_risk = calc_volatility_adjusted_risk(risk_pct, highs, lows, closes)
    effective_risk = vol_risk["adjusted_risk_pct"]

    # Position size using vol-adjusted risk
    position = calc_position_size(
        account_balance, effective_risk,
        stop["stop_distance"], stop["current_price"],
    )

    # All three stop levels for comparison
    stops = {}
    for st in ["tight", "normal", "wide"]:
        s = calc_atr_stop(highs, lows, closes, multiplier=st)
        p = calc_position_size(account_balance, effective_risk, s["stop_distance"], s["current_price"])
        stops[st] = {**s, "position": p}

    # Frequency governor
    frequency = calc_trade_frequency_status(conn)

    # Risk-reward targets (1:2 and 1:3)
    rr_targets = {}
    if stop["stop_distance"] > 0:
        for ratio in [1.5, 2.0, 3.0]:
            tp_dist = stop["stop_distance"] * ratio
            rr_targets[f"1:{ratio:.1f}"] = {
                "tp_distance": round(float(tp_dist), 2),
                "tp_long": round(float(stop["current_price"] + tp_dist), 2),
                "tp_short": round(float(stop["current_price"] - tp_dist), 2),
            }

    return {
        "stop": stop,
        "position": position,
        "vol_adjustment": vol_risk,
        "all_stops": stops,
        "frequency": frequency,
        "rr_targets": rr_targets,
        "account_balance": account_balance,
    }


# ---------------------------------------------------------------------------
# Performance Tracker (Phase 3 — Panel E)
# ---------------------------------------------------------------------------
# Trade logging, performance analytics by regime and time,
# win rate, expectancy, profit factor, and drawdown tracking.
# ---------------------------------------------------------------------------

def log_trade(conn, trade_data):
    """
    Log a completed trade to the database.
    trade_data: dict with entry_time, exit_time, direction, entry_price,
                exit_price, stop_loss, take_profit, regime, timeframe, setup_type
    """
    entry = float(trade_data.get("entry_price", 0))
    exit_p = float(trade_data.get("exit_price", 0))
    direction = trade_data.get("direction", "long")
    risk_amount = float(trade_data.get("risk_amount", 0))

    # Calculate P&L
    if direction == "long":
        pnl_points = exit_p - entry
    else:
        pnl_points = entry - exit_p

    pnl_pct = (pnl_points / entry * 100) if entry > 0 else 0
    result = "win" if pnl_points > 0 else "loss" if pnl_points < 0 else "breakeven"

    # R-multiple (how many R's gained/lost)
    sl = float(trade_data.get("stop_loss", 0))
    if direction == "long":
        risk_distance = entry - sl if sl > 0 else 0
    else:
        risk_distance = sl - entry if sl > 0 else 0
    r_multiple = (pnl_points / risk_distance) if risk_distance > 0 else 0

    conn.execute(
        """INSERT INTO trade_log
           (entry_time, exit_time, direction, entry_price, exit_price,
            stop_loss, take_profit, pnl_points, pnl_pct, r_multiple,
            result, regime, sub_regime, timeframe, setup_type, notes, risk_amount)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            trade_data.get("entry_time", int(datetime.now(timezone.utc).timestamp())),
            trade_data.get("exit_time", int(datetime.now(timezone.utc).timestamp())),
            direction,
            entry,
            exit_p,
            sl,
            float(trade_data.get("take_profit", 0)),
            round(pnl_points, 4),
            round(pnl_pct, 4),
            round(r_multiple, 3),
            result,
            trade_data.get("regime", ""),
            trade_data.get("sub_regime", ""),
            trade_data.get("timeframe", ""),
            trade_data.get("setup_type", ""),
            trade_data.get("notes", ""),
            risk_amount,
        ),
    )
    conn.commit()


def calc_performance_stats(trades):
    """
    Calculate comprehensive performance statistics from trade list.
    """
    if not trades:
        return _empty_performance()

    n = len(trades)
    wins = [t for t in trades if t["result"] == "win"]
    losses = [t for t in trades if t["result"] == "loss"]
    n_wins = len(wins)
    n_losses = len(losses)

    win_rate = (n_wins / n * 100) if n > 0 else 0

    # P&L
    total_pnl = sum(t["pnl_points"] for t in trades)
    total_pnl_pct = sum(t["pnl_pct"] for t in trades)
    avg_win = np.mean([t["pnl_points"] for t in wins]) if wins else 0
    avg_loss = np.mean([abs(t["pnl_points"]) for t in losses]) if losses else 0

    # Profit factor
    gross_profit = sum(t["pnl_points"] for t in wins) if wins else 0
    gross_loss = abs(sum(t["pnl_points"] for t in losses)) if losses else 0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0

    # Expectancy (avg pnl per trade in R-multiples)
    r_multiples = [t["r_multiple"] for t in trades if t["r_multiple"] != 0]
    avg_r = float(np.mean(r_multiples)) if r_multiples else 0
    expectancy = avg_r

    # Drawdown (equity curve based on pnl_pct)
    equity = [0]
    for t in trades:
        equity.append(equity[-1] + t["pnl_pct"])
    equity = np.array(equity)
    running_max = np.maximum.accumulate(equity)
    drawdowns = equity - running_max
    max_drawdown = float(np.min(drawdowns)) if len(drawdowns) > 1 else 0

    # Streaks
    current_streak = 0
    max_win_streak = 0
    max_loss_streak = 0
    temp_streak = 0
    for t in trades:
        if t["result"] == "win":
            if temp_streak > 0:
                temp_streak += 1
            else:
                temp_streak = 1
            max_win_streak = max(max_win_streak, temp_streak)
        elif t["result"] == "loss":
            if temp_streak < 0:
                temp_streak -= 1
            else:
                temp_streak = -1
            max_loss_streak = max(max_loss_streak, abs(temp_streak))
        else:
            temp_streak = 0
    current_streak = temp_streak

    return {
        "total_trades": n,
        "wins": n_wins,
        "losses": n_losses,
        "win_rate": round(float(win_rate), 1),
        "total_pnl_points": round(float(total_pnl), 2),
        "total_pnl_pct": round(float(total_pnl_pct), 2),
        "avg_win": round(float(avg_win), 2),
        "avg_loss": round(float(avg_loss), 2),
        "profit_factor": round(float(profit_factor), 2) if profit_factor != float("inf") else "∞",
        "expectancy_r": round(float(expectancy), 3),
        "max_drawdown_pct": round(float(max_drawdown), 2),
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "current_streak": current_streak,
        "avg_r_multiple": round(float(avg_r), 3),
    }


def _empty_performance():
    return {
        "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0,
        "total_pnl_points": 0, "total_pnl_pct": 0, "avg_win": 0, "avg_loss": 0,
        "profit_factor": 0, "expectancy_r": 0, "max_drawdown_pct": 0,
        "max_win_streak": 0, "max_loss_streak": 0, "current_streak": 0,
        "avg_r_multiple": 0,
    }


def calc_performance_by_regime(trades):
    """Break down performance statistics by market regime."""
    from collections import defaultdict
    regime_groups = defaultdict(list)
    for t in trades:
        regime_groups[t.get("regime", "unknown")].append(t)

    return {regime: calc_performance_stats(group) for regime, group in regime_groups.items()}


def calc_performance_by_time(trades):
    """Break down performance by hour, day, session."""
    from collections import defaultdict

    by_hour = defaultdict(list)
    by_day = defaultdict(list)
    by_session = defaultdict(list)

    day_names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}

    for t in trades:
        ts = datetime.fromtimestamp(t["entry_time"], tz=timezone.utc)
        by_hour[ts.hour].append(t)
        by_day[day_names.get(ts.weekday(), "?")].append(t)

        h = ts.hour
        if 0 <= h < 8:
            by_session["Asian"].append(t)
        elif 8 <= h < 16:
            by_session["London"].append(t)
        elif 16 <= h < 21:
            by_session["New York"].append(t)
        else:
            by_session["Off-hours"].append(t)

    return {
        "by_hour": {str(h): calc_performance_stats(g) for h, g in sorted(by_hour.items())},
        "by_day": {d: calc_performance_stats(g) for d, g in by_day.items()},
        "by_session": {s: calc_performance_stats(g) for s, g in by_session.items()},
    }


def calc_performance_by_setup(trades):
    """Break down performance by setup type."""
    from collections import defaultdict
    setup_groups = defaultdict(list)
    for t in trades:
        setup_groups[t.get("setup_type", "unknown")].append(t)

    return {setup: calc_performance_stats(group) for setup, group in setup_groups.items()}


# ---------------------------------------------------------------------------
# Alert Engine (Phase 4 — Panel F)
# ---------------------------------------------------------------------------
# Continuous monitoring system that generates alerts when actionable
# conditions are detected. Alerts are persisted to DB and pushed to
# the frontend via polling. Each alert has a type, severity, message,
# and cooldown to prevent spam.
# ---------------------------------------------------------------------------

ALERT_CONFIG = {
    "cooldowns": {
        # Minimum seconds between alerts of the same type+timeframe
        "regime_shift": 300,         # 5 min
        "compression_forming": 600,  # 10 min
        "compression_ready": 300,    # 5 min
        "time_window": 1800,         # 30 min
        "overtrading": 900,          # 15 min
        "streak_exhaustion": 300,    # 5 min
        "volatility_spike": 300,     # 5 min
        "momentum_shift": 300,       # 5 min
    },
    "max_alerts_displayed": 50,
    "bb_compression_warn": 0.25,     # BB width percentile to start warning
    "bb_compression_ready": 0.12,    # BB width percentile for "ready" alert
}

# In-memory last-alert timestamps for cooldown enforcement
_alert_cooldowns = {}


def _check_cooldown(alert_type, timeframe):
    """Return True if enough time has passed since last alert of this type."""
    key = f"{alert_type}:{timeframe}"
    now = datetime.now(timezone.utc).timestamp()
    last = _alert_cooldowns.get(key, 0)
    cooldown = ALERT_CONFIG["cooldowns"].get(alert_type, 300)
    if now - last < cooldown:
        return False
    _alert_cooldowns[key] = now
    return True


def _store_alert(conn, alert_type, severity, title, message, timeframe, details=None):
    """Persist an alert to the database."""
    conn.execute(
        """INSERT INTO alerts
           (timestamp, alert_type, severity, title, message, timeframe, details, acknowledged)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
        (
            int(datetime.now(timezone.utc).timestamp()),
            alert_type,
            severity,
            title,
            message,
            timeframe,
            json.dumps(details or {}),
        ),
    )
    conn.commit()


def check_regime_shift(conn, timeframe, current_regime, previous_regime):
    """
    Alert when market regime changes.
    High severity for trending→choppy or expanding→ranging.
    Medium for other transitions.
    """
    if not previous_regime or current_regime == previous_regime:
        return None
    if not _check_cooldown("regime_shift", timeframe):
        return None

    # Severity based on transition type
    dangerous_shifts = {
        ("trending", "choppy"), ("trending_up", "choppy"),
        ("trending_down", "choppy"), ("expanding", "ranging"),
        ("breakout_run", "choppy"), ("breakout_run", "ranging"),
    }
    curr = current_regime.get("regime", "")
    sub = current_regime.get("sub_regime", "")
    prev = previous_regime.get("regime", "")
    prev_sub = previous_regime.get("sub_regime", "")

    if (prev, curr) in dangerous_shifts or (prev_sub, sub) in dangerous_shifts:
        severity = "high"
    elif curr in ("trending", "expanding"):
        severity = "medium"
    else:
        severity = "low"

    title = f"Regime Shift: {prev.upper()} → {curr.upper()}"
    message = (
        f"{timeframe.upper()}: Market shifted from {prev_sub or prev} to {sub or curr}. "
        f"Confidence: {current_regime.get('confidence', 0)}%"
    )

    _store_alert(conn, "regime_shift", severity, title, message, timeframe, {
        "from_regime": prev, "from_sub": prev_sub,
        "to_regime": curr, "to_sub": sub,
        "confidence": current_regime.get("confidence", 0),
    })
    return {"type": "regime_shift", "severity": severity, "title": title}


def check_compression_alert(conn, timeframe, closes, highs, lows):
    """
    Alert when Bollinger Bands are squeezing — compression forming or ready.
    """
    if len(closes) < 30:
        return None

    closes_arr = np.array(closes, dtype=float)
    bb = calc_bollinger_bands(closes_arr, 20, 2)
    if bb is None:
        return None

    _, bb_upper, bb_lower = bb
    current_width = (bb_upper - bb_lower) / closes_arr[-1] if closes_arr[-1] > 0 else 0

    # Historical widths for percentile
    widths = []
    for i in range(20, len(closes_arr)):
        w_bb = calc_bollinger_bands(closes_arr[:i+1], 20, 2)
        if w_bb:
            _, wu, wl = w_bb
            w = (wu - wl) / closes_arr[i] if closes_arr[i] > 0 else 0
            widths.append(w)

    if len(widths) < 10:
        return None

    percentile = float(np.sum(np.array(widths) <= current_width) / len(widths))

    if percentile <= ALERT_CONFIG["bb_compression_ready"]:
        if not _check_cooldown("compression_ready", timeframe):
            return None
        severity = "high"
        title = f"Compression READY — {timeframe.upper()}"
        message = (
            f"BB width at {percentile*100:.0f}th percentile — extreme squeeze. "
            f"Breakout imminent. Watch for direction confirmation."
        )
        alert_type = "compression_ready"
    elif percentile <= ALERT_CONFIG["bb_compression_warn"]:
        if not _check_cooldown("compression_forming", timeframe):
            return None
        severity = "medium"
        title = f"Compression Forming — {timeframe.upper()}"
        message = (
            f"BB width at {percentile*100:.0f}th percentile — squeeze developing. "
            f"Prepare for potential breakout setup."
        )
        alert_type = "compression_forming"
    else:
        return None

    _store_alert(conn, alert_type, severity, title, message, timeframe, {
        "bb_width": round(float(current_width), 6),
        "percentile": round(float(percentile * 100), 1),
    })
    return {"type": alert_type, "severity": severity, "title": title}


def check_time_window_alert(conn):
    """
    Alert when a historically high-performance time window is approaching.
    Uses tendency data to identify best hours/sessions.
    """
    if not _check_cooldown("time_window", "global"):
        return None

    now = datetime.now(timezone.utc)
    current_hour = now.hour

    # Check if we have tendency data to reference
    data = _get_candle_arrays("1h", limit=500)
    if data is None:
        return None

    timestamps, opens, highs, lows, closes = data
    hourly = calc_hourly_tendency(timestamps, opens, highs, lows, closes)

    # Find best hours (high significance + strong directional bias)
    best_hours = [
        h for h in hourly
        if h["significance"] in ("high", "very_high")
        and h["trend_quality"] >= 0.5
        and h["sample_size"] >= 10
    ]

    if not best_hours:
        return None

    # Check if any best hour is coming up in the next 1-2 hours
    upcoming = [
        h for h in best_hours
        if h["bucket"] in (current_hour + 1, (current_hour + 2) % 24)
    ]

    if not upcoming:
        return None

    best = max(upcoming, key=lambda h: h["trend_quality"])
    bias = "Bullish" if best["bullish_pct"] > 55 else "Bearish" if best["bullish_pct"] < 45 else "Active"

    title = f"High-Performance Window: {best['label']} UTC"
    message = (
        f"{bias} tendency ({best['bullish_pct']:.0f}% bull) with "
        f"{best['significance'].replace('_', ' ')} significance. "
        f"Trend quality: {best['trend_quality']:.2f}"
    )

    _store_alert(conn, "time_window", "medium", title, message, "1h", {
        "hour": best["bucket"],
        "bullish_pct": best["bullish_pct"],
        "trend_quality": best["trend_quality"],
        "significance": best["significance"],
    })
    return {"type": "time_window", "severity": "medium", "title": title}


def check_overtrading_alert(conn):
    """
    Alert when trader is approaching or exceeding trade frequency limits.
    """
    if not _check_cooldown("overtrading", "global"):
        return None

    freq = calc_trade_frequency_status(conn)

    alerts = []

    # Warning at 80% of limits
    sess_ratio = freq["session_trades"] / freq["session_limit"] if freq["session_limit"] > 0 else 0
    day_ratio = freq["day_trades"] / freq["day_limit"] if freq["day_limit"] > 0 else 0

    if not freq["allowed"]:
        severity = "high"
        title = "TRADING BLOCKED"
        message = " | ".join(freq["reasons"])
        _store_alert(conn, "overtrading", severity, title, message, "global", freq)
        return {"type": "overtrading", "severity": severity, "title": title}

    if sess_ratio >= 0.8 or day_ratio >= 0.8:
        severity = "medium"
        title = "Approaching Trade Limit"
        parts = []
        if sess_ratio >= 0.8:
            parts.append(f"Session: {freq['session_trades']}/{freq['session_limit']}")
        if day_ratio >= 0.8:
            parts.append(f"Day: {freq['day_trades']}/{freq['day_limit']}")
        message = " | ".join(parts) + " — Be selective with remaining trades."
        _store_alert(conn, "overtrading", severity, title, message, "global", freq)
        return {"type": "overtrading", "severity": severity, "title": title}

    if freq["consecutive_losses"] >= 2:
        severity = "medium"
        title = f"Loss Streak: {freq['consecutive_losses']} Consecutive"
        message = "Consider pausing. Review last trades before continuing."
        _store_alert(conn, "overtrading", severity, title, message, "global", freq)
        return {"type": "overtrading", "severity": severity, "title": title}

    return None


def check_streak_exhaustion_alert(conn, timeframe, closes):
    """
    Alert when a price streak becomes statistically exhausted.
    """
    if len(closes) < 30:
        return None
    if not _check_cooldown("streak_exhaustion", timeframe):
        return None

    closes_arr = np.array(closes, dtype=float)
    streak = calc_streak_info(closes_arr)

    if streak is None:
        return None

    current = streak.get("current_streak", 0)
    mean = streak.get("mean_streak", 2)
    std = streak.get("std_streak", 1)

    if std > 0:
        z = (abs(current) - mean) / std
    else:
        z = 0

    if z < 1.5:
        return None

    direction = "Bullish" if current > 0 else "Bearish"

    if z >= 2.5:
        severity = "high"
    elif z >= 2.0:
        severity = "medium"
    else:
        severity = "low"

    title = f"Streak Exhaustion — {abs(current)}-bar {direction} ({timeframe.upper()})"
    message = (
        f"{abs(current)}-candle {direction.lower()} streak is {z:.1f}σ above average. "
        f"Momentum fade likely. Watch for reversal signals."
    )

    _store_alert(conn, "streak_exhaustion", severity, title, message, timeframe, {
        "streak": current, "z_score": round(z, 2),
        "mean": round(mean, 1), "std": round(std, 2),
    })
    return {"type": "streak_exhaustion", "severity": severity, "title": title}


def check_volatility_spike_alert(conn, timeframe, highs, lows, closes):
    """
    Alert on sudden volatility expansion — ATR ratio spikes above threshold.
    """
    if len(closes) < 60:
        return None
    if not _check_cooldown("volatility_spike", timeframe):
        return None

    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)
    c = np.array(closes, dtype=float)

    atr_fast = calc_atr(h, l, c, 5)
    atr_slow = calc_atr(h, l, c, 50)

    if atr_fast is None or atr_slow is None or atr_slow == 0:
        return None

    ratio = float(atr_fast / atr_slow)

    if ratio < 1.8:
        return None

    if ratio >= 2.5:
        severity = "high"
    elif ratio >= 2.0:
        severity = "medium"
    else:
        severity = "low"

    title = f"Volatility Spike — {timeframe.upper()} ({ratio:.1f}× normal)"
    message = (
        f"ATR(5) is {ratio:.1f}× ATR(50). Extreme expansion detected. "
        f"Reduce position size or wait for stabilization."
    )

    _store_alert(conn, "volatility_spike", severity, title, message, timeframe, {
        "atr_fast": round(float(atr_fast), 4),
        "atr_slow": round(float(atr_slow), 4),
        "ratio": round(ratio, 2),
    })
    return {"type": "volatility_spike", "severity": severity, "title": title}


def check_momentum_shift_alert(conn, timeframe, closes):
    """
    Alert when rolling momentum flips direction (bull→bear or bear→bull).
    Uses 20-bar rolling window.
    """
    if len(closes) < 25:
        return None
    if not _check_cooldown("momentum_shift", timeframe):
        return None

    closes_arr = np.array(closes, dtype=float)

    # Current 20-bar return
    ret_now = (closes_arr[-1] - closes_arr[-20]) / closes_arr[-20] if closes_arr[-20] != 0 else 0
    # Previous 20-bar return (shifted by 1)
    ret_prev = (closes_arr[-2] - closes_arr[-21]) / closes_arr[-21] if closes_arr[-21] != 0 else 0

    # Check for sign flip
    if ret_now > 0.001 and ret_prev < -0.001:
        direction = "BEARISH → BULLISH"
        severity = "medium"
    elif ret_now < -0.001 and ret_prev > 0.001:
        direction = "BULLISH → BEARISH"
        severity = "medium"
    else:
        return None

    title = f"Momentum Shift: {direction} ({timeframe.upper()})"
    message = (
        f"20-bar rolling momentum flipped. "
        f"Previous: {ret_prev*100:.3f}% → Current: {ret_now*100:.3f}%"
    )

    _store_alert(conn, "momentum_shift", severity, title, message, timeframe, {
        "previous_return": round(ret_prev * 100, 4),
        "current_return": round(ret_now * 100, 4),
    })
    return {"type": "momentum_shift", "severity": severity, "title": title}


def run_all_alert_checks(conn, timeframe, closes, highs, lows, current_regime, previous_regime):
    """
    Master alert runner — executes all alert checks for a timeframe.
    Called from the background regime update loop.
    Returns list of new alerts generated.
    """
    new_alerts = []

    try:
        a = check_regime_shift(conn, timeframe, current_regime, previous_regime)
        if a: new_alerts.append(a)
    except Exception as e:
        log.warning(f"Alert check regime_shift failed: {e}")

    try:
        a = check_compression_alert(conn, timeframe, closes, highs, lows)
        if a: new_alerts.append(a)
    except Exception as e:
        log.warning(f"Alert check compression failed: {e}")

    try:
        a = check_streak_exhaustion_alert(conn, timeframe, closes)
        if a: new_alerts.append(a)
    except Exception as e:
        log.warning(f"Alert check streak_exhaustion failed: {e}")

    try:
        a = check_volatility_spike_alert(conn, timeframe, highs, lows, closes)
        if a: new_alerts.append(a)
    except Exception as e:
        log.warning(f"Alert check volatility_spike failed: {e}")

    try:
        a = check_momentum_shift_alert(conn, timeframe, closes)
        if a: new_alerts.append(a)
    except Exception as e:
        log.warning(f"Alert check momentum_shift failed: {e}")

    # Global checks (once, not per-timeframe — use 1h as trigger)
    if timeframe == "1h":
        try:
            a = check_time_window_alert(conn)
            if a: new_alerts.append(a)
        except Exception as e:
            log.warning(f"Alert check time_window failed: {e}")

        try:
            a = check_overtrading_alert(conn)
            if a: new_alerts.append(a)
        except Exception as e:
            log.warning(f"Alert check overtrading failed: {e}")

    return new_alerts


# ---------------------------------------------------------------------------
# Deriv WebSocket Data Service
# ---------------------------------------------------------------------------

class DerivDataService:
    """Handles all communication with Deriv's WebSocket API."""

    def __init__(self):
        self.ws = None
        self.running = False
        self.tick_buffer = deque(maxlen=10000)
        self.latest_tick = None
        self.connected = False
        self._loop = None
        self._thread = None

    def start(self):
        """Start the data service in a background thread."""
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        log.info("Deriv data service thread started")

    def _run_loop(self):
        """Run the async event loop in a thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._connect_and_stream())

    async def _connect_and_stream(self):
        """Connect to Deriv and stream V75 ticks."""
        self.running = True
        retry_delay = 5

        while self.running:
            try:
                log.info(f"Connecting to Deriv WebSocket...")
                async with websockets.connect(DERIV_WS_URL) as ws:
                    self.ws = ws
                    self.connected = True
                    retry_delay = 5
                    log.info("Connected to Deriv WebSocket")

                    # Authorize if token is set
                    if DERIV_API_TOKEN:
                        auth_msg = {"authorize": DERIV_API_TOKEN}
                        await ws.send(json.dumps(auth_msg))
                        auth_resp = await ws.recv()
                        auth_data = json.loads(auth_resp)
                        if "error" in auth_data:
                            log.error(f"Auth failed: {auth_data['error']['message']}")
                            self.connected = False
                            return
                        log.info("Authorized with Deriv")

                    # Fetch historical candles for each timeframe
                    await self._fetch_history(ws)

                    # Subscribe to live ticks
                    sub_msg = {
                        "ticks": V75_SYMBOL,
                        "subscribe": 1,
                    }
                    await ws.send(json.dumps(sub_msg))
                    log.info(f"Subscribed to {V75_SYMBOL} ticks")

                    # Process incoming messages
                    async for message in ws:
                        data = json.loads(message)
                        if "tick" in data:
                            self._process_tick(data["tick"])
                        elif "error" in data:
                            log.warning(f"Deriv error: {data['error'].get('message', 'Unknown')}")

            except (websockets.exceptions.ConnectionClosed, Exception) as e:
                self.connected = False
                log.warning(f"WebSocket disconnected: {e}. Retrying in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60)

    async def _fetch_history(self, ws):
        """Fetch historical candle data for backtesting regime classification."""
        # Map our timeframes to Deriv's granularity values
        tf_to_granularity = {
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "1h": 3600,
            "4h": 14400,
        }

        for tf, granularity in tf_to_granularity.items():
            try:
                # Request last 500 candles
                hist_msg = {
                    "ticks_history": V75_SYMBOL,
                    "adjust_start_time": 1,
                    "count": 500,
                    "end": "latest",
                    "granularity": granularity,
                    "style": "candles",
                }
                await ws.send(json.dumps(hist_msg))
                resp = await ws.recv()
                data = json.loads(resp)

                if "candles" in data:
                    candles = data["candles"]
                    conn = get_db()
                    for c in candles:
                        try:
                            conn.execute(
                                """INSERT OR IGNORE INTO candles
                                   (timeframe, timestamp, open, high, low, close)
                                   VALUES (?, ?, ?, ?, ?, ?)""",
                                (tf, c["epoch"], c["open"], c["high"], c["low"], c["close"]),
                            )
                        except sqlite3.IntegrityError:
                            pass
                    conn.commit()
                    conn.close()
                    log.info(f"Loaded {len(candles)} historical {tf} candles")
                elif "error" in data:
                    log.warning(f"History error for {tf}: {data['error'].get('message')}")

            except Exception as e:
                log.error(f"Failed to fetch {tf} history: {e}")

    def _process_tick(self, tick):
        """Process incoming tick and update candle data."""
        self.latest_tick = {
            "price": float(tick["quote"]),
            "timestamp": int(tick["epoch"]),
            "symbol": tick.get("symbol", V75_SYMBOL),
        }
        self.tick_buffer.append(self.latest_tick)

        # Update current candles for each timeframe
        conn = get_db()
        for tf, seconds in TIMEFRAMES.items():
            candle_ts = (self.latest_tick["timestamp"] // seconds) * seconds
            price = self.latest_tick["price"]

            existing = conn.execute(
                "SELECT * FROM candles WHERE timeframe=? AND timestamp=?",
                (tf, candle_ts),
            ).fetchone()

            if existing:
                new_high = max(existing["high"], price)
                new_low = min(existing["low"], price)
                conn.execute(
                    """UPDATE candles SET high=?, low=?, close=?, tick_count=tick_count+1
                       WHERE timeframe=? AND timestamp=?""",
                    (new_high, new_low, price, tf, candle_ts),
                )
            else:
                conn.execute(
                    """INSERT OR IGNORE INTO candles
                       (timeframe, timestamp, open, high, low, close, tick_count)
                       VALUES (?, ?, ?, ?, ?, ?, 1)""",
                    (tf, candle_ts, price, price, price, price),
                )
        conn.commit()
        conn.close()


# ---------------------------------------------------------------------------
# Global data service instance
# ---------------------------------------------------------------------------

data_service = DerivDataService()

# ---------------------------------------------------------------------------
# Flask Application
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.secret_key = os.environ.get("V75_SECRET_KEY", "v75-sgp-dashboard-dev-key")


# Recursively sanitize numpy types to native Python for JSON serialization
def sanitize_for_json(obj):
    """Convert numpy types to native Python types recursively."""
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_json(v) for v in obj]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


@app.route("/sw.js")
def service_worker():
    """Serve SW from root so its scope covers the whole app."""
    return send_from_directory("static", "sw.js", mimetype="application/javascript")


@app.route("/")
def dashboard():
    """Main dashboard page."""
    return render_template("dashboard.html")


@app.route("/api/status")
def api_status():
    """System status check."""
    return jsonify({
        "connected": data_service.connected,
        "latest_tick": data_service.latest_tick,
        "tick_buffer_size": len(data_service.tick_buffer),
        "has_api_token": bool(DERIV_API_TOKEN),
        "symbol": V75_SYMBOL,
        "server_time": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/regime")
def api_regime():
    """Get current regime classification for all timeframes."""
    results = {}
    conn = get_db()

    for tf in TIMEFRAMES:
        rows = conn.execute(
            """SELECT timestamp, open, high, low, close FROM candles
               WHERE timeframe=? ORDER BY timestamp DESC LIMIT ?""",
            (tf, REGIME_CONFIG["regime_lookback"] + 50),
        ).fetchall()

        if len(rows) < 20:
            results[tf] = {
                "regime": "insufficient_data",
                "sub_regime": "waiting",
                "confidence": 0,
                "candle_count": len(rows),
                "metrics": {},
            }
            continue

        # Convert to dataframe (reverse to chronological order)
        rows = list(reversed(rows))
        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col])

        regime = classify_regime(df)
        regime["candle_count"] = len(rows)
        results[tf] = regime

    conn.close()
    return jsonify(results)


@app.route("/api/candles/<timeframe>")
def api_candles(timeframe):
    """Get candle data for charting."""
    if timeframe not in TIMEFRAMES:
        return jsonify({"error": f"Invalid timeframe: {timeframe}"}), 400

    limit = request.args.get("limit", 200, type=int)
    conn = get_db()
    rows = conn.execute(
        """SELECT timestamp, open, high, low, close, tick_count FROM candles
           WHERE timeframe=? ORDER BY timestamp DESC LIMIT ?""",
        (timeframe, limit),
    ).fetchall()
    conn.close()

    candles = [
        {
            "timestamp": r["timestamp"],
            "time": datetime.fromtimestamp(r["timestamp"], tz=timezone.utc).isoformat(),
            "open": r["open"],
            "high": r["high"],
            "low": r["low"],
            "close": r["close"],
            "tick_count": r["tick_count"],
        }
        for r in reversed(rows)
    ]
    return jsonify(candles)


@app.route("/api/metrics/<timeframe>")
def api_metrics(timeframe):
    """Get detailed statistical metrics for a timeframe."""
    if timeframe not in TIMEFRAMES:
        return jsonify({"error": f"Invalid timeframe: {timeframe}"}), 400

    conn = get_db()
    rows = conn.execute(
        """SELECT timestamp, open, high, low, close FROM candles
           WHERE timeframe=? ORDER BY timestamp DESC LIMIT 200""",
        (timeframe,),
    ).fetchall()
    conn.close()

    if len(rows) < 20:
        return jsonify({"error": "Insufficient data", "candle_count": len(rows)})

    rows = list(reversed(rows))
    closes = [r["close"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]

    # Price metrics
    current_price = closes[-1]
    sma_20 = float(np.mean(closes[-20:]))
    sma_50 = float(np.mean(closes[-min(50, len(closes)):]))

    # Volatility metrics
    returns = np.diff(np.log(np.array(closes, dtype=float)))
    realized_vol = float(np.std(returns) * np.sqrt(252)) if len(returns) > 1 else 0

    # Streak analysis
    streak = calc_streak_info(closes)

    # Bollinger info
    bb_period = 20
    if len(closes) >= bb_period:
        bb_sma = np.mean(closes[-bb_period:])
        bb_std = np.std(closes[-bb_period:], ddof=1)
        bb_upper = bb_sma + 2 * bb_std
        bb_lower = bb_sma - 2 * bb_std
        bb_position = (current_price - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0.5
    else:
        bb_upper = bb_lower = bb_sma = current_price
        bb_position = 0.5

    return jsonify({
        "price": {
            "current": current_price,
            "sma_20": round(sma_20, 2),
            "sma_50": round(sma_50, 2),
            "price_vs_sma20": round((current_price / sma_20 - 1) * 100, 3),
        },
        "volatility": {
            "realized_annual": round(realized_vol * 100, 2),
            "atr": calc_atr(highs, lows, closes),
            "bb_width": calc_bollinger_bandwidth(closes),
            "bb_position": round(float(bb_position), 3),
            "bb_upper": round(float(bb_upper), 2),
            "bb_lower": round(float(bb_lower), 2),
        },
        "behavior": {
            "hurst": calc_hurst(closes),
            "autocorrelation": calc_autocorrelation(closes),
            "streak": streak,
        },
        "candle_count": len(rows),
    })


@app.route("/api/regime_history/<timeframe>")
def api_regime_history(timeframe):
    """Get regime classification history for trend visualization."""
    if timeframe not in TIMEFRAMES:
        return jsonify({"error": f"Invalid timeframe: {timeframe}"}), 400

    conn = get_db()
    rows = conn.execute(
        """SELECT * FROM regime_history
           WHERE timeframe=? ORDER BY timestamp DESC LIMIT 100""",
        (timeframe,),
    ).fetchall()
    conn.close()

    return jsonify([dict(r) for r in reversed(rows)])


# ---------------------------------------------------------------------------
# Tendency Engine API Endpoints (Phase 2 — Panel B)
# ---------------------------------------------------------------------------

def _get_candle_arrays(timeframe, limit=500):
    """Helper: fetch candle arrays for tendency calculations."""
    conn = get_db()
    rows = conn.execute(
        """SELECT timestamp, open, high, low, close FROM candles
           WHERE timeframe=? ORDER BY timestamp DESC LIMIT ?""",
        (timeframe, limit),
    ).fetchall()
    conn.close()

    if len(rows) < 30:
        return None

    rows = list(reversed(rows))
    timestamps = [r["timestamp"] for r in rows]
    opens = [float(r["open"]) for r in rows]
    highs = [float(r["high"]) for r in rows]
    lows = [float(r["low"]) for r in rows]
    closes = [float(r["close"]) for r in rows]
    return timestamps, opens, highs, lows, closes


@app.route("/api/tendency/<timeframe>")
def api_tendency(timeframe):
    """
    Full tendency engine output for a timeframe.
    Returns hourly, weekday, monthly, quarterly, session profiles
    plus rolling momentum and a synthesized summary.
    """
    if timeframe not in TIMEFRAMES:
        return jsonify({"error": f"Invalid timeframe: {timeframe}"}), 400

    data = _get_candle_arrays(timeframe, limit=500)
    if data is None:
        return jsonify({"error": "Insufficient data", "candle_count": 0})

    timestamps, opens, highs, lows, closes = data

    hourly = calc_hourly_tendency(timestamps, opens, highs, lows, closes)
    weekday = calc_weekday_tendency(timestamps, opens, highs, lows, closes)
    monthly = calc_monthly_tendency(timestamps, opens, highs, lows, closes)
    quarterly = calc_quarterly_tendency(timestamps, opens, highs, lows, closes)
    session = calc_session_tendency(timestamps, opens, highs, lows, closes)
    rolling = calc_rolling_tendency(timestamps, closes)
    summary = calc_current_tendency_summary(hourly, weekday, session, rolling)

    return jsonify({
        "timeframe": timeframe,
        "candle_count": len(closes),
        "hourly": hourly,
        "weekday": weekday,
        "monthly": monthly,
        "quarterly": quarterly,
        "session": session,
        "rolling": rolling,
        "summary": summary,
    })


@app.route("/api/tendency/summary/<timeframe>")
def api_tendency_summary(timeframe):
    """Lightweight summary — just the current window's tendency verdict."""
    if timeframe not in TIMEFRAMES:
        return jsonify({"error": f"Invalid timeframe: {timeframe}"}), 400

    data = _get_candle_arrays(timeframe, limit=500)
    if data is None:
        return jsonify({"error": "Insufficient data"})

    timestamps, opens, highs, lows, closes = data

    hourly = calc_hourly_tendency(timestamps, opens, highs, lows, closes)
    weekday = calc_weekday_tendency(timestamps, opens, highs, lows, closes)
    session = calc_session_tendency(timestamps, opens, highs, lows, closes)
    rolling = calc_rolling_tendency(timestamps, closes)
    summary = calc_current_tendency_summary(hourly, weekday, session, rolling)

    return jsonify(summary)


# ---------------------------------------------------------------------------
# Setup Scanner API Endpoints (Phase 2 — Panel C)
# ---------------------------------------------------------------------------

@app.route("/api/setups/<timeframe>")
def api_setups(timeframe):
    """
    Scan for active trade setups on a given timeframe.
    Each setup includes confidence, regime compatibility, and composite score.
    """
    if timeframe not in TIMEFRAMES:
        return jsonify({"error": f"Invalid timeframe: {timeframe}"}), 400

    conn = get_db()
    rows = conn.execute(
        """SELECT timestamp, open, high, low, close FROM candles
           WHERE timeframe=? ORDER BY timestamp DESC LIMIT 200""",
        (timeframe,),
    ).fetchall()
    conn.close()

    if len(rows) < 50:
        return jsonify({"timeframe": timeframe, "setups": [], "count": 0,
                        "error": "Insufficient data for setup detection"})

    try:
        rows = list(reversed(rows))
        closes = [float(r["close"]) for r in rows]
        highs = [float(r["high"]) for r in rows]
        lows = [float(r["low"]) for r in rows]

        # Get current regime for compatibility scoring
        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
        for col in ["open", "high", "low", "close"]:
            df[col] = pd.to_numeric(df[col])
        regime_data = classify_regime(df)

        setups = scan_all_setups(closes, highs, lows, regime_data)

        return jsonify(sanitize_for_json({
            "timeframe": timeframe,
            "regime": regime_data.get("regime"),
            "sub_regime": regime_data.get("sub_regime"),
            "setups": setups,
            "count": len(setups),
        }))
    except Exception as e:
        log.error(f"Setup scan error for {timeframe}: {e}", exc_info=True)
        return jsonify({"timeframe": timeframe, "setups": [], "count": 0,
                        "error": str(e)}), 500


@app.route("/api/setups/all")
def api_setups_all():
    """Scan all timeframes and return setups from each."""
    all_setups = {}
    for tf in TIMEFRAMES:
        try:
            conn = get_db()
            rows = conn.execute(
                """SELECT timestamp, open, high, low, close FROM candles
                   WHERE timeframe=? ORDER BY timestamp DESC LIMIT 200""",
                (tf,),
            ).fetchall()
            conn.close()

            if len(rows) < 50:
                all_setups[tf] = {"setups": [], "count": 0}
                continue

            rows = list(reversed(rows))
            closes = [float(r["close"]) for r in rows]
            highs = [float(r["high"]) for r in rows]
            lows = [float(r["low"]) for r in rows]

            df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col])
            regime_data = classify_regime(df)

            setups = scan_all_setups(closes, highs, lows, regime_data)
            all_setups[tf] = {
                "regime": regime_data.get("regime"),
                "sub_regime": regime_data.get("sub_regime"),
                "setups": setups,
                "count": len(setups),
            }
        except Exception as e:
            log.error(f"Setup scan error for {tf}: {e}")
            all_setups[tf] = {"setups": [], "count": 0, "error": str(e)}

    return jsonify(sanitize_for_json(all_setups))


# ---------------------------------------------------------------------------
# Alert Engine API Endpoints (Phase 4 — Panel F)
# ---------------------------------------------------------------------------

@app.route("/api/alerts")
def api_alerts():
    """Get recent alerts (undismissed by default)."""
    show_all = request.args.get("all", "0") == "1"
    limit = request.args.get("limit", 50, type=int)

    conn = get_db()
    if show_all:
        rows = conn.execute(
            "SELECT * FROM alerts ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM alerts WHERE dismissed=0 ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()

    alerts = []
    for r in rows:
        alert = dict(r)
        try:
            alert["data"] = json.loads(alert.get("data", "{}"))
        except (json.JSONDecodeError, TypeError):
            alert["data"] = {}
        alerts.append(alert)

    return jsonify(alerts)


@app.route("/api/alerts/dismiss/<int:alert_id>", methods=["POST"])
def api_dismiss_alert(alert_id):
    """Dismiss a single alert."""
    conn = get_db()
    conn.execute("UPDATE alerts SET dismissed=1 WHERE id=?", (alert_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/alerts/dismiss_all", methods=["POST"])
def api_dismiss_all_alerts():
    """Dismiss all alerts."""
    conn = get_db()
    conn.execute("UPDATE alerts SET dismissed=1")
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/alerts/count")
def api_alert_count():
    """Quick count of undismissed alerts — for badge display."""
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM alerts WHERE dismissed=0").fetchone()[0]
    conn.close()
    return jsonify({"count": count})


@app.route("/api/telegram/test", methods=["POST"])
def api_telegram_test():
    """Send a test message to verify Telegram is configured."""
    if not TELEGRAM_ENABLED:
        return jsonify({"ok": False, "error": "Telegram not configured. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in D.env"})
    _send_telegram("warning", "Test Alert", "Telegram integration is working! V75 Dashboard alerts will appear here.", "")
    return jsonify({"ok": True, "message": "Test message sent — check your Telegram"})


# ---------------------------------------------------------------------------
# AI Interpreter Engine (Phase 5 — Panel G)
# ---------------------------------------------------------------------------
# Rule-based interpretation engine that reads all panel data and produces
# a synthesized market narrative with directional guidance and reasoning.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# META-ANALYSIS ENGINE (V75-SPECIFIC)
# ---------------------------------------------------------------------------
# Rebuilt for V75's algorithmic behavior. Uses additive scoring — earns
# alignment points from positive signals instead of deducting from 100.
# Detects signal conflicts, alert clustering, regime fatigue, and produces
# a unified System Alignment Score (0-100).
# ---------------------------------------------------------------------------

_regime_run_tracker = {}  # {timeframe: {"regime": str, "count": int, "started": timestamp}}


def run_meta_analysis(regime_data, tendency_summary, setups_data, metrics_data, timeframe="1h"):
    """
    V75-specific meta-analysis engine.  Uses ADDITIVE scoring — starts at 0
    and earns alignment points from positive signals.  Only flags conflicts
    that represent genuine structural breakdowns, not normal V75 behavior.

    Returns: alignment_score, conflicts, opportunities, spike_tracking,
             tf_alignment, regime_fatigue, alert_intelligence, meta_warnings,
             meta_narrative.
    """
    cfg = V75_META_CONFIG
    weights = cfg["weights"]
    conflicts = []
    opportunities = []
    meta_warnings = []

    regime = regime_data.get("regime", "unknown")
    sub_regime = regime_data.get("sub_regime", "unknown")
    confidence = regime_data.get("confidence", 0)
    metrics = regime_data.get("metrics", {})
    adx = metrics.get("adx", 0) or 0
    hurst = metrics.get("hurst", 0.5) or 0.5
    atr_ratio = metrics.get("atr_ratio", 1.0) or 1.0
    autocorr = metrics.get("autocorrelation", 0) or 0

    # --- Tendency data (uses real field names from calc_current_tendency_summary) ---
    tendency_bias = "neutral"
    tendency_strength = 0
    tendency_quality = 0
    if tendency_summary:
        tendency_bias = tendency_summary.get("tendency", "neutral")
        tendency_strength = tendency_summary.get("tendency_strength", 0)  # 0-1 ratio
        tendency_quality = tendency_summary.get("window_quality", 0)

    # --- Setup data ---
    setup_list = []
    if setups_data and isinstance(setups_data, list):
        setup_list = setups_data
    elif setups_data and isinstance(setups_data, dict):
        setup_list = setups_data.get("setups", []) or []

    # =================================================================
    # 1. TENDENCY ENGINE ACCURACY (up to 35 pts)
    # =================================================================
    tendency_points = 0
    if tendency_bias != "neutral":
        # Strength contributes up to 20 pts (strength is 0-1)
        tendency_points += min(20, tendency_strength * 25)
        # Quality contributes up to 10 pts (quality is 0-1)
        tendency_points += min(10, tendency_quality * 12)
        # Bonus: tendency aligns with regime direction
        regime_dir = "bullish" if "up" in sub_regime else "bearish" if "down" in sub_regime else "neutral"
        if tendency_bias == regime_dir:
            tendency_points += 5  # Agreement bonus
    tendency_points = min(weights["tendency_accuracy"], tendency_points)

    # =================================================================
    # 2. TIMEFRAME HIERARCHY (up to 25 pts)
    # =================================================================
    tf_alignment, tf_warnings = _check_timeframe_hierarchy_v75(regime, sub_regime)
    tf_points = tf_alignment.get("alignment_points", 0)
    tf_points = min(weights["tf_hierarchy"], tf_points)
    for w in tf_warnings:
        meta_warnings.append(w)

    # =================================================================
    # 3. REGIME CONFIDENCE (up to 20 pts)
    # =================================================================
    regime_points = 0
    if regime != "unknown":
        regime_points = min(weights["regime_confidence"], confidence * 0.25)
        # V75-calibrated indicator checks — only flag EXTREME anomalies
        if adx > cfg["adx_extreme"]:
            meta_warnings.append(f"ADX anomaly ({adx:.0f}) — above V75's normal range. Possible data issue or unprecedented move.")
            regime_points = max(0, regime_points - 5)
        if adx > cfg["adx_strong_trend"] and hurst < cfg["hurst_mr"]:
            conflicts.append({
                "type": "indicator_divergence",
                "severity": "medium",
                "description": f"ADX ({adx:.0f}) shows strong trend but Hurst ({hurst:.3f}) says mean-reverting. Unusual even for V75.",
                "resolution": "This specific combination is rare in V75. Reduce size until indicators realign."
            })
            regime_points = max(0, regime_points - 5)

    # =================================================================
    # 4. SETUP ALIGNMENT (up to 15 pts)
    # =================================================================
    setup_points = 0
    if setup_list:
        regime_dir = "bullish" if "up" in sub_regime else "bearish" if "down" in sub_regime else "neutral"
        for s in setup_list:
            stype = s.get("type", "")
            sdir = s.get("direction", "")
            stag = s.get("regime_tag", "")

            if sdir == regime_dir or sdir == tendency_bias:
                # Setup aligns with bias — earn points
                setup_points += 5
            elif regime_dir != "neutral" and sdir and sdir != regime_dir:
                # Opposite direction setup = FADE opportunity, not a conflict
                opportunities.append({
                    "type": "fade_opportunity",
                    "severity": "info",
                    "description": f"{sdir.upper()} {stype} during {sub_regime.upper()} regime — potential FADE entry.",
                    "resolution": f"Use this {stype} as a counter-trend entry if regime shows fatigue. Tight stops."
                })
            if stag == "CAUTION" and tendency_bias == "neutral" and confidence < 50:
                # Only flag CAUTION setups when there's no clear read at all
                conflicts.append({
                    "type": "low_conviction_setup",
                    "severity": "low",
                    "description": f"Setup '{stype}' has CAUTION tag with no clear tendency and low regime confidence.",
                    "resolution": f"Skip or paper trade this {stype}."
                })
    elif regime in ("trending",) and confidence >= 80 and tendency_bias != "neutral":
        # Strong regime + clear tendency but no setups — V75 can trend without traditional setups
        meta_warnings.append("No setups detected despite strong trend. V75 can trend without pullbacks — watch for entry on micro-TF.")
    setup_points = min(weights["setup_alignment"], setup_points)

    # =================================================================
    # 5. ALERT HEALTH (up to 5 pts)
    # =================================================================
    alert_intel = _analyze_alert_intelligence_v75(timeframe, regime)
    alert_points = weights["alert_health"]  # Start at max, deduct for noise
    if alert_intel["density_score"] >= 8:
        alert_points = max(0, alert_points - 3)
        meta_warnings.append(f"High alert density ({alert_intel['total_recent']} in 4h) — V75 algo is active. Normal during trending.")
    if alert_intel["echo_detected"]:
        alert_points = max(0, alert_points - 2)
        for echo in alert_intel["echoes"]:
            meta_warnings.append(f"Alert echo: '{echo['type']}' fired {echo['count']}x in 4h")

    # =================================================================
    # 6. SPIKE PATTERN TRACKING
    # =================================================================
    spike_tracking = _track_spike_patterns(alert_intel, regime, atr_ratio)
    if spike_tracking["spike_probable"]:
        opportunities.append({
            "type": "spike_setup",
            "severity": "info",
            "description": f"Spike probability {spike_tracking['probability']:.0%} — {spike_tracking['compression_count']} compressions detected.",
            "resolution": "Watch for volatility expansion. Set alerts for breakout entries."
        })

    # =================================================================
    # 7. REGIME FATIGUE
    # =================================================================
    fatigue = _check_regime_fatigue(regime, timeframe)
    if fatigue["is_fatigued"]:
        meta_warnings.append(
            f"Regime fatigue: {regime.upper()} active for {fatigue['duration_readings']} readings "
            f"(avg: {fatigue['avg_duration']:.0f}). Transition probability elevated."
        )
        if fatigue["likely_next"]:
            meta_warnings.append(f"Likely next regime: {fatigue['likely_next'].upper()} ({fatigue['transition_prob']:.0f}%)")

    # =================================================================
    # 8. REAL CONFLICT DETECTION (only genuine structural issues)
    # =================================================================
    # Tendency prediction failure: tendency has clear read but regime totally disagrees
    # AND tendency strength is very high — this is a real structural divergence
    if tendency_strength > 0.7:
        regime_dir = "bullish" if "up" in sub_regime else "bearish" if "down" in sub_regime else "neutral"
        if regime_dir != "neutral" and tendency_bias != "neutral" and tendency_bias != regime_dir:
            conflicts.append({
                "type": "tendency_vs_regime",
                "severity": "high",
                "description": f"Strong tendency ({tendency_bias.upper()}, {tendency_strength:.0%}) opposes regime ({sub_regime.upper()}). One will break.",
                "resolution": "Tendency often leads regime shifts. Watch for regime transition confirmation on 15M."
            })
            tendency_points = max(0, tendency_points - 10)

    # Structure breakdown: 15M (structure) contradicts 1H (bias) — from tf_alignment
    if tf_alignment.get("structure_breakdown"):
        conflicts.append({
            "type": "structure_breakdown",
            "severity": "high",
            "description": tf_alignment["structure_breakdown"],
            "resolution": "The structure supporting the 1H bias is failing. Reduce size or wait for realignment."
        })
        tf_points = max(0, tf_points - 10)

    # =================================================================
    # 9. COMPUTE FINAL ALIGNMENT SCORE
    # =================================================================
    alignment_score = int(min(100, tendency_points + tf_points + regime_points + setup_points + alert_points))
    alignment_score = max(0, alignment_score)

    if alignment_score >= 75:
        label = "HIGH"
    elif alignment_score >= 50:
        label = "MODERATE"
    elif alignment_score >= 30:
        label = "LOW"
    else:
        label = "CRITICAL"

    # Build V75-specific narrative
    if alignment_score >= 75:
        meta_narrative = "V75 is in a clean state — bias, structure, and tendency agree. Trade your setups with full conviction."
    elif alignment_score >= 50:
        meta_narrative = "Structure intact but some divergence detected. Normal V75 behavior — proceed with standard sizing."
    elif alignment_score >= 30:
        meta_narrative = "Structure is breaking down against the bias. Reduce size or wait for structure to realign."
    else:
        meta_narrative = "All systems disagree. Sit out until clarity returns."

    if conflicts:
        meta_narrative += f" {len(conflicts)} conflict(s)."
    if opportunities:
        meta_narrative += f" {len(opportunities)} opportunity(s) detected."

    return {
        "alignment_score": alignment_score,
        "alignment_label": label,
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "opportunities": opportunities,
        "opportunity_count": len(opportunities),
        "spike_tracking": spike_tracking,
        "tf_alignment": tf_alignment,
        "regime_fatigue": fatigue,
        "alert_intelligence": alert_intel,
        "meta_warnings": meta_warnings,
        "meta_narrative": meta_narrative,
        "score_breakdown": {
            "tendency": round(tendency_points, 1),
            "tf_hierarchy": round(tf_points, 1),
            "regime_confidence": round(regime_points, 1),
            "setup_alignment": round(setup_points, 1),
            "alert_health": round(alert_points, 1),
        },
    }


def _analyze_alert_intelligence_v75(timeframe="1h", regime="unknown"):
    """
    V75-specific alert intelligence.  High alert density during trending
    is NORMAL for V75 — only flag when alerts actively contradict the regime.
    """
    result = {
        "total_recent": 0,
        "density_score": 0,
        "echo_detected": False,
        "echoes": [],
        "counter_trend_alerts": 0,
        "compression_count": 0,
        "by_type": {},
        "fade_signals": 0,
    }
    try:
        conn = get_db()
        four_hours_ago = int(time.time()) - 4 * 3600
        rows = conn.execute(
            "SELECT alert_type, severity, title, timeframe FROM alerts WHERE timestamp > ? ORDER BY timestamp DESC",
            (four_hours_ago,)
        ).fetchall()
        conn.close()

        result["total_recent"] = len(rows)

        type_counts = {}
        for r in rows:
            atype = r["alert_type"]
            type_counts[atype] = type_counts.get(atype, 0) + 1
        result["by_type"] = type_counts

        # V75-calibrated density (higher thresholds — V75 is noisy by nature)
        if len(rows) >= 30:
            result["density_score"] = 10
        elif len(rows) >= 20:
            result["density_score"] = 8
        elif len(rows) >= 12:
            result["density_score"] = 6
        elif len(rows) >= 6:
            result["density_score"] = 4
        else:
            result["density_score"] = max(0, len(rows))

        # Echo detection: same alert type 5+ times (raised from 3 for V75)
        for atype, count in type_counts.items():
            if count >= 5:
                result["echo_detected"] = True
                result["echoes"].append({"type": atype, "count": count})

        # Streak exhaustion during trending = fade signals (opportunities, not danger)
        streak_count = type_counts.get("streak_exhaustion", 0)
        if regime == "trending" and streak_count > 0:
            result["fade_signals"] = streak_count
        result["counter_trend_alerts"] = streak_count

        # Compression counting (used for spike tracking)
        result["compression_count"] = type_counts.get("compression", 0)

    except Exception as e:
        log.warning(f"Alert intelligence error: {e}")

    return result


def _check_regime_fatigue(current_regime, timeframe="1h"):
    """Check if the current regime has been running longer than typical."""
    result = {
        "is_fatigued": False,
        "duration_readings": 0,
        "avg_duration": 0,
        "likely_next": None,
        "transition_prob": 0,
    }
    try:
        conn = get_db()
        # Get recent regime history
        rows = conn.execute(
            """SELECT regime, timestamp FROM regime_history
               WHERE timeframe=? ORDER BY timestamp DESC LIMIT 200""",
            (timeframe,)
        ).fetchall()
        conn.close()

        if len(rows) < 10:
            return result

        # Count current run length
        current_run = 0
        for r in rows:
            if r["regime"] == current_regime:
                current_run += 1
            else:
                break
        result["duration_readings"] = current_run

        # Track to regime run tracker
        global _regime_run_tracker
        key = timeframe
        if key not in _regime_run_tracker or _regime_run_tracker[key]["regime"] != current_regime:
            _regime_run_tracker[key] = {"regime": current_regime, "count": current_run, "started": time.time()}
        else:
            _regime_run_tracker[key]["count"] = current_run

        # Calculate average regime duration from history
        regimes_list = [r["regime"] for r in reversed(rows)]
        run_lengths = []
        prev = None
        run_len = 0
        for r in regimes_list:
            if r == prev:
                run_len += 1
            else:
                if prev is not None:
                    run_lengths.append({"regime": prev, "length": run_len})
                prev = r
                run_len = 1
        if prev is not None:
            run_lengths.append({"regime": prev, "length": run_len})

        # Average duration for current regime type
        same_regime_runs = [rl["length"] for rl in run_lengths if rl["regime"] == current_regime]
        if same_regime_runs:
            avg_dur = np.mean(same_regime_runs)
            result["avg_duration"] = avg_dur
            # Fatigued if current run > 1.5x average
            if current_run > avg_dur * 1.5 and current_run >= 15:
                result["is_fatigued"] = True

        # What regime typically follows this one?
        transitions = {}
        for i in range(len(run_lengths) - 1):
            if run_lengths[i]["regime"] == current_regime:
                next_regime = run_lengths[i + 1]["regime"]
                transitions[next_regime] = transitions.get(next_regime, 0) + 1

        if transitions:
            total_transitions = sum(transitions.values())
            most_likely = max(transitions, key=transitions.get)
            result["likely_next"] = most_likely
            result["transition_prob"] = (transitions[most_likely] / total_transitions) * 100

    except Exception as e:
        log.warning(f"Regime fatigue check error: {e}")

    return result


def _track_spike_patterns(alert_intel, regime, atr_ratio):
    """
    V75 spike probability tracker.  Compression alerts during trending
    regimes are opportunity signals — V75 builds pressure then spikes.
    """
    cfg = V75_META_CONFIG["spike_config"]
    compression_count = alert_intel.get("compression_count", 0)

    probability = 0
    if compression_count >= cfg["min_compressions_for_spike"]:
        probability = min(0.95, cfg["spike_probability_base"] + compression_count * cfg["spike_probability_per_compression"])
        # ATR compression (low ratio) increases spike probability
        if atr_ratio < 0.7:
            probability = min(0.95, probability + 0.10)

    return {
        "spike_probable": probability >= 0.45,
        "probability": probability,
        "compression_count": compression_count,
        "atr_ratio": atr_ratio,
        "guidance": (
            f"Spike building — {probability:.0%} probability ({compression_count} compressions). Watch for breakout."
            if probability >= 0.45
            else "No spike pattern detected."
        ),
    }


def _check_timeframe_hierarchy_v75(bias_regime="unknown", bias_sub="unknown"):
    """
    V75-specific role-based TF hierarchy.
    1H = bias (truth), 15M = structure, 5M = timing, 1M = execution (noise).
    Only flags when STRUCTURE (15M) breaks against BIAS (1H).
    """
    alignment = {
        "alignment_points": 0,
        "tf_data": {},
        "structure_breakdown": None,
        "structure_leading": None,
    }
    warnings = []
    try:
        conn = get_db()
        tf_regimes = {}
        for tf in ["1m", "5m", "15m", "1h"]:
            row = conn.execute(
                "SELECT regime, confidence FROM regime_history WHERE timeframe=? ORDER BY timestamp DESC LIMIT 1",
                (tf,)
            ).fetchone()
            if row:
                tf_regimes[tf] = {"regime": row["regime"], "confidence": row["confidence"]}
        conn.close()

        alignment["tf_data"] = tf_regimes

        h1 = tf_regimes.get("1h", {}).get("regime", "unknown")
        m15 = tf_regimes.get("15m", {}).get("regime", "unknown")
        m5 = tf_regimes.get("5m", {}).get("regime", "unknown")
        # 1M is intentionally ignored for conflict detection

        # Award points for agreement
        points = 0

        # 1H exists and has a clear read
        if h1 in ("trending", "ranging"):
            points += 8

        # 15M (structure) agrees with 1H (bias)
        if h1 == m15:
            points += 12  # Full structure alignment
        elif h1 == "trending" and m15 == "ranging":
            # Structure is consolidating within trend — normal V75 pullback zone
            points += 6
            warnings.append(f"15M ranging within 1H trend — potential pullback/entry zone.")
        elif h1 == "trending" and m15 in ("choppy", "expanding"):
            # Structure is breaking — real warning
            alignment["structure_breakdown"] = (
                f"15M shows {m15.upper()} while 1H is TRENDING. "
                f"Market structure supporting the trend is degrading."
            )
            points += 0
        elif h1 != "unknown" and m15 != "unknown" and h1 != m15:
            # Structure disagrees but not catastrophically
            warnings.append(f"15M ({m15.upper()}) differs from 1H ({h1.upper()}) — structure may be shifting.")
            points += 3

        # 5M (timing) — bonus if it agrees, no penalty if it doesn't
        if m5 == h1:
            points += 5  # Timing aligns with bias

        # Check if lower TFs are leading a shift
        if h1 == "trending" and m15 != "trending" and m5 != "trending":
            alignment["structure_leading"] = (
                f"Both 15M ({m15.upper()}) and 5M ({m5.upper()}) have left trending. "
                f"1H may follow — early regime shift signal."
            )
            if alignment["structure_leading"]:
                warnings.append(alignment["structure_leading"])

        alignment["alignment_points"] = points

    except Exception as e:
        log.warning(f"TF hierarchy check error: {e}")

    return alignment, warnings


# Global cache for latest meta-analysis (updated every regime cycle)
_latest_meta_analysis = {}


def _interpret_market(regime_data, tendency_summary, setups_data, metrics_data, perf_data):
    """
    Core interpreter: takes current state from all panels and produces
    a human-readable market assessment with action guidance.

    Now enhanced with Meta-Analysis Engine integration.

    Returns dict with:
      - action: "LOOK FOR LONGS" / "LOOK FOR SHORTS" / "WAIT" / "SIT OUT"
      - conviction: "HIGH" / "MEDIUM" / "LOW" / "NONE"
      - narrative: Plain-English summary of what the market is doing
      - reasoning: List of bullet points explaining the assessment
      - warnings: List of caution items
      - edge_window: Whether current time is a high-performance window
      - meta: Meta-analysis results (alignment, conflicts, fatigue)
    """
    action = "WAIT"
    conviction = "NONE"
    reasoning = []
    warnings = []
    narrative = ""
    edge_window = False

    # --- 1. REGIME ASSESSMENT ---
    regime = regime_data.get("regime", "unknown")
    sub_regime = regime_data.get("sub_regime", "unknown")
    confidence = regime_data.get("confidence", 0)
    metrics = regime_data.get("metrics", {})

    adx = metrics.get("adx", 0) or 0
    hurst = metrics.get("hurst", 0.5) or 0.5
    atr_ratio = metrics.get("atr_ratio", 1.0) or 1.0
    autocorr = metrics.get("autocorrelation", 0) or 0

    # Regime narrative
    regime_narratives = {
        "trending": "The market is in a trending state — price has sustained directional momentum.",
        "ranging": "The market is range-bound — price is oscillating sideways without clear direction.",
        "expanding": "Volatility is expanding — the market is making outsized moves.",
        "choppy": "The market is choppy — no structure, no edge. Price is walking randomly.",
    }
    narrative = regime_narratives.get(regime, "Market state is unclear — waiting for enough data to classify.")

    # Sub-regime detail
    if sub_regime == "trending_up":
        narrative += " Bullish structure — price is above key moving averages with upward momentum."
        reasoning.append("Bullish trend: SMA20 > SMA50, price above both")
    elif sub_regime == "trending_down":
        narrative += " Bearish structure — price is below key moving averages with downward momentum."
        reasoning.append("Bearish trend: SMA20 < SMA50, price below both")
    elif sub_regime == "trending_mixed":
        narrative += " Trend strength is there but direction is unclear."
        reasoning.append("Mixed trend: ADX shows strength but MAs are tangled")
    elif sub_regime == "compressing":
        narrative += " Volatility is compressing — a breakout is likely building."
        reasoning.append("Compression phase: ATR shrinking, BB squeezing")
    elif sub_regime == "breakout_run":
        narrative += " A breakout is in progress — momentum is expanding."
        reasoning.append("Active breakout: expansion + multi-candle streak detected")
    elif sub_regime == "volatility_spike":
        narrative += " Volatile spike without clear direction — could be whipsaw."
        warnings.append("Volatility spike without directional commitment — be cautious")

    # Confidence assessment
    if confidence >= 70:
        reasoning.append(f"Regime confidence is strong at {confidence:.0f}% — classification is reliable")
    elif confidence >= 50:
        reasoning.append(f"Regime confidence is moderate at {confidence:.0f}% — market may be transitioning")
    else:
        warnings.append(f"Regime confidence is weak at {confidence:.0f}% — market between states, be cautious")

    # --- 2. INDICATOR QUALITY CHECK ---
    if adx > 25:
        reasoning.append(f"ADX at {adx:.1f} confirms real trend strength")
    elif adx < 15:
        warnings.append(f"ADX at {adx:.1f} — no trend exists. Momentum trades are risky")

    if hurst > 0.55:
        reasoning.append(f"Hurst at {hurst:.2f} — market is persistent, trends should continue")
    elif hurst < 0.45:
        reasoning.append(f"Hurst at {hurst:.2f} — market is anti-persistent, expect mean reversion")
    else:
        warnings.append(f"Hurst at {hurst:.2f} — near random walk territory, no statistical edge in direction")

    if atr_ratio > 1.5:
        warnings.append(f"ATR Ratio at {atr_ratio:.2f} — volatility is elevated, widen stops or reduce size")
    elif atr_ratio < 0.6:
        reasoning.append(f"ATR Ratio at {atr_ratio:.2f} — compression, breakout conditions building")

    if abs(autocorr) > 0.3:
        dir_label = "bullish" if autocorr > 0 else "bearish"
        reasoning.append(f"Autocorrelation at {autocorr:.2f} — returns are persisting ({dir_label} momentum)")
    elif abs(autocorr) < 0.1:
        warnings.append(f"Autocorrelation at {autocorr:.2f} — each bar is independent, no momentum edge")

    # --- 3. TENDENCY ALIGNMENT ---
    tendency_bias = "neutral"
    tendency_strength = 0
    tendency_quality = "low"

    if tendency_summary:
        tendency_bias = tendency_summary.get("bias", "neutral")
        tendency_strength = tendency_summary.get("strength", 0)
        tendency_quality = tendency_summary.get("quality", "low")

        if tendency_quality == "high":
            edge_window = True
            reasoning.append(f"Tendency quality is HIGH — current time window produces clean moves")
        elif tendency_quality == "medium":
            reasoning.append(f"Tendency quality is MEDIUM — decent but not optimal conditions")
        else:
            warnings.append("Tendency quality is LOW — current time window is historically noisy")

        if tendency_strength > 60:
            reasoning.append(f"Tendency points {tendency_bias.upper()} with {tendency_strength:.0f}% strength")
        elif tendency_strength > 30:
            reasoning.append(f"Tendency leans {tendency_bias.upper()} but strength is moderate ({tendency_strength:.0f}%)")

    # --- 4. SETUP ASSESSMENT ---
    best_setup = None
    setup_count = 0
    setup_list = []

    if setups_data and isinstance(setups_data, dict):
        raw_setups = setups_data.get("setups", [])
        if isinstance(raw_setups, list):
            setup_count = len(raw_setups)
            # Sort by composite score
            sorted_setups = sorted(raw_setups, key=lambda s: s.get("composite_score", 0), reverse=True)
            for s in sorted_setups:
                name_map = {
                    "compression_breakout": "Compression Breakout",
                    "pullback_to_trend": "Pullback to Trend",
                    "mean_reversion": "Mean Reversion",
                    "streak_exhaustion": "Streak Exhaustion",
                    "order_block_touch": "Order Block Touch",
                }
                sname = name_map.get(s.get("type", ""), s.get("type", "Unknown"))
                sdir = s.get("direction", "neutral")
                sconf = s.get("confidence", 0)
                scomp = s.get("composite_score", 0)
                stag = s.get("regime_tag", "")
                setup_list.append({
                    "name": sname, "direction": sdir, "confidence": sconf,
                    "composite": scomp, "tag": stag, "type": s.get("type", ""),
                })

            if sorted_setups:
                best_setup = setup_list[0]

    if best_setup:
        if best_setup["composite"] >= 60:
            reasoning.append(f"A+ setup active: {best_setup['name']} ({best_setup['direction']}) — composite {best_setup['composite']:.0f}")
        elif best_setup["composite"] >= 35:
            reasoning.append(f"Decent setup: {best_setup['name']} ({best_setup['direction']}) — composite {best_setup['composite']:.0f}")
        else:
            warnings.append(f"Weak setup: {best_setup['name']} only scores {best_setup['composite']:.0f} composite — regime doesn't support it well")

        if best_setup["tag"] == "CAUTION":
            warnings.append(f"{best_setup['name']} has CAUTION tag — regime works against this setup type")
    else:
        reasoning.append("No active setups detected — no pattern with edge right now")

    # --- 5. PERFORMANCE CONTEXT ---
    if perf_data and perf_data.get("trade_count", 0) > 0:
        overall = perf_data.get("overall", {})
        expectancy = overall.get("expectancy_r", 0)
        win_rate = overall.get("win_rate", 0)

        if expectancy > 0:
            reasoning.append(f"Your expectancy is positive ({expectancy:.2f}R) — your method has edge")
        elif expectancy < 0 and perf_data.get("trade_count", 0) >= 10:
            warnings.append(f"Your expectancy is negative ({expectancy:.2f}R) — review your approach before trading more")

        # Check regime-specific performance
        by_regime = perf_data.get("by_regime", {})
        if regime in by_regime:
            regime_perf = by_regime[regime]
            regime_wr = regime_perf.get("win_rate", 0)
            regime_exp = regime_perf.get("expectancy_r", 0)
            regime_trades = regime_perf.get("count", 0)
            if regime_trades >= 5:
                if regime_exp > 0:
                    reasoning.append(f"You perform well in {regime.upper()} regimes ({regime_wr:.0f}% WR, {regime_exp:.2f}R expectancy)")
                elif regime_exp < 0:
                    warnings.append(f"You LOSE money in {regime.upper()} regimes ({regime_wr:.0f}% WR, {regime_exp:.2f}R) — consider sitting this one out")

    # --- 6. SYNTHESIZE ACTION ---
    if regime == "choppy":
        action = "SIT OUT"
        conviction = "HIGH"
        narrative += " There is no statistical edge in choppy conditions. Protect your capital."
    elif regime == "trending":
        if sub_regime == "trending_up":
            if tendency_bias in ("bullish", "neutral") and tendency_quality != "low":
                if best_setup and best_setup["composite"] >= 35 and best_setup["direction"] == "bullish":
                    action = "LOOK FOR LONGS"
                    conviction = "HIGH" if best_setup["composite"] >= 60 and edge_window else "MEDIUM"
                elif not best_setup or best_setup["composite"] < 35:
                    action = "LOOK FOR LONGS"
                    conviction = "LOW"
                    reasoning.append("Regime supports longs but no strong setup yet — wait for a pullback or pattern")
                else:
                    action = "WAIT"
                    conviction = "LOW"
                    reasoning.append("Setup direction doesn't match bullish trend — wait for alignment")
            else:
                action = "LOOK FOR LONGS"
                conviction = "LOW"
                if tendency_quality == "low":
                    warnings.append("Trend is up but current time window quality is low — reduce size")
        elif sub_regime == "trending_down":
            if tendency_bias in ("bearish", "neutral") and tendency_quality != "low":
                if best_setup and best_setup["composite"] >= 35 and best_setup["direction"] == "bearish":
                    action = "LOOK FOR SHORTS"
                    conviction = "HIGH" if best_setup["composite"] >= 60 and edge_window else "MEDIUM"
                elif not best_setup or best_setup["composite"] < 35:
                    action = "LOOK FOR SHORTS"
                    conviction = "LOW"
                    reasoning.append("Regime supports shorts but no strong setup yet — wait for a pullback or pattern")
                else:
                    action = "WAIT"
                    conviction = "LOW"
                    reasoning.append("Setup direction doesn't match bearish trend — wait for alignment")
            else:
                action = "LOOK FOR SHORTS"
                conviction = "LOW"
                if tendency_quality == "low":
                    warnings.append("Trend is down but current time window quality is low — reduce size")
        else:
            # trending_mixed
            action = "WAIT"
            conviction = "LOW"
            reasoning.append("Trend strength is there but direction is mixed — wait for clarity")

    elif regime == "ranging":
        if best_setup and best_setup["type"] in ("mean_reversion", "order_block_touch"):
            if best_setup["composite"] >= 40:
                action = f"LOOK FOR {best_setup['direction'].upper()}S"
                conviction = "MEDIUM" if best_setup["composite"] >= 55 else "LOW"
                reasoning.append(f"Range-bound — {best_setup['name']} is the right play here")
            else:
                action = "WAIT"
                conviction = "LOW"
                reasoning.append("Range setup forming but not strong enough yet")
        elif best_setup and best_setup["type"] == "compression_breakout":
            action = "WAIT"
            conviction = "MEDIUM"
            reasoning.append("Compression building in range — prepare for breakout direction")
        else:
            action = "WAIT"
            conviction = "LOW"
            reasoning.append("Ranging with no clear setup — patience required")

    elif regime == "expanding":
        if sub_regime == "breakout_run":
            if best_setup and best_setup["composite"] >= 40:
                action = f"LOOK FOR {best_setup['direction'].upper()}S"
                conviction = "MEDIUM"
                reasoning.append("Breakout in progress — trade the momentum but watch for exhaustion")
            else:
                action = "WAIT"
                conviction = "LOW"
                warnings.append("Expansion without clear setup — could be a whipsaw. Wait for structure.")
        else:
            action = "WAIT"
            conviction = "LOW"
            warnings.append("Volatility expanding without clean breakout — dangerous to enter now")

    # Downgrade conviction if regime confidence is weak
    if confidence < 50 and conviction == "HIGH":
        conviction = "MEDIUM"
        warnings.append("Conviction downgraded — regime classification is uncertain")

    # Downgrade if tendency quality is low
    if tendency_quality == "low" and conviction == "HIGH":
        conviction = "MEDIUM"

    # --- 7. META-ANALYSIS INTEGRATION ---
    global _latest_meta_analysis
    try:
        meta = run_meta_analysis(regime_data, tendency_summary, setups_data, metrics_data)
        _latest_meta_analysis = meta

        # Auto-downgrade conviction based on alignment score
        if meta["alignment_score"] < 40:
            if action not in ("WAIT", "SIT OUT"):
                action = "WAIT"
                conviction = "LOW"
                narrative += " META-OVERRIDE: System alignment is CRITICAL — panels are heavily contradicting each other. Signals are unreliable."
                warnings.append(f"System alignment score: {meta['alignment_score']}/100 — DO NOT TRADE")
            elif conviction in ("HIGH", "MEDIUM"):
                conviction = "LOW"
        elif meta["alignment_score"] < 60:
            if conviction == "HIGH":
                conviction = "MEDIUM"
                warnings.append(f"Conviction downgraded by meta-analysis — alignment score {meta['alignment_score']}/100")

        # Add meta-conflicts to warnings
        for c in meta.get("conflicts", []):
            if c["severity"] == "high":
                warnings.append(f"CONFLICT: {c['description']}")

        # Add meta-warnings
        for mw in meta.get("meta_warnings", []):
            warnings.append(mw)

        # Enhance narrative with meta context
        if meta.get("regime_fatigue", {}).get("is_fatigued"):
            narrative += f" Note: {regime.upper()} regime is aging — transition probability is elevated."

    except Exception as e:
        log.warning(f"Meta-analysis integration error: {e}")
        meta = {}

    return {
        "action": action,
        "conviction": conviction,
        "narrative": narrative,
        "reasoning": reasoning,
        "warnings": warnings,
        "edge_window": edge_window,
        "setup_count": setup_count,
        "best_setup": best_setup,
        "regime": regime,
        "sub_regime": sub_regime,
        "tendency_bias": tendency_bias,
        "tendency_strength": tendency_strength,
        "tendency_quality": tendency_quality,
        "meta": meta,
    }


# Click-to-explain dictionary — contextual explanations for dashboard elements
EXPLAIN_DICT = {
    # Panel A — Regime
    "regime": {
        "title": "Market Regime",
        "explanation": "The regime tells you WHAT STATE the market is in. V75 cycles through 4 states: Trending (sustained moves), Ranging (sideways), Expanding (volatility spike), Choppy (random noise). Every decision on this dashboard starts here — the regime determines which setups work and which don't.",
        "how_to_use": "Check regime FIRST before any trade. If it says CHOPPY, don't trade. If it says TRENDING, look for pullback entries. If RANGING, look for mean reversion at extremes."
    },
    "confidence": {
        "title": "Regime Confidence",
        "explanation": "How clearly the market fits the current classification. Calculated from how strongly the indicators agree. 70%+ means the regime is well-defined. Below 50% means the market is between states.",
        "how_to_use": "Trade with full size at 70%+. Reduce size at 50-70%. Below 50%, wait — the market is transitioning and setups are unreliable."
    },
    "sub_regime": {
        "title": "Sub-Regime",
        "explanation": "More specific classification within the main regime. 'trending_up' means bullish trend (price above MAs). 'compressing' means volatility is shrinking — breakout coming. 'breakout_run' means an expansion is already happening.",
        "how_to_use": "Use sub-regime to determine DIRECTION. The main regime tells you the strategy type, the sub-regime tells you which way."
    },
    "tf_strip": {
        "title": "Multi-Timeframe Regime Strip",
        "explanation": "Shows the regime classification on ALL timeframes simultaneously. A trending 1M inside a ranging 4H means you're in a short-term pullback within a larger range. When all timeframes agree, the signal is strongest.",
        "how_to_use": "Look for alignment. If 1H and 4H both say TRENDING in the same direction, that's a high-conviction environment. If they disagree, use the higher timeframe as context."
    },
    "regime_scores": {
        "title": "Regime Score Bars",
        "explanation": "Shows how much each regime scored in the voting system. The indicators (ADX, Hurst, ATR Ratio, Autocorrelation) each cast votes. The highest scoring regime wins. If two regimes are close, the market is between states.",
        "how_to_use": "Check the gap between the winning regime and the second place. A big gap = clear regime. Close scores = transition zone — be careful."
    },
    # Panel A — Metrics
    "adx": {
        "title": "ADX (Average Directional Index)",
        "explanation": "Measures TREND STRENGTH, not direction. Uses Wilder's smoothing method over 14 bars. Above 25 means a real trend exists. Below 15 means there's no trend at all. Between 15-25 is a weak/forming trend.",
        "how_to_use": "ADX > 25 = trade WITH the trend (pullbacks, momentum). ADX < 15 = don't take trend trades. ADX rising = trend strengthening. ADX falling = trend weakening even if price is still moving."
    },
    "atr_ratio": {
        "title": "ATR Ratio (Current ATR / 50-bar Average ATR)",
        "explanation": "Compares current volatility to recent average. ATR Ratio > 1.5 means volatility is expanding (bigger candles than usual). Below 0.6 means compression (smaller candles — something is building).",
        "how_to_use": "Above 1.5: widen your stops (normal stops will get hit by noise) or reduce position size. Below 0.6: tighten stops and watch for a breakout. Between 0.6-1.5: normal conditions, use standard stops."
    },
    "hurst": {
        "title": "Hurst Exponent",
        "explanation": "Statistical measure of whether price movements persist or revert. Calculated via Rescaled Range (R/S) analysis. H > 0.55 = PERSISTENT (trends continue). H < 0.45 = ANTI-PERSISTENT (moves reverse). H ≈ 0.50 = RANDOM WALK (no edge in direction).",
        "how_to_use": "This is the most important number most traders ignore. If Hurst > 0.55, follow the trend — it statistically continues. If Hurst < 0.45, fade moves — they statistically reverse. At 0.50, there is NO statistical edge in predicting direction."
    },
    "autocorrelation": {
        "title": "Autocorrelation (Lag-1)",
        "explanation": "Measures whether each bar's return predicts the next bar's return. Positive autocorrelation = momentum (up follows up). Negative = mean reversion (up follows down). Near zero = independent (no prediction possible).",
        "how_to_use": "|Autocorr| > 0.3: momentum is real, trade continuations. |Autocorr| < 0.1: each bar is random relative to the last — don't expect follow-through. Negative values below -0.3: strong mean reversion — fade every impulse."
    },
    "bb_width": {
        "title": "Bollinger Band Width",
        "explanation": "Measures how far apart the upper and lower Bollinger Bands are. Low BB Width = bands are tight = compression = breakout building. High BB Width = bands are wide = expansion/high volatility.",
        "how_to_use": "Historically low BB Width (compression) precedes breakouts. Watch for the expansion. Historically high BB Width means the big move may already be happening — late entries are risky."
    },
    "bb_position": {
        "title": "Bollinger Band Position (%B)",
        "explanation": "Where price sits within the Bollinger Bands. 0 = at the lower band. 0.5 = at the middle (20 SMA). 1.0 = at the upper band. Above 1 or below 0 = price has broken outside the bands.",
        "how_to_use": "In a RANGING regime: %B near 0 = potential long (price at support). %B near 1 = potential short (price at resistance). In a TRENDING regime: %B staying above 0.5 = healthy uptrend. Don't fade it."
    },
    # Panel A — Streak
    "streak": {
        "title": "Streak Behavior",
        "explanation": "Counts consecutive same-direction candles. The current streak count, average streak length, max streak, and standard deviation tell you if the current run is normal or exceptional. If current streak > avg + 1.5σ, it's statistically exhausted.",
        "how_to_use": "Long streak approaching avg + 1.5× std dev = exhaustion zone. Expect a pause or reversal. Short streak in a trending regime = pullback opportunity. The streak exhaustion setup detector uses this data."
    },
    # Panel B — Tendency
    "tendency_summary": {
        "title": "Tendency Summary",
        "explanation": "Synthesizes hour-of-day, day-of-week, session, and rolling momentum into one verdict. Shows: BIAS (bullish/bearish/neutral), STRENGTH (how strong the consensus is), and QUALITY (how clean the expected moves are).",
        "how_to_use": "Only trade in the tendency direction when quality is HIGH. When quality is LOW, either reduce size or wait. The tendency replaces gut feeling about 'when to trade' with statistical evidence."
    },
    "hourly_heatmap": {
        "title": "Hourly Heatmap",
        "explanation": "Each cell is one hour of the day (UTC). Color shows directional bias: green = historically more bullish bars, red = more bearish. Stars show statistical significance: *** = 99% confidence, ** = 95%, * = 90%. No star = might just be noise.",
        "how_to_use": "Find green/red hours with stars. Trade during those hours in that direction. Hours with no star and grey color = no statistical edge — you're gambling, not trading."
    },
    "session_analysis": {
        "title": "Session Analysis",
        "explanation": "V75 runs 24/7 but may behave differently during real-market hours. Sessions: Asian (00-08 UTC), London (08-16 UTC), LDN/NY Overlap (13-16 UTC), New York (16-21 UTC), Late NY (21-00 UTC).",
        "how_to_use": "Cross-reference with your performance tracker. If you win more in London and the tendency engine confirms London is structurally better — that's your edge window. Trade there, reduce elsewhere."
    },
    "rolling_momentum": {
        "title": "Rolling Momentum (20/40/60-bar)",
        "explanation": "Replaces manual liquidity projections. Shows directional momentum over 3 windows. Return % = total move. Consistency = what % of bars were bullish (>70% = very consistent trend). Strength = magnitude × consistency.",
        "how_to_use": "When all 3 windows agree on direction with high consistency = strong trend. When they disagree = transition. 20-bar turning while 60-bar holds = short-term pullback in larger trend."
    },
    "monthly_seasonal": {
        "title": "Monthly Seasonal Strip",
        "explanation": "Replaces manual color-coded seasonal charts. Each month shows its historical bullish %, average return, and volatility. Z-score indicates if the tendency is statistically real or just noise.",
        "how_to_use": "Green month with high z-score = statistically real seasonal bullish tendency. Colored month with low z-score = not enough evidence, might be coincidence. Use as a background bias, not a primary signal."
    },
    "quarterly_analysis": {
        "title": "Quarterly Cycle Analysis",
        "explanation": "Replaces manual quarterly shift analysis. Shows Q1-Q4 directional profiles, Early/Mid/Late phase breakdown within each quarter, and shift detection at quarter boundaries.",
        "how_to_use": "Check which phase of the quarter you're in. If the current quarter-phase historically trends, align with it. Shift analysis shows if behaviour changes at quarter boundaries — useful for your ICT quarterly theory."
    },
    # Panel C — Setups
    "setup_confidence": {
        "title": "Setup Confidence Score",
        "explanation": "How cleanly the detected pattern matches the ideal template. 65+ = high confidence, the pattern is well-formed. 40-65 = moderate, needs more confirmation. Below 40 = early formation or weak pattern.",
        "how_to_use": "Only act on setups with 65+ confidence for full size. 40-65 can work but reduce size. Below 40, the setup is just forming — monitor it but don't trade it yet."
    },
    "composite_score": {
        "title": "Composite Score",
        "explanation": "THE most important setup number. Calculated as Confidence × Regime Compatibility. A 90-confidence setup in a CAUTION regime might only score 30 composite. This forces you to consider whether the environment supports the pattern.",
        "how_to_use": "60+ composite = A+ trade. Take it with conviction. 35-60 = decent but conditions aren't perfect — reduce size. Below 35 = the regime works against this setup. Skip it."
    },
    "regime_tag": {
        "title": "Regime Compatibility Tag",
        "explanation": "IDEAL = this setup type thrives in the current regime (e.g., pullback in trending). OKAY = it can work but conditions aren't optimal. CAUTION = the regime actively works against this setup type (e.g., trend follow in ranging market).",
        "how_to_use": "IDEAL setups get full size. OKAY setups get reduced size. CAUTION setups should be SKIPPED entirely — even if the pattern looks clean, the regime will work against you."
    },
    "compression_breakout": {
        "title": "Setup: Compression Breakout",
        "explanation": "Detects Bollinger Band squeeze (volatility compression to historical lows) followed by expansion. When BB width drops below the 15th percentile and price breaks out with ATR expansion, this fires. Your ICT equivalent: consolidation → displacement → expansion.",
        "how_to_use": "Best in RANGING → EXPANDING transitions. Stage 'compression' = building, set alerts. Stage 'breakout' = entering. Trade in the breakout direction. Stop below the compression range."
    },
    "pullback_to_trend": {
        "title": "Setup: Pullback to Trend",
        "explanation": "Detects price pulling back to the 20 EMA zone during a confirmed trend (ADX > 22). Looks for wick rejection at the zone as entry confirmation. Your ICT equivalent: pullback to order block within established trend.",
        "how_to_use": "Best in TRENDING regime. Stage 'approaching' = watch it. Stage 'rejection' = entry signal. Trade in the trend direction. Stop below the EMA zone + a small buffer."
    },
    "mean_reversion": {
        "title": "Setup: Mean Reversion",
        "explanation": "Detects RSI extremes (< 28 oversold, > 72 overbought) confirmed by Hurst < 0.5 (anti-persistent behavior) and price at Bollinger Band edge. Your ICT equivalent: liquidity sweep at range extreme → rejection.",
        "how_to_use": "Best in RANGING regime. Works AGAINST trend in trending regimes (CAUTION). Look for RSI divergence as extra confirmation. Stop beyond the extreme wick."
    },
    "streak_exhaustion": {
        "title": "Setup: Streak Exhaustion",
        "explanation": "Detects when the current streak exceeds mean + 1.5 standard deviations AND bar-over-bar returns are shrinking (momentum dying). Your ICT equivalent: extended move that's run out of steam. Turtle soup.",
        "how_to_use": "This is a fade/reversal signal. The move has gone too far statistically. Look for confirmation (wick rejection, volume spike) before entering the counter-trade. Best late in trends."
    },
    "order_block_touch": {
        "title": "Setup: Order Block Touch",
        "explanation": "Finds historical zones where price made a large candle + displacement (institutional reaction), then detects price returning to that zone with wick rejection. This IS your ICT order block methodology, automated and quantified.",
        "how_to_use": "Best in TRENDING regime where OBs align with the trend. The detector shows the zone level and rejection quality. Enter on the rejection, stop beyond the OB zone. OBs against the trend are lower probability."
    },
    # Panel D — Risk
    "atr_stop": {
        "title": "ATR-Based Stop Calculator",
        "explanation": "Uses Average True Range to set stops based on actual market volatility. Tight = 1× ATR, Normal = 1.5× ATR, Wide = 2× ATR. Stops are placed at price ± ATR distance. Volatility-adaptive — as the market gets more volatile, stops automatically widen.",
        "how_to_use": "Tight stops for high-conviction setups (IDEAL tag + high composite). Normal stops for standard trades. Wide stops for uncertain conditions or higher timeframes. The comparison strip shows all three side by side."
    },
    "position_size": {
        "title": "Position Sizing",
        "explanation": "Calculates lot size using: (Account Balance × Risk %) ÷ Stop Distance. The dashboard also adjusts for current volatility — high vol reduces size (protection), low vol slightly increases it. This prevents you from over-sizing in wild markets.",
        "how_to_use": "Enter your real account balance and risk percentage. The calculator does the rest. NEVER override the position size manually — if you're tempted to increase it, your conviction is emotional, not statistical."
    },
    "rr_targets": {
        "title": "R:R Targets",
        "explanation": "Shows take-profit levels at 1:1.5R, 1:2R, and 1:3R based on your stop distance. R = the amount you're risking. At 1:2R, you make 2× what you risked if the trade hits target.",
        "how_to_use": "Default to 1:2R targets. Use 1:3R only for A+ setups with strong regime + tendency alignment. Use 1:1.5R when conditions are less certain. Your profit factor depends on getting this right."
    },
    "frequency_governor": {
        "title": "Trade Frequency Governor",
        "explanation": "Tracks your trades per session and per day. Enforces hard limits and cooldowns after consecutive losses. Green light = you can trade. Red light = STOP, you've hit your limit or are on a loss streak.",
        "how_to_use": "The red light is NON-NEGOTIABLE. When it fires, close your charts and walk away. Every trader's #1 account killer is overtrading after losses. This governor prevents that."
    },
    # Panel E — Performance
    "win_rate": {
        "title": "Win Rate",
        "explanation": "Percentage of trades that were profitable. Meaningless in isolation — a 40% win rate with 1:3 R:R is more profitable than 60% with 1:0.5 R:R. Always read together with Profit Factor and Expectancy.",
        "how_to_use": "Don't optimize for high win rate. Optimize for positive expectancy. Many profitable systems have win rates below 50% because winners are much larger than losers."
    },
    "expectancy": {
        "title": "Expectancy (R)",
        "explanation": "Average R-multiple per trade. The single most important performance metric. Positive = you have edge. Negative = you're losing money on average. Calculated as: (Win% × Avg Win R) - (Loss% × Avg Loss R).",
        "how_to_use": "If positive, keep trading your system. If negative with 20+ trades, something fundamental needs to change — review which regimes and setups are dragging you down using the breakdown tabs."
    },
    "profit_factor": {
        "title": "Profit Factor",
        "explanation": "Total gross profit ÷ Total gross loss. Above 1.0 = profitable. Above 1.5 = good system. Above 2.0 = excellent. Below 1.0 = losing money overall.",
        "how_to_use": "Track this over time. If it's declining, you're taking more bad trades or your winners are getting smaller. Cross-reference with the regime breakdown — maybe you started trading in regimes where you don't have edge."
    },
    "perf_by_regime": {
        "title": "Performance by Regime",
        "explanation": "Shows your win rate, profit factor, and expectancy broken down by market regime. This is WHY the dashboard exists — it reveals which regimes you're profitable in and which are killing your account.",
        "how_to_use": "If you're profitable in trending but losing in ranging — ONLY trade trending regimes. If you're losing in choppy — Panel A already tells you not to trade choppy. This data proves it with your actual money."
    },
    # Panel F — Alerts
    "regime_shift_alert": {
        "title": "Regime Shift Alert",
        "explanation": "Fires when the market regime changes (e.g., trending → ranging). Critical severity on 1H/4H timeframes because these are structural changes. Warning on lower TFs because regime changes faster there.",
        "how_to_use": "STOP everything when a 1H/4H regime shift fires. Re-read all panels. A regime change means your current setups may no longer be valid. Close positions that don't fit the new regime."
    },
    "setup_confluence_alert": {
        "title": "Setup Confluence Alert",
        "explanation": "Fires when 2+ high-confidence setups are detected on the same timeframe, all pointing the same direction. This is rare and powerful — multiple patterns agreeing at once.",
        "how_to_use": "This is your A+ trade signal. When confluence fires: confirm regime supports it, confirm tendency aligns, calculate position size, and execute. These are the trades that make your month."
    },
    "compression_alert": {
        "title": "Compression Alert",
        "explanation": "Fires when Bollinger Band Width drops to the 15th percentile or below — meaning the bands are tighter than 85% of recent history. This is a statistical precursor to a breakout. The market is coiling and energy is building.",
        "how_to_use": "When this fires, PREPARE. Don't enter yet — set your alerts and levels. Watch for the expansion candle that breaks the compression range. Enter on the breakout direction. This is your 'get ready' signal, not your 'go' signal."
    },
    "time_window_alert": {
        "title": "High-Performance Time Window Alert",
        "explanation": "Fires when the next hour has a statistically significant tendency — meaning the Tendency Engine identified it as a high-probability trading hour based on historical data. The z-score passed the significance threshold.",
        "how_to_use": "This is your 'be at the screen' signal. The upcoming hour historically produces clean, directional moves. Open your charts, check what the Tendency Engine says about direction, and look for setups aligning with the tendency."
    },
    "overtrading_alert": {
        "title": "Overtrading Alert",
        "explanation": "Fires when you've logged 5+ trades within a 2-hour window. This is a CRITICAL discipline alert. Overtrading is the #1 account killer — it signals emotional trading, revenge trading, or chasing. The frequency governor also triggers a red light.",
        "how_to_use": "STOP TRADING IMMEDIATELY. Close your charts. Walk away for at least 30 minutes. Review your last 5 trades — were they all planned setups or were some impulse entries? This alert exists to protect your capital from yourself."
    },
    "streak_exhaustion_alert": {
        "title": "Streak Exhaustion Alert",
        "explanation": "Fires when the current candle streak (consecutive same-direction bars) exceeds the mean + 1.5 standard deviations. Statistically, the move is overextended. Bar-by-bar returns are often shrinking at this point — momentum is dying.",
        "how_to_use": "DON'T chase this move. The streak is statistically exhausted. If you're already in a trade in the streak direction, consider tightening your stop or taking partial profit. If you're looking for entries, look for reversal confirmation — this is where the Streak Exhaustion setup fires."
    },
    # Panel C — Scanner-level explanations
    "setup_scanner": {
        "title": "Setup Scanner",
        "explanation": "The Setup Scanner runs 5 pattern detectors against live price data: Compression Breakout, Pullback to Trend, Mean Reversion, Streak Exhaustion, and Order Block Touch. Each setup gets a confidence score (pattern quality) and a regime compatibility tag (IDEAL/OKAY/CAUTION). The composite score combines both.",
        "how_to_use": "Don't trade every setup that appears. Wait for composite scores above 50 with IDEAL or OKAY tags. The best trades come when a setup aligns with both the regime (Panel A) and the tendency (Panel B). Click any setup card for a detailed explanation of that specific pattern."
    },
    "setup_mtf": {
        "title": "Multi-Timeframe Scanner",
        "explanation": "Scans ALL timeframes (1M through 4H) simultaneously and shows how many setups are active on each. When multiple timeframes show setups pointing the same direction, the signal is much stronger. A single setup on 1M alone is weak — the same setup on 15M + 1H is powerful.",
        "how_to_use": "Look for timeframe alignment. If the 1H shows a Pullback to Trend and the 15M shows a Compression Breakout in the same direction — that's confluence. The more timeframes that agree, the higher your conviction should be."
    },
    # Panel F — System-level explanation
    "alert_system": {
        "title": "Alert System",
        "explanation": "The alert engine runs every 30 seconds in the background, scanning for 6 conditions: regime shifts, compression forming, high-performance time windows approaching, overtrading, streak exhaustion, and setup confluence. Alerts are severity-coded: CRITICAL (red) demands immediate action, WARNING (amber) means prepare, INFO (blue) is awareness. Each alert type has a cooldown to prevent spam.",
        "how_to_use": "CRITICAL alerts override everything — stop what you're doing and respond. Regime shifts on 1H/4H mean your open positions may no longer be valid. Overtrading alerts are non-negotiable stops. Setup confluence alerts are your best trade opportunities. Click any individual alert to understand what it means and what action to take."
    },
}


@app.route("/api/interpret/<timeframe>")
def api_interpret(timeframe):
    """
    AI Interpreter endpoint — synthesizes all panel data into
    a market read with directional guidance and reasoning.
    """
    if timeframe not in TIMEFRAMES:
        return jsonify({"error": f"Invalid timeframe: {timeframe}"}), 400

    try:
        conn = get_db()

        # 1. Get current regime
        rows = conn.execute(
            """SELECT timestamp, open, high, low, close FROM candles
               WHERE timeframe=? ORDER BY timestamp DESC LIMIT 200""",
            (timeframe,),
        ).fetchall()

        regime_data = {"regime": "unknown", "sub_regime": "unknown", "confidence": 0, "metrics": {}}
        if len(rows) >= 50:
            rows_asc = list(reversed(rows))
            df = pd.DataFrame(rows_asc, columns=["timestamp", "open", "high", "low", "close"])
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col])
            regime_data = classify_regime(df)

        # 2. Get tendency summary
        tendency_summary = None
        try:
            closes = [float(r["close"]) for r in reversed(rows)]
            if len(closes) >= 50:
                tendency_result = calc_tendency_analysis(closes, timeframe)
                tendency_summary = tendency_result.get("summary")
        except Exception:
            pass

        # 3. Get active setups
        setups_data = None
        try:
            rows_asc = list(reversed(rows))
            highs = [float(r["high"]) for r in rows_asc]
            lows = [float(r["low"]) for r in rows_asc]
            closes_list = [float(r["close"]) for r in rows_asc]
            opens_list = [float(r["open"]) for r in rows_asc]
            setups_data = scan_all_setups(opens_list, highs, lows, closes_list, regime_data)
        except Exception:
            pass

        # 4. Get metrics
        metrics_data = regime_data.get("metrics", {})

        # 5. Get performance data
        perf_data = None
        try:
            trade_rows = conn.execute("SELECT * FROM trade_log ORDER BY entry_time ASC").fetchall()
            trades = [dict(r) for r in trade_rows]
            if trades:
                perf_data = {
                    "overall": calc_performance_stats(trades),
                    "by_regime": calc_performance_by_regime(trades),
                    "trade_count": len(trades),
                }
        except Exception:
            pass

        conn.close()

        # 6. Run interpreter
        result = _interpret_market(regime_data, tendency_summary, setups_data, metrics_data, perf_data)
        return jsonify(sanitize_for_json(result))

    except Exception as e:
        log.error(f"Interpreter error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/meta/<timeframe>")
def api_meta(timeframe):
    """
    Meta-Analysis endpoint — returns system alignment score,
    signal conflicts, regime fatigue, and alert intelligence.
    """
    if timeframe not in TIMEFRAMES:
        return jsonify({"error": f"Invalid timeframe: {timeframe}"}), 400

    try:
        conn = get_db()
        rows = conn.execute(
            """SELECT timestamp, open, high, low, close FROM candles
               WHERE timeframe=? ORDER BY timestamp DESC LIMIT 200""",
            (timeframe,),
        ).fetchall()

        regime_data = {"regime": "unknown", "sub_regime": "unknown", "confidence": 0, "metrics": {}}
        if len(rows) >= 50:
            rows_asc = list(reversed(rows))
            df = pd.DataFrame(rows_asc, columns=["timestamp", "open", "high", "low", "close"])
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col])
            regime_data = classify_regime(df)

        # BUG FIX: Use actual tendency function chain (calc_tendency_analysis didn't exist)
        tendency_summary = None
        try:
            data = _get_candle_arrays(timeframe, limit=500)
            if data:
                timestamps, opens_t, highs_t, lows_t, closes_t = data
                hourly = calc_hourly_tendency(timestamps, opens_t, highs_t, lows_t, closes_t)
                weekday = calc_weekday_tendency(timestamps, opens_t, highs_t, lows_t, closes_t)
                session = calc_session_tendency(timestamps, opens_t, highs_t, lows_t, closes_t)
                rolling = calc_rolling_tendency(timestamps, closes_t)
                tendency_summary = calc_current_tendency_summary(hourly, weekday, session, rolling)
        except Exception:
            pass

        # BUG FIX: scan_all_setups takes (closes, highs, lows, regime_data) — not 5 args
        setups_data = None
        try:
            rows_asc = list(reversed(rows))
            highs = [float(r["high"]) for r in rows_asc]
            lows = [float(r["low"]) for r in rows_asc]
            closes_list = [float(r["close"]) for r in rows_asc]
            setups_data = scan_all_setups(closes_list, highs, lows, regime_data)
        except Exception:
            pass

        metrics_data = regime_data.get("metrics", {})
        conn.close()

        result = run_meta_analysis(regime_data, tendency_summary, setups_data, metrics_data, timeframe)
        return jsonify(sanitize_for_json(result))

    except Exception as e:
        log.error(f"Meta-analysis error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/explain/<key>")
def api_explain(key):
    """Return contextual explanation for a dashboard element."""
    entry = EXPLAIN_DICT.get(key)
    if not entry:
        return jsonify({"error": f"No explanation found for '{key}'"}), 404
    return jsonify(entry)


@app.route("/api/explain")
def api_explain_all():
    """Return all available explanation keys (for reference)."""
    keys = [{"key": k, "title": v["title"]} for k, v in EXPLAIN_DICT.items()]
    return jsonify(keys)


# ---------------------------------------------------------------------------
# Interactive Q&A Engine (Phase 5 — Chat Assistant)
# ---------------------------------------------------------------------------
# Rule-based question answering that reads live dashboard state and the
# EXPLAIN_DICT to give contextual, data-aware answers.
# ---------------------------------------------------------------------------

# Keyword → topic mapping for question routing
_QA_TOPICS = {
    "regime": ["regime", "state", "market state", "what state", "trending", "ranging", "expanding", "choppy", "classification"],
    "adx": ["adx", "trend strength", "directional index", "how strong is the trend"],
    "hurst": ["hurst", "persistent", "anti-persistent", "random walk", "mean revert"],
    "atr": ["atr", "average true range", "volatility", "atr ratio", "vol ratio"],
    "autocorrelation": ["autocorrelation", "autocorr", "return persistence", "momentum persist"],
    "bb": ["bollinger", "bb width", "bb position", "compression", "squeeze", "bands"],
    "streak": ["streak", "consecutive", "candle streak", "how many candles"],
    "tendency": ["tendency", "time", "when to trade", "best time", "hour", "session", "seasonal", "quarterly", "rolling momentum", "window", "quality"],
    "setup": ["setup", "pattern", "scanner", "compression breakout", "pullback", "mean reversion", "streak exhaustion", "order block", "detector", "confluence"],
    "risk": ["risk", "stop", "position size", "lot size", "atr stop", "stop loss", "how much", "r:r", "reward", "target"],
    "performance": ["performance", "win rate", "profit factor", "expectancy", "equity", "trade log", "how am i doing", "my edge", "my results"],
    "alert": ["alert", "notification", "regime shift", "overtrading", "warning"],
    "direction": ["direction", "should i buy", "should i sell", "long or short", "bullish or bearish", "which way", "what direction", "go long", "go short"],
    "action": ["what should i do", "should i trade", "can i trade", "is it safe", "enter", "sit out", "wait"],
    "explain": ["what is", "what does", "explain", "how does", "tell me about", "what are"],
}


def _match_topic(question):
    """Match a user question to a topic using keyword matching."""
    q = question.lower().strip()
    scores = {}
    for topic, keywords in _QA_TOPICS.items():
        score = 0
        for kw in keywords:
            if kw in q:
                score += len(kw)  # longer matches score higher
        if score > 0:
            scores[topic] = score
    if not scores:
        return "general"
    return max(scores, key=scores.get)


def _gather_live_state(timeframe):
    """Gather current dashboard state for contextual answers."""
    state = {
        "regime": None, "metrics": {}, "tendency": None,
        "setups": None, "performance": None, "interpretation": None,
    }
    try:
        conn = get_db()
        rows = conn.execute(
            """SELECT timestamp, open, high, low, close FROM candles
               WHERE timeframe=? ORDER BY timestamp DESC LIMIT 200""",
            (timeframe,),
        ).fetchall()

        if len(rows) >= 50:
            rows_asc = list(reversed(rows))
            df = pd.DataFrame(rows_asc, columns=["timestamp", "open", "high", "low", "close"])
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col])
            regime_data = classify_regime(df)
            state["regime"] = regime_data
            state["metrics"] = regime_data.get("metrics", {})

            # Tendency
            try:
                closes = [float(r["close"]) for r in rows_asc]
                tendency_result = calc_tendency_analysis(closes, timeframe)
                state["tendency"] = tendency_result.get("summary")
            except Exception:
                pass

            # Setups
            try:
                highs = [float(r["high"]) for r in rows_asc]
                lows = [float(r["low"]) for r in rows_asc]
                closes_l = [float(r["close"]) for r in rows_asc]
                opens_l = [float(r["open"]) for r in rows_asc]
                state["setups"] = scan_all_setups(opens_l, highs, lows, closes_l, regime_data)
            except Exception:
                pass

            # Interpretation
            try:
                perf_data = None
                trade_rows = conn.execute("SELECT * FROM trade_log ORDER BY entry_time ASC").fetchall()
                trades = [dict(r) for r in trade_rows]
                if trades:
                    perf_data = {
                        "overall": calc_performance_stats(trades),
                        "by_regime": calc_performance_by_regime(trades),
                        "by_time": calc_performance_by_time(trades),
                        "by_setup": calc_performance_by_setup(trades),
                        "trade_count": len(trades),
                    }
                state["performance"] = perf_data
                state["interpretation"] = _interpret_market(
                    regime_data, state["tendency"], state["setups"], state["metrics"], perf_data
                )
            except Exception:
                pass

        conn.close()
    except Exception as e:
        log.error(f"Q&A state gather error: {e}")

    return state


def _build_answer(topic, question, state):
    """Build a contextual answer based on topic and live state."""
    regime = state.get("regime") or {}
    metrics = state.get("metrics") or {}
    tendency = state.get("tendency") or {}
    setups = state.get("setups") or {}
    perf = state.get("performance")
    interp = state.get("interpretation") or {}

    r_name = regime.get("regime", "unknown")
    r_sub = regime.get("sub_regime", "unknown")
    r_conf = regime.get("confidence", 0)
    adx = metrics.get("adx", 0) or 0
    hurst = metrics.get("hurst", 0.5) or 0.5
    atr_ratio = metrics.get("atr_ratio", 1.0) or 1.0
    autocorr = metrics.get("autocorrelation", 0) or 0

    if topic == "regime":
        regime_desc = {
            "trending": "trending — price has sustained directional momentum",
            "ranging": "ranging — price is oscillating sideways without clear direction",
            "expanding": "expanding — volatility is spiking with outsized moves",
            "choppy": "choppy — no structure, random walk, no statistical edge",
        }
        desc = regime_desc.get(r_name, r_name)
        sub_desc = {
            "trending_up": "Bullish structure — price above key moving averages.",
            "trending_down": "Bearish structure — price below key moving averages.",
            "trending_mixed": "Trend strength exists but direction is unclear.",
            "compressing": "Volatility compressing — breakout likely building.",
            "ranging_normal": "Standard sideways range.",
            "breakout_run": "Active breakout in progress.",
            "volatility_spike": "Volatile spike without clear direction.",
        }
        sub_text = sub_desc.get(r_sub, "")
        answer = f"The market is currently **{desc}** with {r_conf:.0f}% confidence. {sub_text}"
        if r_name == "choppy":
            answer += " This is the worst regime to trade in — there is no statistical edge. Sit this one out."
        elif r_name == "trending":
            answer += f" ADX is at {adx:.1f} confirming trend strength. Look for pullback entries in the trend direction."
        return answer

    elif topic == "adx":
        if adx > 25:
            strength = "strong"
            advice = "The trend is real. Look for pullback entries with the trend."
        elif adx > 15:
            strength = "moderate"
            advice = "Weak trend — could go either way. Be cautious with trend-following setups."
        else:
            strength = "absent"
            advice = "No trend exists. Don't take momentum or trend trades right now."
        return f"ADX is at **{adx:.1f}** — trend strength is **{strength}**. {advice} Remember: ADX measures strength, not direction. A falling ADX means the trend is weakening even if price is still moving."

    elif topic == "hurst":
        if hurst > 0.55:
            state_desc = "persistent (trending)"
            advice = "Trends should continue. Follow them, don't fade them."
        elif hurst < 0.45:
            state_desc = "anti-persistent (mean-reverting)"
            advice = "Moves tend to reverse. Fade impulses and look for mean reversion setups."
        else:
            state_desc = "near random walk"
            advice = "There's no statistical edge in predicting direction right now. Reduce size or wait."
        return f"Hurst Exponent is at **{hurst:.3f}** — the market is **{state_desc}**. {advice} This is the most important number most traders ignore. It directly answers: 'will this move continue or reverse?'"

    elif topic == "atr":
        if atr_ratio > 1.5:
            vol_state = "elevated"
            advice = "Widen your stops or reduce position size. Normal stops will get clipped by the noise."
        elif atr_ratio < 0.6:
            vol_state = "compressed"
            advice = "Volatility is squeezing — a breakout is likely building. Tighten stops and watch for the expansion."
        else:
            vol_state = "normal"
            advice = "Standard volatility conditions. Use normal stop distances."
        return f"ATR Ratio is at **{atr_ratio:.2f}** — volatility is **{vol_state}**. {advice}"

    elif topic == "autocorrelation":
        if abs(autocorr) > 0.3:
            dir_label = "bullish" if autocorr > 0 else "bearish"
            return f"Autocorrelation is at **{autocorr:.3f}** — returns are persisting with **{dir_label} momentum**. Each bar tends to follow the previous one's direction. This supports trend-following entries."
        elif abs(autocorr) < 0.1:
            return f"Autocorrelation is at **{autocorr:.3f}** — each bar is essentially independent. There's no momentum signal. Don't expect follow-through on moves."
        else:
            return f"Autocorrelation is at **{autocorr:.3f}** — weak persistence. Some directional tendency but not strong enough to rely on alone."

    elif topic == "bb":
        bb_width = metrics.get("bb_width")
        bb_pos = metrics.get("bb_position")
        parts = []
        if bb_width is not None:
            parts.append(f"BB Width is at **{bb_width:.4f}**.")
            if atr_ratio < 0.6:
                parts.append("Combined with low ATR ratio, this confirms compression — breakout conditions are building.")
        if bb_pos is not None:
            if bb_pos > 0.8:
                parts.append(f"Price is near the **upper band** (%B = {bb_pos:.2f}). In a ranging market, this is overbought. In a trending market, this is normal.")
            elif bb_pos < 0.2:
                parts.append(f"Price is near the **lower band** (%B = {bb_pos:.2f}). In a ranging market, this is oversold. In a trending market, the downtrend is strong.")
            else:
                parts.append(f"Price is **mid-band** (%B = {bb_pos:.2f}). No extreme positioning.")
        return " ".join(parts) if parts else "Bollinger Band data is not available yet. Waiting for enough candles to calculate."

    elif topic == "streak":
        streak = regime.get("streak", {})
        if isinstance(streak, dict):
            current = streak.get("current", 0)
            direction = streak.get("direction", "—")
            avg = streak.get("avg", 0)
            std = streak.get("std", 0)
            threshold = avg + 1.5 * std if std else avg + 3
            if current > threshold:
                return f"Current streak: **{current} {direction} candles** — this is **statistically exhausted** (threshold is {threshold:.1f}). The move is overextended. Watch for reversal or at minimum don't chase it."
            else:
                return f"Current streak: **{current} {direction} candles**. Average streak is {avg:.1f} ± {std:.1f}. Not exhausted yet — {'has room to continue' if current < avg else 'approaching average length'}."
        return "Streak data is loading. The streak tracker counts consecutive same-direction candles and flags when they're statistically overextended."

    elif topic == "tendency":
        bias = tendency.get("bias", "neutral")
        strength = tendency.get("strength", 0)
        quality = tendency.get("quality", "low")
        parts = [f"Current tendency: **{bias.upper()}** with {strength:.0f}% strength and **{quality.upper()}** quality."]
        if quality == "high":
            parts.append("This is a high-performance time window — the market historically produces clean, directional moves now.")
        elif quality == "low":
            parts.append("Current time window is historically noisy. Reduce size or wait for a better window.")
        if bias != "neutral" and strength > 50:
            parts.append(f"The statistical bias favours **{bias}** trades right now.")
        return " ".join(parts)

    elif topic == "setup":
        setup_list = setups.get("setups", []) if isinstance(setups, dict) else []
        if not setup_list:
            return "No active setups detected right now. The scanner checks for 5 patterns: Compression Breakout, Pullback to Trend, Mean Reversion, Streak Exhaustion, and Order Block Touch. When a pattern forms, it will appear with a confidence score and regime compatibility tag."

        parts = [f"**{len(setup_list)} setup(s) detected:**"]
        name_map = {
            "compression_breakout": "Compression Breakout",
            "pullback_to_trend": "Pullback to Trend",
            "mean_reversion": "Mean Reversion",
            "streak_exhaustion": "Streak Exhaustion",
            "order_block_touch": "Order Block Touch",
        }
        for s in sorted(setup_list, key=lambda x: x.get("composite_score", 0), reverse=True):
            sname = name_map.get(s.get("type", ""), s.get("type", ""))
            sdir = s.get("direction", "—")
            scomp = s.get("composite_score", 0)
            stag = s.get("regime_tag", "—")
            quality = "A+" if scomp >= 60 else "decent" if scomp >= 35 else "weak"
            parts.append(f"• **{sname}** — {sdir}, composite {scomp:.0f} ({quality}), regime: {stag}")
            if stag == "CAUTION":
                parts.append(f"  ⚠ CAUTION: Regime works against {sname}. Consider skipping.")
        return "\n".join(parts)

    elif topic == "risk":
        return f"Risk management is based on ATR (current ATR ratio: **{atr_ratio:.2f}**). Use Tight stops (1× ATR) for high-conviction A+ setups, Normal (1.5× ATR) for standard trades, Wide (2× ATR) for uncertain conditions. The position sizer calculates: (Balance × Risk%) ÷ Stop Distance = Lots. The dashboard also auto-adjusts for volatility — in high-vol conditions, it reduces your size to protect you. Check Panel D for exact numbers with your current balance."

    elif topic == "performance":
        if not perf or perf.get("trade_count", 0) == 0:
            return "No trades logged yet. Once you start logging trades in Panel E, I can tell you your win rate, profit factor, expectancy, and which regimes/sessions/setups make you money. This is where you discover YOUR specific edge."
        overall = perf.get("overall", {})
        wr = overall.get("win_rate", 0)
        pf = overall.get("profit_factor", 0)
        exp = overall.get("expectancy_r", 0)
        tc = perf.get("trade_count", 0)
        parts = [f"After **{tc} trades**:"]
        parts.append(f"• Win Rate: **{wr:.1f}%**")
        parts.append(f"• Profit Factor: **{pf:.2f}** {'(profitable)' if pf > 1 else '(losing money)'}")
        parts.append(f"• Expectancy: **{exp:.2f}R** {'(positive edge!)' if exp > 0 else '(negative — review your approach)'}")

        by_regime = perf.get("by_regime", {})
        if by_regime:
            best_regime = max(by_regime.items(), key=lambda x: x[1].get("expectancy_r", -999))
            worst_regime = min(by_regime.items(), key=lambda x: x[1].get("expectancy_r", 999))
            if best_regime[1].get("count", 0) >= 3:
                parts.append(f"• Best regime: **{best_regime[0].upper()}** ({best_regime[1].get('expectancy_r', 0):.2f}R)")
            if worst_regime[1].get("count", 0) >= 3 and worst_regime[0] != best_regime[0]:
                parts.append(f"• Worst regime: **{worst_regime[0].upper()}** ({worst_regime[1].get('expectancy_r', 0):.2f}R)")
        return "\n".join(parts)

    elif topic == "alert":
        return "The alert system scans every 30 seconds for 6 conditions:\n• **Regime Shift** (critical on 1H/4H) — market state changed, re-evaluate everything\n• **Compression** — breakout building, get ready\n• **Time Window** — high-performance hour approaching\n• **Overtrading** — you've traded too much, STOP\n• **Streak Exhaustion** — move is overextended\n• **Setup Confluence** — multiple patterns aligned, A+ opportunity\n\nCritical alerts demand immediate action. When the overtrading alert fires, walk away."

    elif topic == "direction" or topic == "action":
        if not interp:
            return "I need a moment to read the full dashboard state. Try asking again in a few seconds."
        action = interp.get("action", "WAIT")
        conviction = interp.get("conviction", "NONE")
        narrative = interp.get("narrative", "")
        reasons = interp.get("reasoning", [])
        warns = interp.get("warnings", [])

        parts = [f"**{action}** — {conviction} conviction."]
        parts.append(narrative)
        if reasons:
            parts.append("\n**Why:**")
            for r in reasons[:5]:
                parts.append(f"• {r}")
        if warns:
            parts.append("\n**Watch out:**")
            for w in warns[:3]:
                parts.append(f"• ⚠ {w}")
        return "\n".join(parts)

    elif topic == "explain":
        # Try to find the specific thing they want explained
        q = question.lower()
        for key, entry in EXPLAIN_DICT.items():
            title_lower = entry["title"].lower()
            if title_lower in q or key.replace("_", " ") in q:
                return f"**{entry['title']}**\n\n{entry['explanation']}\n\n**How to use:** {entry['how_to_use']}"
        return "I can explain any element on the dashboard. Try asking about specific things like: 'what is Hurst?', 'explain ADX', 'what does composite score mean?', 'tell me about the regime', etc."

    else:
        # General / unmatched
        parts = ["Here's a quick snapshot of the market right now:\n"]
        parts.append(f"• **Regime:** {r_name.upper()} ({r_sub}) — {r_conf:.0f}% confidence")
        parts.append(f"• **Indicators:** ADX {adx:.1f}, Hurst {hurst:.3f}, ATR Ratio {atr_ratio:.2f}")

        if tendency:
            parts.append(f"• **Tendency:** {tendency.get('bias', 'neutral').upper()} — strength {tendency.get('strength', 0):.0f}%, quality {tendency.get('quality', 'low').upper()}")

        setup_list = setups.get("setups", []) if isinstance(setups, dict) else []
        parts.append(f"• **Setups:** {len(setup_list)} active")

        if interp:
            parts.append(f"\n**Verdict:** {interp.get('action', 'WAIT')} — {interp.get('conviction', 'NONE')} conviction")

        parts.append("\nYou can ask me about: regime, indicators (ADX, Hurst, ATR, autocorrelation), tendency, setups, risk, performance, alerts, or 'should I trade right now?'")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Adaptive Agent Engine (Panel H v2 — Claude-powered)
# ---------------------------------------------------------------------------
# Replaces the old keyword-matching Q&A with a Claude API-powered agent that
# has full dashboard context, conversation memory, drift detection, and
# learns from trade outcomes over time.
# ---------------------------------------------------------------------------

CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY", "")
AGENT_ENABLED = bool(CLAUDE_API_KEY)
AGENT_MODEL = "claude-sonnet-4-20250514"
AGENT_MAX_TOKENS = 600
_AGENT_CONVERSATION_LIMIT = 20  # messages to include in context


def _agent_system_prompt():
    """Build the system prompt that defines the agent's personality and role."""
    return """You are the V75 Trading Agent — an adaptive market analyst embedded inside a Volatility 75 Index dashboard. You are NOT a generic AI assistant. You are a specialist who lives inside this dashboard and knows it intimately.

PERSONALITY:
- Talk like a sharp, experienced trading partner — direct, no fluff
- Use "we" language — you and the trader are a team
- Be honest about uncertainty. If the data is mixed, say so
- When you spot danger (choppy regime, overtrading, exhaustion), be firm and protective
- Reference specific numbers from the live data, not generic advice
- Keep responses concise (2-4 sentences for simple questions, short paragraphs for analysis)
- Use the trader's ICT terminology naturally: order blocks, displacement, liquidity sweeps, quarterly shifts

WHAT YOU KNOW:
- V75 is algorithmically generated by Deriv — not driven by fundamentals
- The question is never "why is it moving?" but "HOW is it behaving?"
- You have access to: regime classification, all indicators, tendency data, active setups, alerts, performance stats, and your own observations/memory
- You understand the 4 regimes (trending, ranging, expanding, choppy) and the 5 setup detectors

WHAT YOU DO:
- Answer questions using LIVE dashboard data (provided in context)
- Notice patterns: "This is the 3rd regime shift today — unusual choppiness"
- Flag drift: "Hurst has been below 0.50 for days — algo may have shifted to mean-reverting"
- Learn from trades: "Your pullback trades win 70% but mean reversion only 38%"
- Proactively warn: if you see danger in the data, mention it even if not asked
- When suggesting trades, always reference regime compatibility and tendency alignment

NEVER DO:
- Give generic trading advice unrelated to the live V75 data
- Claim to predict the future
- Suggest specific entry prices (you're an analyst, not an executor)
- Be overly verbose — this trader checks you on their phone"""


def _get_recent_conversations(limit=None):
    """Fetch recent conversation history for context."""
    limit = limit or _AGENT_CONVERSATION_LIMIT
    try:
        conn = get_db()
        rows = conn.execute(
            "SELECT role, content FROM agent_conversations ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        ).fetchall()
        conn.close()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
    except Exception:
        return []


def _store_conversation(role, content, context_summary=""):
    """Save a conversation turn to memory."""
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO agent_conversations (timestamp, role, content, context_summary) VALUES (?, ?, ?, ?)",
            (int(time.time()), role, content[:2000], context_summary[:500])
        )
        # Keep only last 200 messages
        conn.execute("""
            DELETE FROM agent_conversations WHERE id NOT IN (
                SELECT id FROM agent_conversations ORDER BY timestamp DESC LIMIT 200
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning(f"Failed to store conversation: {e}")


def _get_agent_observations(limit=10):
    """Fetch recent relevant observations."""
    try:
        conn = get_db()
        now = int(time.time())
        rows = conn.execute(
            """SELECT category, observation, data FROM agent_observations
               WHERE expires_at = 0 OR expires_at > ?
               ORDER BY relevance_score DESC, timestamp DESC LIMIT ?""",
            (now, limit)
        ).fetchall()
        conn.close()
        return [{"category": r["category"], "observation": r["observation"]} for r in rows]
    except Exception:
        return []


def _store_observation(category, observation, data=None, relevance=0.5, ttl_hours=48):
    """Store an agent observation with optional expiry."""
    try:
        conn = get_db()
        expires = int(time.time() + ttl_hours * 3600) if ttl_hours > 0 else 0
        conn.execute(
            """INSERT INTO agent_observations
               (timestamp, category, observation, data, relevance_score, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (int(time.time()), category, observation,
             json.dumps(data or {}), relevance, expires)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning(f"Failed to store observation: {e}")


def _get_trade_lessons(limit=5):
    """Fetch top trade lessons."""
    try:
        conn = get_db()
        rows = conn.execute(
            """SELECT lesson, confidence, times_confirmed FROM agent_trade_lessons
               ORDER BY confidence DESC, times_confirmed DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        conn.close()
        return [{"lesson": r["lesson"], "confidence": r["confidence"],
                 "confirmed": r["times_confirmed"]} for r in rows]
    except Exception:
        return []


def _get_baselines(timeframe="1h"):
    """Get the most recent baseline for comparison."""
    try:
        conn = get_db()
        row = conn.execute(
            """SELECT * FROM agent_baselines WHERE timeframe=?
               ORDER BY week_start DESC LIMIT 1""",
            (timeframe,)
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
    except Exception:
        pass
    return None


def _build_agent_context(timeframe="1h"):
    """Assemble the full context block for the Claude prompt."""
    state = _gather_live_state(timeframe)
    regime = state.get("regime") or {}
    metrics = state.get("metrics") or {}
    tendency = state.get("tendency") or {}
    setups = state.get("setups") or {}
    perf = state.get("performance")
    interp = state.get("interpretation") or {}

    # Live market data
    r_name = regime.get("regime", "unknown")
    r_sub = regime.get("sub_regime", "unknown")
    r_conf = regime.get("confidence", 0)

    ctx_parts = [f"=== LIVE DASHBOARD STATE (as of {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}) ==="]

    # Regime
    ctx_parts.append(f"\n[REGIME] {r_name.upper()} ({r_sub}) — {r_conf:.0f}% confidence")
    ctx_parts.append(f"  ADX: {metrics.get('adx', 0):.1f} | Hurst: {metrics.get('hurst', 0.5):.3f} | ATR Ratio: {metrics.get('atr_ratio', 1.0):.2f} | Autocorr: {metrics.get('autocorrelation', 0):.3f}")

    streak = regime.get("streak", {})
    if isinstance(streak, dict) and streak.get("current"):
        ctx_parts.append(f"  Streak: {streak.get('current', 0)} {streak.get('direction', '?')} candles (avg: {streak.get('avg', 0):.1f})")

    # Tendency
    if tendency:
        ctx_parts.append(f"\n[TENDENCY] {tendency.get('bias', 'neutral').upper()} — strength {tendency.get('strength', 0):.0f}%, quality {tendency.get('quality', 'low').upper()}")

    # Setups
    setup_list = setups.get("setups", []) if isinstance(setups, dict) else []
    if setup_list:
        ctx_parts.append(f"\n[SETUPS] {len(setup_list)} active:")
        for s in sorted(setup_list, key=lambda x: x.get("composite_score", 0), reverse=True):
            ctx_parts.append(f"  • {s.get('type', '?')}: {s.get('direction', '?')}, composite {s.get('composite_score', 0):.0f}, regime: {s.get('regime_tag', '?')}, stage: {s.get('stage', '?')}")
    else:
        ctx_parts.append("\n[SETUPS] None active")

    # Interpretation
    if interp:
        ctx_parts.append(f"\n[AI INTERPRETER] {interp.get('action', 'WAIT')} — {interp.get('conviction', 'NONE')} conviction")
        if interp.get("narrative"):
            ctx_parts.append(f"  {interp['narrative'][:300]}")

    # Performance
    if perf and perf.get("trade_count", 0) > 0:
        overall = perf.get("overall", {})
        ctx_parts.append(f"\n[PERFORMANCE] {perf['trade_count']} trades logged")
        ctx_parts.append(f"  Win rate: {overall.get('win_rate', 0):.1f}% | PF: {overall.get('profit_factor', 0):.2f} | Expectancy: {overall.get('expectancy_r', 0):.2f}R")

        by_regime = perf.get("by_regime", {})
        if by_regime:
            best = max(by_regime.items(), key=lambda x: x[1].get("expectancy_r", -99))
            worst = min(by_regime.items(), key=lambda x: x[1].get("expectancy_r", 99))
            ctx_parts.append(f"  Best regime: {best[0]} ({best[1].get('expectancy_r', 0):.2f}R) | Worst: {worst[0]} ({worst[1].get('expectancy_r', 0):.2f}R)")

    # Recent alerts
    try:
        conn = get_db()
        recent_alerts = conn.execute(
            "SELECT alert_type, severity, title, timeframe FROM alerts WHERE dismissed=0 ORDER BY timestamp DESC LIMIT 5"
        ).fetchall()
        conn.close()
        if recent_alerts:
            ctx_parts.append(f"\n[ACTIVE ALERTS] {len(recent_alerts)} undismissed:")
            for a in recent_alerts:
                ctx_parts.append(f"  • [{a['severity']}] {a['title']} ({a['timeframe'] or 'global'})")
    except Exception:
        pass

    # Agent observations
    observations = _get_agent_observations(8)
    if observations:
        ctx_parts.append("\n[YOUR OBSERVATIONS]")
        for obs in observations:
            ctx_parts.append(f"  • [{obs['category']}] {obs['observation']}")

    # Trade lessons
    lessons = _get_trade_lessons(5)
    if lessons:
        ctx_parts.append("\n[TRADE LESSONS LEARNED]")
        for l in lessons:
            ctx_parts.append(f"  • {l['lesson']} (confidence: {l['confidence']:.0f}%, confirmed {l['confirmed']}x)")

    # Drift detection
    baseline = _get_baselines(timeframe)
    if baseline:
        drift_notes = []
        if baseline.get("avg_hurst") and metrics.get("hurst"):
            hurst_diff = metrics["hurst"] - baseline["avg_hurst"]
            if abs(hurst_diff) > 0.05:
                drift_notes.append(f"Hurst shifted {'up' if hurst_diff > 0 else 'down'} by {abs(hurst_diff):.3f} vs weekly baseline ({baseline['avg_hurst']:.3f})")
        if baseline.get("avg_adx") and metrics.get("adx"):
            adx_diff = metrics["adx"] - baseline["avg_adx"]
            if abs(adx_diff) > 5:
                drift_notes.append(f"ADX {'higher' if adx_diff > 0 else 'lower'} by {abs(adx_diff):.1f} vs weekly baseline ({baseline['avg_adx']:.1f})")
        if drift_notes:
            ctx_parts.append("\n[DRIFT DETECTED]")
            for d in drift_notes:
                ctx_parts.append(f"  ⚠ {d}")

    # Meta-Analysis (the collective intelligence layer)
    global _latest_meta_analysis
    if _latest_meta_analysis:
        meta = _latest_meta_analysis
        ctx_parts.append(f"\n[META-ANALYSIS] System Alignment: {meta.get('alignment_score', '?')}/100 ({meta.get('alignment_label', '?')})")
        conflicts = meta.get("conflicts", [])
        if conflicts:
            ctx_parts.append(f"  {len(conflicts)} signal conflict(s):")
            for c in conflicts[:5]:
                ctx_parts.append(f"  ⚠ [{c['severity'].upper()}] {c['description']}")
                ctx_parts.append(f"    → {c['resolution']}")
        fatigue = meta.get("regime_fatigue", {})
        if fatigue.get("is_fatigued"):
            ctx_parts.append(f"  ⚠ REGIME FATIGUE: {fatigue['duration_readings']} readings (avg: {fatigue['avg_duration']:.0f})")
            if fatigue.get("likely_next"):
                ctx_parts.append(f"    Likely next regime: {fatigue['likely_next'].upper()} ({fatigue['transition_prob']:.0f}%)")
        for mw in meta.get("meta_warnings", []):
            ctx_parts.append(f"  ⚠ {mw}")

    return "\n".join(ctx_parts)


def _call_claude(messages, system_prompt):
    """Call Claude API via raw HTTP (no SDK dependency)."""
    try:
        payload = json.dumps({
            "model": AGENT_MODEL,
            "max_tokens": AGENT_MAX_TOKENS,
            "system": system_prompt,
            "messages": messages,
        }).encode()

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "x-api-key": CLAUDE_API_KEY,
                "anthropic-version": "2023-06-01",
            }
        )
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read().decode())
        return data.get("content", [{}])[0].get("text", "I couldn't formulate a response.")
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        log.error(f"Claude API error {e.code}: {body[:300]}")
        return None
    except Exception as e:
        log.error(f"Claude API call failed: {e}")
        return None


def _agent_fallback(question, timeframe):
    """Fall back to old rule-based system if Claude API is unavailable."""
    topic = _match_topic(question)
    state = _gather_live_state(timeframe)
    return _build_answer(topic, question, state)


@app.route("/api/ask", methods=["POST"])
def api_ask():
    """
    Adaptive Agent endpoint. Powered by Claude API with full dashboard
    context, conversation memory, and drift awareness.
    Falls back to rule-based answers if API key not configured.
    """
    data = request.get_json()
    if not data or not data.get("question"):
        return jsonify({"error": "No question provided"}), 400

    question = data["question"].strip()
    timeframe = data.get("timeframe", "1h")
    if timeframe not in TIMEFRAMES:
        timeframe = "1h"

    # If Claude API not configured, use fallback
    if not AGENT_ENABLED:
        answer = _agent_fallback(question, timeframe)
        return jsonify({"question": question, "answer": answer, "mode": "rule-based"})

    # Build context
    context = _build_agent_context(timeframe)
    system = _agent_system_prompt()

    # Get conversation history
    history = _get_recent_conversations()

    # Build messages: inject context into first user message
    messages = []
    for msg in history[-10:]:  # Last 10 turns
        messages.append({"role": msg["role"], "content": msg["content"]})

    # Current question with context
    user_msg = f"[DASHBOARD CONTEXT]\n{context}\n\n[MY QUESTION]\n{question}"
    messages.append({"role": "user", "content": user_msg})

    # Call Claude
    answer = _call_claude(messages, system)

    if answer is None:
        # API failed — fall back
        answer = _agent_fallback(question, timeframe)
        mode = "fallback"
    else:
        mode = "agent"

    # Store conversation
    _store_conversation("user", question, context_summary=f"Asked about: {question[:100]}")
    _store_conversation("assistant", answer, context_summary="")

    return jsonify({
        "question": question,
        "answer": answer,
        "mode": mode,
        "timeframe": timeframe,
    })


# ---------------------------------------------------------------------------
# Agent Background Loop — Drift Detection & Observation Engine
# ---------------------------------------------------------------------------

def _compute_weekly_baseline(timeframe="1h"):
    """Compute and store a statistical baseline for the current week."""
    try:
        conn = get_db()
        # Get regime history for the past 7 days
        week_ago = int(time.time()) - 7 * 86400
        rows = conn.execute(
            """SELECT regime, adx, hurst, atr_ratio, autocorrelation
               FROM regime_history WHERE timeframe=? AND timestamp > ?""",
            (timeframe, week_ago)
        ).fetchall()

        if len(rows) < 10:
            conn.close()
            return

        adx_vals = [r["adx"] for r in rows if r["adx"]]
        hurst_vals = [r["hurst"] for r in rows if r["hurst"]]
        atr_vals = [r["atr_ratio"] for r in rows if r["atr_ratio"]]
        autocorr_vals = [r["autocorrelation"] for r in rows if r["autocorrelation"]]

        # Regime distribution
        regime_counts = {}
        for r in rows:
            regime_counts[r["regime"]] = regime_counts.get(r["regime"], 0) + 1

        week_start = int(time.time()) - (int(time.time()) % (7 * 86400))

        conn.execute(
            """INSERT OR REPLACE INTO agent_baselines
               (week_start, timeframe, avg_adx, avg_hurst, avg_atr_ratio, avg_autocorr,
                regime_distribution, sample_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (week_start, timeframe,
             np.mean(adx_vals) if adx_vals else None,
             np.mean(hurst_vals) if hurst_vals else None,
             np.mean(atr_vals) if atr_vals else None,
             np.mean(autocorr_vals) if autocorr_vals else None,
             json.dumps(regime_counts),
             len(rows))
        )
        conn.commit()
        conn.close()
        log.info(f"Agent baseline updated for {timeframe}: {len(rows)} samples")
    except Exception as e:
        log.error(f"Baseline computation error: {e}")


def _detect_drift_and_observe():
    """Check for behavioral drift and generate observations."""
    try:
        conn = get_db()
        now = int(time.time())

        # Count regime shifts in last 24h
        day_ago = now - 86400
        shifts = conn.execute(
            """SELECT COUNT(*) FROM alerts
               WHERE alert_type='regime_shift' AND timestamp > ?""",
            (day_ago,)
        ).fetchone()[0]

        if shifts >= 5:
            _store_observation(
                "regime_instability",
                f"{shifts} regime shifts in the last 24h — market is highly unstable. Reducing trade confidence is advisable.",
                {"shift_count": shifts},
                relevance=0.9, ttl_hours=24
            )

        # Check if market has been in one regime for extended period
        recent = conn.execute(
            """SELECT regime FROM regime_history
               WHERE timeframe='1h' ORDER BY timestamp DESC LIMIT 50"""
        ).fetchall()

        if recent and len(recent) >= 20:
            regimes = [r["regime"] for r in recent]
            if len(set(regimes[:20])) == 1:
                _store_observation(
                    "regime_persistence",
                    f"V75 has been in {regimes[0].upper()} for 20+ consecutive readings on 1H. Extended {regimes[0]} phase — strategies for this regime should be prioritized.",
                    {"regime": regimes[0], "count": 20},
                    relevance=0.8, ttl_hours=12
                )

        # Analyze trade performance patterns
        trades = conn.execute(
            "SELECT * FROM trade_log ORDER BY entry_time DESC LIMIT 20"
        ).fetchall()

        if len(trades) >= 5:
            recent_trades = [dict(t) for t in trades[:5]]
            losses = sum(1 for t in recent_trades if t.get("result") == "loss")
            if losses >= 4:
                _store_observation(
                    "losing_streak",
                    f"{losses} of last 5 trades were losses. Consider stepping back and reviewing conditions before next entry.",
                    {"losses": losses},
                    relevance=1.0, ttl_hours=6
                )

        # Clean expired observations
        conn.execute("DELETE FROM agent_observations WHERE expires_at > 0 AND expires_at < ?", (now,))
        conn.commit()
        conn.close()

    except Exception as e:
        log.error(f"Agent observation loop error: {e}")


def agent_memory_loop():
    """Background thread: updates baselines, observations, and scheduled reports."""
    time.sleep(60)  # Wait for data to accumulate
    while True:
        try:
            # Update baselines every 6 hours
            _compute_weekly_baseline("1h")
            _compute_weekly_baseline("4h")

            # Generate observations
            _detect_drift_and_observe()

            # Check if any scheduled reports are due
            _check_and_send_reports()

        except Exception as e:
            log.error(f"Agent memory loop error: {e}")

        time.sleep(21600)  # Every 6 hours


# ---------------------------------------------------------------------------
# Scheduled Report System — 3/7/14/30 Day Automated Monitoring
# ---------------------------------------------------------------------------

REPORT_SCHEDULES = {
    "3day":  3 * 86400,
    "7day":  7 * 86400,
    "14day": 14 * 86400,
    "30day": 30 * 86400,
}


def _last_report_time(report_type):
    """Get timestamp of last report of this type."""
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT timestamp FROM agent_reports WHERE report_type=? ORDER BY timestamp DESC LIMIT 1",
            (report_type,)
        ).fetchone()
        conn.close()
        return row["timestamp"] if row else 0
    except Exception:
        return 0


def _store_report(report_type, content, sent=False):
    """Store a generated report."""
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO agent_reports (timestamp, report_type, content, sent_telegram) VALUES (?, ?, ?, ?)",
            (int(time.time()), report_type, content, 1 if sent else 0)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning(f"Failed to store report: {e}")


def _send_telegram_long(text):
    """Send a long message via Telegram, splitting into chunks if needed."""
    if not TELEGRAM_ENABLED:
        return
    # Telegram max is 4096 chars
    chunks = []
    while len(text) > 4000:
        split_at = text.rfind("\n", 0, 4000)
        if split_at == -1:
            split_at = 4000
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()
    chunks.append(text)

    for chunk in chunks:
        def _do_send(msg=chunk):
            try:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                payload = urllib.parse.urlencode({
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": msg,
                    "parse_mode": "Markdown",
                }).encode()
                req = urllib.request.Request(url, data=payload, method="POST")
                urllib.request.urlopen(req, timeout=15)
            except Exception as e:
                log.warning(f"Telegram report send failed: {e}")
        _do_send()
        time.sleep(1)  # Rate limit between chunks


def _generate_3day_report():
    """3-Day Report: Immediate bugs, signal conflicts, performance issues."""
    now = int(time.time())
    three_days_ago = now - 3 * 86400
    parts = ["\U0001F4CA *V75 DASHBOARD — 3-DAY REPORT*\n"]

    try:
        conn = get_db()

        # Signal conflicts summary
        parts.append("*SIGNAL CONFLICTS*")
        global _latest_meta_analysis
        if _latest_meta_analysis:
            score = _latest_meta_analysis.get("alignment_score", "?")
            label = _latest_meta_analysis.get("alignment_label", "?")
            parts.append(f"Current alignment: {score}/100 ({label})")
            conflicts = _latest_meta_analysis.get("conflicts", [])
            if conflicts:
                parts.append(f"{len(conflicts)} active conflict(s):")
                for c in conflicts[:5]:
                    parts.append(f"  \u26a0 {c['description'][:120]}")
            else:
                parts.append("No active conflicts — panels are aligned.")
        else:
            parts.append("Meta-analysis not yet available.")

        # Alert activity
        parts.append("\n*ALERT ACTIVITY (3 days)*")
        alert_rows = conn.execute(
            "SELECT alert_type, COUNT(*) as cnt FROM alerts WHERE timestamp > ? GROUP BY alert_type ORDER BY cnt DESC",
            (three_days_ago,)
        ).fetchall()
        total_alerts = sum(r["cnt"] for r in alert_rows)
        parts.append(f"Total alerts: {total_alerts}")
        for r in alert_rows:
            parts.append(f"  {r['alert_type']}: {r['cnt']}")

        # Regime shifts
        shifts = conn.execute(
            "SELECT COUNT(*) FROM alerts WHERE alert_type='regime_shift' AND timestamp > ?",
            (three_days_ago,)
        ).fetchone()[0]
        if shifts >= 10:
            parts.append(f"\n\u26a0 *HIGH INSTABILITY*: {shifts} regime shifts in 3 days")
        elif shifts >= 5:
            parts.append(f"\n\u26a1 Moderate instability: {shifts} regime shifts")

        # Observations
        obs = conn.execute(
            "SELECT category, observation FROM agent_observations WHERE timestamp > ? ORDER BY relevance_score DESC LIMIT 5",
            (three_days_ago,)
        ).fetchall()
        if obs:
            parts.append("\n*AGENT OBSERVATIONS*")
            for o in obs:
                parts.append(f"  \u2022 [{o['category']}] {o['observation'][:150]}")

        # Recent trade performance
        trades = conn.execute(
            "SELECT result, COUNT(*) as cnt FROM trade_log WHERE entry_time > ? GROUP BY result",
            (three_days_ago,)
        ).fetchall()
        if trades:
            parts.append("\n*TRADE PERFORMANCE (3 days)*")
            for t in trades:
                parts.append(f"  {t['result']}: {t['cnt']}")

        conn.close()
    except Exception as e:
        parts.append(f"\nError generating report: {e}")

    return "\n".join(parts)


def _generate_7day_report():
    """7-Day Report: Pattern recognition, baseline drift, setup analysis."""
    now = int(time.time())
    week_ago = now - 7 * 86400
    parts = ["\U0001F4C8 *V75 DASHBOARD — 7-DAY REPORT*\n"]

    try:
        conn = get_db()

        # Regime distribution
        parts.append("*REGIME DISTRIBUTION (7 days)*")
        regimes = conn.execute(
            "SELECT regime, COUNT(*) as cnt FROM regime_history WHERE timeframe='1h' AND timestamp > ? GROUP BY regime ORDER BY cnt DESC",
            (week_ago,)
        ).fetchall()
        total = sum(r["cnt"] for r in regimes) or 1
        for r in regimes:
            pct = (r["cnt"] / total) * 100
            bar = "\u2588" * int(pct / 5)
            parts.append(f"  {r['regime']:12s} {bar} {pct:.0f}%")

        # Baseline comparison
        parts.append("\n*INDICATOR BASELINES (1H)*")
        baseline = _get_baselines("1h")
        if baseline:
            parts.append(f"  Avg ADX: {baseline.get('avg_adx', 0):.1f}")
            parts.append(f"  Avg Hurst: {baseline.get('avg_hurst', 0):.3f}")
            parts.append(f"  Avg ATR Ratio: {baseline.get('avg_atr_ratio', 0):.2f}")
            parts.append(f"  Avg Autocorr: {baseline.get('avg_autocorr', 0):.3f}")
            parts.append(f"  Samples: {baseline.get('sample_count', 0)}")

        # Alert patterns
        parts.append("\n*ALERT PATTERNS*")
        alert_types = conn.execute(
            "SELECT alert_type, COUNT(*) as cnt FROM alerts WHERE timestamp > ? GROUP BY alert_type ORDER BY cnt DESC",
            (week_ago,)
        ).fetchall()
        for a in alert_types:
            parts.append(f"  {a['alert_type']}: {a['cnt']}")
        if any(a["cnt"] >= 20 for a in alert_types):
            heavy = [a for a in alert_types if a["cnt"] >= 20]
            parts.append(f"\n\u26a0 *ALERT SPAM*: {', '.join(a['alert_type'] for a in heavy)} firing excessively — review thresholds")

        # Setup success (if trades logged)
        trades = conn.execute(
            "SELECT setup_type, result, COUNT(*) as cnt FROM trade_log WHERE entry_time > ? AND setup_type != '' GROUP BY setup_type, result",
            (week_ago,)
        ).fetchall()
        if trades:
            parts.append("\n*SETUP PERFORMANCE*")
            setup_stats = {}
            for t in trades:
                st = t["setup_type"]
                if st not in setup_stats:
                    setup_stats[st] = {"win": 0, "loss": 0}
                if t["result"] == "win":
                    setup_stats[st]["win"] += t["cnt"]
                else:
                    setup_stats[st]["loss"] += t["cnt"]
            for st, stats in setup_stats.items():
                total = stats["win"] + stats["loss"]
                wr = (stats["win"] / total * 100) if total > 0 else 0
                parts.append(f"  {st}: {wr:.0f}% WR ({total} trades)")

        # Trade lessons
        lessons = _get_trade_lessons(5)
        if lessons:
            parts.append("\n*TRADE LESSONS*")
            for l in lessons:
                parts.append(f"  \u2022 {l['lesson'][:120]}")

        conn.close()
    except Exception as e:
        parts.append(f"\nError: {e}")

    return "\n".join(parts)


def _generate_14day_report():
    """14-Day Report: System intelligence, accuracy review, recommendations."""
    now = int(time.time())
    two_weeks_ago = now - 14 * 86400
    parts = ["\U0001F9E0 *V75 DASHBOARD — 14-DAY INTELLIGENCE REPORT*\n"]

    try:
        conn = get_db()

        # Overall trading stats
        trades = conn.execute(
            "SELECT * FROM trade_log WHERE entry_time > ? ORDER BY entry_time ASC",
            (two_weeks_ago,)
        ).fetchall()
        trade_list = [dict(t) for t in trades]

        if trade_list:
            stats = calc_performance_stats(trade_list)
            parts.append("*TRADING PERFORMANCE (14 days)*")
            parts.append(f"  Trades: {len(trade_list)}")
            parts.append(f"  Win Rate: {stats.get('win_rate', 0):.1f}%")
            parts.append(f"  Profit Factor: {stats.get('profit_factor', 0):.2f}")
            parts.append(f"  Expectancy: {stats.get('expectancy_r', 0):.2f}R")
            parts.append(f"  Max Drawdown: {stats.get('max_drawdown_pct', 0):.1f}%")

            # By regime
            by_regime = calc_performance_by_regime(trade_list)
            if by_regime:
                parts.append("\n*PERFORMANCE BY REGIME*")
                for regime, rdata in by_regime.items():
                    if rdata.get("count", 0) >= 2:
                        parts.append(f"  {regime}: {rdata.get('win_rate', 0):.0f}% WR, {rdata.get('expectancy_r', 0):.2f}R ({rdata['count']} trades)")

        # Regime behavior analysis
        parts.append("\n*V75 BEHAVIOR ANALYSIS*")
        regimes = conn.execute(
            "SELECT regime, COUNT(*) as cnt FROM regime_history WHERE timeframe='1h' AND timestamp > ? GROUP BY regime",
            (two_weeks_ago,)
        ).fetchall()
        total_r = sum(r["cnt"] for r in regimes) or 1

        regime_pcts = {r["regime"]: r["cnt"] / total_r * 100 for r in regimes}
        dominant = max(regime_pcts, key=regime_pcts.get) if regime_pcts else "unknown"
        parts.append(f"  Dominant regime: {dominant.upper()} ({regime_pcts.get(dominant, 0):.0f}%)")

        # Recommendations
        parts.append("\n*RECOMMENDATIONS*")
        if regime_pcts.get("choppy", 0) > 30:
            parts.append("  \u26a0 V75 has been choppy >30% of the time — be selective with entries")
        if trade_list:
            if stats.get("expectancy_r", 0) < 0:
                parts.append("  \u26a0 Negative expectancy — review your entry criteria and regime filters")
            if stats.get("win_rate", 0) < 40:
                parts.append("  \u26a0 Win rate below 40% — consider tighter setup filters (composite > 60)")

        # Agent observations summary
        obs = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM agent_observations WHERE timestamp > ? GROUP BY category ORDER BY cnt DESC",
            (two_weeks_ago,)
        ).fetchall()
        if obs:
            parts.append("\n*AGENT OBSERVATION CATEGORIES*")
            for o in obs:
                parts.append(f"  {o['category']}: {o['cnt']} observations")

        conn.close()
    except Exception as e:
        parts.append(f"\nError: {e}")

    return "\n".join(parts)


def _generate_30day_report():
    """30-Day Report: Strategic evolution, algo behavior changes, architecture."""
    now = int(time.time())
    month_ago = now - 30 * 86400
    parts = ["\U0001F3AF *V75 DASHBOARD — 30-DAY STRATEGIC REPORT*\n"]

    try:
        conn = get_db()

        # Month-over-month comparison
        parts.append("*V75 ALGORITHM BEHAVIOR (30 days)*")

        # Compare first half vs second half baselines
        mid = now - 15 * 86400
        first_half = conn.execute(
            "SELECT AVG(adx) as adx, AVG(hurst) as hurst, AVG(atr_ratio) as atr, AVG(autocorrelation) as ac "
            "FROM regime_history WHERE timeframe='1h' AND timestamp BETWEEN ? AND ?",
            (month_ago, mid)
        ).fetchone()
        second_half = conn.execute(
            "SELECT AVG(adx) as adx, AVG(hurst) as hurst, AVG(atr_ratio) as atr, AVG(autocorrelation) as ac "
            "FROM regime_history WHERE timeframe='1h' AND timestamp BETWEEN ? AND ?",
            (mid, now)
        ).fetchone()

        if first_half and second_half and first_half["adx"] and second_half["adx"]:
            parts.append("  First 15d → Last 15d comparison:")
            adx_d = (second_half["adx"] or 0) - (first_half["adx"] or 0)
            hurst_d = (second_half["hurst"] or 0) - (first_half["hurst"] or 0)
            atr_d = (second_half["atr"] or 0) - (first_half["atr"] or 0)
            parts.append(f"  ADX: {'+' if adx_d > 0 else ''}{adx_d:.1f} {'(trending more)' if adx_d > 3 else '(trending less)' if adx_d < -3 else '(stable)'}")
            parts.append(f"  Hurst: {'+' if hurst_d > 0 else ''}{hurst_d:.3f} {'(more persistent)' if hurst_d > 0.03 else '(more mean-reverting)' if hurst_d < -0.03 else '(stable)'}")
            parts.append(f"  ATR Ratio: {'+' if atr_d > 0 else ''}{atr_d:.2f} {'(more volatile)' if atr_d > 0.15 else '(less volatile)' if atr_d < -0.15 else '(stable)'}")

            if abs(hurst_d) > 0.05 or abs(adx_d) > 5:
                parts.append("\n  \u26a0 *SIGNIFICANT ALGO SHIFT DETECTED*")
                parts.append("  V75 behavior has materially changed in the second half of the month.")

        # Regime transitions
        parts.append("\n*REGIME TRANSITION MAP*")
        all_regimes = conn.execute(
            "SELECT regime FROM regime_history WHERE timeframe='1h' AND timestamp > ? ORDER BY timestamp ASC",
            (month_ago,)
        ).fetchall()
        if len(all_regimes) > 20:
            transitions = {}
            prev = all_regimes[0]["regime"]
            for r in all_regimes[1:]:
                curr = r["regime"]
                if curr != prev:
                    key = f"{prev} \u2192 {curr}"
                    transitions[key] = transitions.get(key, 0) + 1
                    prev = curr
            for t, cnt in sorted(transitions.items(), key=lambda x: x[1], reverse=True)[:8]:
                parts.append(f"  {t}: {cnt}x")

        # Full performance
        trades = conn.execute(
            "SELECT * FROM trade_log WHERE entry_time > ? ORDER BY entry_time ASC",
            (month_ago,)
        ).fetchall()
        if trades:
            stats = calc_performance_stats([dict(t) for t in trades])
            parts.append(f"\n*MONTHLY PERFORMANCE*")
            parts.append(f"  Trades: {len(trades)}")
            parts.append(f"  Win Rate: {stats.get('win_rate', 0):.1f}%")
            parts.append(f"  Profit Factor: {stats.get('profit_factor', 0):.2f}")
            parts.append(f"  Expectancy: {stats.get('expectancy_r', 0):.2f}R")

        # Report count
        report_count = conn.execute(
            "SELECT COUNT(*) FROM agent_reports WHERE timestamp > ?",
            (month_ago,)
        ).fetchone()[0]
        parts.append(f"\n*SYSTEM HEALTH*")
        parts.append(f"  Reports generated this month: {report_count}")
        parts.append(f"  Dashboard uptime: Monitoring active")

        conn.close()
    except Exception as e:
        parts.append(f"\nError: {e}")

    return "\n".join(parts)


def _check_and_send_reports():
    """Check if any scheduled reports are due and send them."""
    now = int(time.time())

    report_generators = {
        "3day": _generate_3day_report,
        "7day": _generate_7day_report,
        "14day": _generate_14day_report,
        "30day": _generate_30day_report,
    }

    for rtype, interval in REPORT_SCHEDULES.items():
        last_sent = _last_report_time(rtype)
        if now - last_sent >= interval:
            try:
                log.info(f"Generating {rtype} report...")
                content = report_generators[rtype]()
                _store_report(rtype, content, sent=TELEGRAM_ENABLED)
                if TELEGRAM_ENABLED:
                    _send_telegram_long(content)
                    log.info(f"{rtype} report sent to Telegram")
                else:
                    log.info(f"{rtype} report generated (Telegram not configured)")
            except Exception as e:
                log.error(f"Report generation error ({rtype}): {e}")


# ---------------------------------------------------------------------------
# Risk Module API Endpoints (Phase 3 — Panel D)
# ---------------------------------------------------------------------------

@app.route("/api/risk/<timeframe>")
def api_risk(timeframe):
    """
    Full risk module output for a timeframe.
    Query params: balance, risk_pct, stop_type
    """
    if timeframe not in TIMEFRAMES:
        return jsonify({"error": f"Invalid timeframe: {timeframe}"}), 400

    balance = request.args.get("balance", RISK_CONFIG["default_account_balance"], type=float)
    risk_pct = request.args.get("risk_pct", RISK_CONFIG["default_risk_pct"], type=float)
    stop_type = request.args.get("stop_type", "normal")

    conn = get_db()
    rows = conn.execute(
        """SELECT timestamp, open, high, low, close FROM candles
           WHERE timeframe=? ORDER BY timestamp DESC LIMIT 200""",
        (timeframe,),
    ).fetchall()

    if len(rows) < 20:
        conn.close()
        return jsonify({"error": "Insufficient data"})

    rows = list(reversed(rows))
    highs = [float(r["high"]) for r in rows]
    lows = [float(r["low"]) for r in rows]
    closes = [float(r["close"]) for r in rows]

    try:
        result = calc_risk_summary(highs, lows, closes, balance, risk_pct, stop_type, conn)
        conn.close()
        return jsonify(sanitize_for_json(result))
    except Exception as e:
        conn.close()
        log.error(f"Risk calc error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------------------
# Performance Tracker API Endpoints (Phase 3 — Panel E)
# ---------------------------------------------------------------------------

@app.route("/api/trades", methods=["GET"])
def api_get_trades():
    """Get trade log with optional filters."""
    limit = request.args.get("limit", 50, type=int)
    regime_filter = request.args.get("regime", None)
    setup_filter = request.args.get("setup", None)

    conn = get_db()
    query = "SELECT * FROM trade_log"
    params = []
    conditions = []

    if regime_filter:
        conditions.append("regime = ?")
        params.append(regime_filter)
    if setup_filter:
        conditions.append("setup_type = ?")
        params.append(setup_filter)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY entry_time DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return jsonify([dict(r) for r in rows])


@app.route("/api/trades", methods=["POST"])
def api_log_trade():
    """Log a new trade."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    required = ["entry_price", "exit_price", "direction"]
    for field in required:
        if field not in data:
            return jsonify({"error": f"Missing field: {field}"}), 400

    try:
        conn = get_db()
        log_trade(conn, data)
        conn.close()
        return jsonify({"status": "ok", "message": "Trade logged"})
    except Exception as e:
        log.error(f"Trade log error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/api/trades/<int:trade_id>", methods=["DELETE"])
def api_delete_trade(trade_id):
    """Delete a trade by ID."""
    conn = get_db()
    conn.execute("DELETE FROM trade_log WHERE id = ?", (trade_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


@app.route("/api/performance")
def api_performance():
    """Full performance analytics."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM trade_log ORDER BY entry_time ASC").fetchall()
    conn.close()

    trades = [dict(r) for r in rows]

    overall = calc_performance_stats(trades)
    by_regime = calc_performance_by_regime(trades)
    by_time = calc_performance_by_time(trades)
    by_setup = calc_performance_by_setup(trades)

    return jsonify(sanitize_for_json({
        "overall": overall,
        "by_regime": by_regime,
        "by_time": by_time,
        "by_setup": by_setup,
        "trade_count": len(trades),
    }))


@app.route("/api/performance/equity")
def api_equity_curve():
    """Get equity curve data for charting."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM trade_log ORDER BY entry_time ASC").fetchall()
    conn.close()

    curve = [{"trade_num": 0, "equity_pct": 0, "time": None}]
    running = 0
    for i, r in enumerate(rows):
        running += r["pnl_pct"]
        curve.append({
            "trade_num": i + 1,
            "equity_pct": round(running, 2),
            "time": r["exit_time"],
            "result": r["result"],
            "r_multiple": r["r_multiple"],
        })

    return jsonify(curve)


# ---------------------------------------------------------------------------
# Background regime calculation
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Alert Engine (Phase 4 — Panel F)
# ---------------------------------------------------------------------------
# Generates alerts based on regime shifts, compression forming, performance
# windows, overtrading patterns, and streak exhaustion.
# ---------------------------------------------------------------------------

# Track previous regime per timeframe to detect shifts
_prev_regimes = {}

# Track trade frequency for overtrading detection
_recent_trade_times = deque(maxlen=50)

ALERT_COOLDOWNS = {
    "regime_shift": 300,      # 5 min between same-type alerts
    "compression": 600,       # 10 min
    "time_window": 1800,      # 30 min
    "overtrading": 900,       # 15 min
    "streak_exhaustion": 600, # 10 min
    "setup_confluence": 600,  # 10 min
}

_last_alert_times = {}


def _can_fire_alert(alert_type, timeframe=""):
    """Cooldown check — prevents alert spam."""
    key = f"{alert_type}:{timeframe}"
    now = time.time()
    last = _last_alert_times.get(key, 0)
    cooldown = ALERT_COOLDOWNS.get(alert_type, 300)
    if now - last < cooldown:
        return False
    return True


def _send_telegram(severity, title, message, timeframe=""):
    """Send alert to Telegram. Runs in a thread to avoid blocking."""
    if not TELEGRAM_ENABLED or severity not in TELEGRAM_SEVERITIES:
        return

    severity_emoji = {"critical": "\u26a0\ufe0f", "warning": "\u26a1"}.get(severity, "\u2139\ufe0f")
    tf_tag = f" [{timeframe}]" if timeframe else ""
    text = f"{severity_emoji} *V75{tf_tag}*\n*{title}*\n{message}"

    def _do_send():
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            payload = urllib.parse.urlencode({
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "Markdown",
                "disable_notification": severity != "critical",
            }).encode()
            req = urllib.request.Request(url, data=payload, method="POST")
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            log.warning(f"Telegram send failed: {e}")

    threading.Thread(target=_do_send, daemon=True).start()


def _store_alert(alert_type, severity, title, message, timeframe="", data=None):
    """Write alert to DB and update cooldown."""
    key = f"{alert_type}:{timeframe}"
    _last_alert_times[key] = time.time()

    try:
        conn = get_db()
        conn.execute(
            """INSERT INTO alerts (timestamp, alert_type, severity, title, message, timeframe, data)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (int(time.time()), alert_type, severity, title, message, timeframe,
             json.dumps(sanitize_for_json(data or {}))),
        )
        conn.commit()
        conn.close()
        log.info(f"Alert: [{severity}] {title}")
        _send_telegram(severity, title, message, timeframe)
    except Exception as e:
        log.error(f"Failed to store alert: {e}")


def check_regime_shift_alerts(timeframe, current_regime_data):
    """Detect when market regime changes — the most important alert."""
    global _prev_regimes

    regime = current_regime_data.get("regime", "unknown")
    sub_regime = current_regime_data.get("sub_regime", "unknown")
    confidence = current_regime_data.get("confidence", 0)

    prev = _prev_regimes.get(timeframe)
    _prev_regimes[timeframe] = regime

    if prev is None or prev == regime:
        return  # No shift or first read

    if not _can_fire_alert("regime_shift", timeframe):
        return

    severity = "critical" if timeframe in ("1h", "4h") else "warning"

    _store_alert(
        alert_type="regime_shift",
        severity=severity,
        title=f"Regime Shift on {timeframe.upper()}",
        message=f"{prev.upper()} → {regime.upper()} ({sub_regime}) | Confidence: {confidence:.0f}%",
        timeframe=timeframe,
        data={"from": prev, "to": regime, "sub_regime": sub_regime, "confidence": confidence},
    )


def check_compression_alerts(timeframe, closes, highs, lows):
    """Detect Bollinger Band compression approaching breakout threshold."""
    if len(closes) < 30:
        return

    closes_arr = np.array(closes, dtype=float)
    bb_width = calc_bollinger_bandwidth(closes_arr)

    if bb_width is None:
        return

    # Calculate historical percentile of current BB width
    widths = []
    for i in range(30, len(closes_arr)):
        w = calc_bollinger_bandwidth(closes_arr[:i])
        if w is not None:
            widths.append(w)

    if len(widths) < 10:
        return

    percentile = float(np.sum(np.array(widths) <= bb_width) / len(widths) * 100)

    # Alert when compression is in bottom 15th percentile
    if percentile <= 15 and _can_fire_alert("compression", timeframe):
        atr = calc_atr(np.array(highs, dtype=float), np.array(lows, dtype=float), closes_arr, 14)
        _store_alert(
            alert_type="compression",
            severity="warning",
            title=f"Compression Forming on {timeframe.upper()}",
            message=f"BB Width at {percentile:.0f}th percentile — breakout conditions building. ATR: {atr:.2f}" if atr else f"BB Width at {percentile:.0f}th percentile — breakout conditions building.",
            timeframe=timeframe,
            data={"bb_width": round(bb_width, 5), "percentile": round(percentile, 1)},
        )


def check_time_window_alerts(tendency_data):
    """Alert when a historically high-performance time window is approaching or active."""
    if not tendency_data:
        return

    now = datetime.now(timezone.utc)
    current_hour = now.hour

    # Check if next hour is a statistically significant one
    hourly = tendency_data.get("hourly", [])
    for h in hourly:
        if h["bucket"] == (current_hour + 1) % 24:
            if h["significance"] in ("high", "very_high") and h["trend_quality"] > 0.5:
                if _can_fire_alert("time_window"):
                    bias = "BULLISH" if h["bullish_pct"] > 55 else "BEARISH" if h["bullish_pct"] < 45 else "ACTIVE"
                    _store_alert(
                        alert_type="time_window",
                        severity="info",
                        title=f"High-Performance Window at {h['label']} UTC",
                        message=f"{bias} tendency ({h['bullish_pct']:.0f}% bull, z={h['z_score']:.2f}, quality={h['trend_quality']:.2f}). Prepare for clean moves.",
                        data={"hour": h["bucket"], "bullish_pct": h["bullish_pct"],
                              "z_score": h["z_score"], "trend_quality": h["trend_quality"]},
                    )
                break  # Only one time window alert per cycle


def check_overtrading_alerts():
    """Detect excessive trade frequency — a discipline guard."""
    try:
        conn = get_db()
        # Count trades in last 2 hours
        two_hours_ago = int(time.time()) - 7200
        count = conn.execute(
            "SELECT COUNT(*) FROM trade_log WHERE entry_time > ?",
            (two_hours_ago,),
        ).fetchone()[0]
        conn.close()

        if count >= 5 and _can_fire_alert("overtrading"):
            _store_alert(
                alert_type="overtrading",
                severity="critical",
                title="Overtrading Warning",
                message=f"{count} trades in the last 2 hours. Step back, review your plan, and wait for A+ setups only.",
                data={"trade_count_2h": count},
            )
    except Exception as e:
        log.warning(f"Overtrading check failed: {e}")


def check_streak_exhaustion_alerts(timeframe, closes):
    """Alert when a long directional streak may be exhausting."""
    if len(closes) < 10:
        return

    closes_arr = np.array(closes, dtype=float)
    streak = calc_streak_info(closes_arr)

    abs_streak = abs(streak["current_streak"])

    # Alert on extended streaks (5+ candles same direction)
    if abs_streak >= 5 and _can_fire_alert("streak_exhaustion", timeframe):
        direction = "BULLISH" if streak["current_streak"] > 0 else "BEARISH"
        _store_alert(
            alert_type="streak_exhaustion",
            severity="warning",
            title=f"{abs_streak}-Candle {direction} Streak on {timeframe.upper()}",
            message=f"Extended streak may be approaching exhaustion. Watch for reversal signals. Max historical: {streak['max_streak']}.",
            timeframe=timeframe,
            data={"streak": streak["current_streak"], "max_streak": streak["max_streak"]},
        )


def check_setup_confluence_alerts(timeframe, setups_data):
    """Alert when multiple high-confidence setups align."""
    if not setups_data:
        return

    setups = setups_data.get("setups", [])
    high_conf = [s for s in setups if s.get("composite_score", 0) >= 55]

    if len(high_conf) >= 2 and _can_fire_alert("setup_confluence", timeframe):
        names = ", ".join(s.get("name", s.get("type", "?")) for s in high_conf[:3])
        best = high_conf[0]
        _store_alert(
            alert_type="setup_confluence",
            severity="critical",
            title=f"Setup Confluence on {timeframe.upper()}",
            message=f"{len(high_conf)} high-confidence setups aligned: {names}. Top composite: {best.get('composite_score', 0):.0f}.",
            timeframe=timeframe,
            data={"setup_count": len(high_conf), "setups": [s.get("type") for s in high_conf]},
        )


def alert_scan_cycle():
    """Run all alert checks for all timeframes. Called by background thread."""
    for tf in TIMEFRAMES:
        try:
            conn = get_db()
            rows = conn.execute(
                """SELECT timestamp, open, high, low, close FROM candles
                   WHERE timeframe=? ORDER BY timestamp DESC LIMIT 200""",
                (tf,),
            ).fetchall()
            conn.close()

            if len(rows) < 50:
                continue

            rows = list(reversed(rows))
            closes = [float(r["close"]) for r in rows]
            highs = [float(r["high"]) for r in rows]
            lows = [float(r["low"]) for r in rows]

            # Regime shift check
            df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
            for col in ["open", "high", "low", "close"]:
                df[col] = pd.to_numeric(df[col])
            regime_data = classify_regime(df)
            check_regime_shift_alerts(tf, regime_data)

            # Compression check
            check_compression_alerts(tf, closes, highs, lows)

            # Streak exhaustion check
            check_streak_exhaustion_alerts(tf, closes)

            # Setup confluence check (only for primary timeframes)
            if tf in ("15m", "1h", "4h"):
                try:
                    setups = scan_all_setups(closes, highs, lows, regime_data)
                    check_setup_confluence_alerts(tf, {"setups": setups})
                except Exception:
                    pass

        except Exception as e:
            log.warning(f"Alert scan error for {tf}: {e}")

    # Time window alerts (uses tendency data from 1h)
    try:
        data = _get_candle_arrays("1h", limit=500)
        if data:
            timestamps, opens, highs, lows, closes = data
            hourly = calc_hourly_tendency(timestamps, opens, highs, lows, closes)
            weekday = calc_weekday_tendency(timestamps, opens, highs, lows, closes)
            session = calc_session_tendency(timestamps, opens, highs, lows, closes)
            rolling = calc_rolling_tendency(timestamps, closes)
            check_time_window_alerts({"hourly": hourly})
    except Exception as e:
        log.warning(f"Time window alert error: {e}")

    # Overtrading check
    check_overtrading_alerts()


def alert_loop():
    """Background thread: runs alert checks every 30 seconds."""
    time.sleep(15)  # Offset from regime loop
    while True:
        try:
            alert_scan_cycle()
        except Exception as e:
            log.error(f"Alert loop error: {e}")
        time.sleep(30)


def regime_update_loop():
    """Periodically recalculate and store regime classifications."""
    while True:
        try:
            conn = get_db()
            for tf in TIMEFRAMES:
                rows = conn.execute(
                    """SELECT timestamp, open, high, low, close FROM candles
                       WHERE timeframe=? ORDER BY timestamp DESC LIMIT ?""",
                    (tf, REGIME_CONFIG["regime_lookback"] + 50),
                ).fetchall()

                if len(rows) < 30:
                    continue

                rows = list(reversed(rows))
                df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close"])
                for col in ["open", "high", "low", "close"]:
                    df[col] = pd.to_numeric(df[col])

                regime = classify_regime(df)
                latest_ts = rows[-1][0]  # timestamp

                try:
                    conn.execute(
                        """INSERT OR REPLACE INTO regime_history
                           (timeframe, timestamp, regime, adx, atr_ratio, hurst, autocorrelation, confidence)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            tf,
                            latest_ts,
                            regime["regime"],
                            regime["metrics"].get("adx"),
                            regime["metrics"].get("atr_ratio"),
                            regime["metrics"].get("hurst"),
                            regime["metrics"].get("autocorrelation"),
                            regime["confidence"],
                        ),
                    )
                except sqlite3.IntegrityError:
                    pass

            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Regime update error: {e}")

        time.sleep(30)  # Update every 30 seconds


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()

    # Start Deriv data service
    data_service.start()

    # Start regime calculation background thread
    regime_thread = threading.Thread(target=regime_update_loop, daemon=True)
    regime_thread.start()

    # Start alert engine background thread
    alert_thread = threading.Thread(target=alert_loop, daemon=True)
    alert_thread.start()

    # Start agent memory loop (drift detection, observations)
    agent_thread = threading.Thread(target=agent_memory_loop, daemon=True)
    agent_thread.start()

    log.info(f"V75 Dashboard starting on port {APP_PORT}")
    app.run(host="0.0.0.0", port=APP_PORT, debug=False)
