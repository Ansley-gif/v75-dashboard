/**
 * V75 Behavioral Dashboard — Frontend Controller
 * Solid Gold Performance
 *
 * Polls the Flask API and updates all panels.
 * Phase 1: Market Regime + Metrics + Streak + Price Chart
 */

(function () {
    "use strict";

    // ── State ──────────────────────────────────────────────────────────
    let activeTimeframe = "1h";   // primary regime timeframe
    let chartTimeframe = "15m";   // chart display timeframe
    let tendencyTimeframe = "1h"; // tendency engine timeframe (follows active)
    let priceChart = null;
    let pollTimer = null;
    let tendencyData = null;      // cached tendency response

    const REGIME_META = {
        trending:   { icon: "📈", color: "#10b981", label: "TRENDING" },
        ranging:    { icon: "↔️",  color: "#f59e0b", label: "RANGING" },
        expanding:  { icon: "💥", color: "#ef4444", label: "EXPANDING" },
        choppy:     { icon: "🌊", color: "#8b5cf6", label: "CHOPPY" },
        insufficient_data: { icon: "⏳", color: "#4a5568", label: "WAITING" },
    };

    const SUB_REGIME_LABELS = {
        trending_up: "Bullish trend",
        trending_down: "Bearish trend",
        trending_mixed: "Mixed trend",
        compressing: "Compression forming",
        ranging_normal: "Sideways range",
        breakout_run: "Breakout in progress",
        volatility_spike: "Volatility spike",
        waiting: "Waiting for data...",
        choppy: "No clear structure",
    };

    // ── Initialization ─────────────────────────────────────────────────
    document.addEventListener("DOMContentLoaded", () => {
        initChart();
        bindTimeframeSelectors();
        bindTendencyTabs();
        bindRiskInputs();
        bindPerfTabs();
        bindTradeForm();
        initAlerts();
        poll();                       // first fetch immediately
        pollTimer = setInterval(poll, 5000);  // then every 5s
        setInterval(fetchAlerts, 10000);      // alerts every 10s
        setInterval(updateFooterTime, 1000);
        updateFooterTime();
        // Performance data loads slower — fetch separately on init
        fetchPerformance();
        fetchAlerts();
        // AI Interpreter + Click-to-Explain + Chat
        initInterpreter();
        initExplainSystem();
        initChat();
    });

    // ── Polling ────────────────────────────────────────────────────────
    async function poll() {
        try {
            const [status, regimes, metrics, candles, tendency, setups, setupsAll] = await Promise.all([
                fetchJSON("/api/status"),
                fetchJSON("/api/regime"),
                fetchJSON(`/api/metrics/${activeTimeframe}`),
                fetchJSON(`/api/candles/${chartTimeframe}?limit=200`),
                fetchJSON(`/api/tendency/${activeTimeframe}`),
                fetchJSON(`/api/setups/${activeTimeframe}`),
                fetchJSON("/api/setups/all"),
            ]);

            updateConnection(status);
            updatePrice(status);
            updateRegimePanel(regimes);
            updateMetrics(metrics);
            updateStreak(metrics);
            updateChart(candles);

            // Track current regime for trade logging
            if (regimes && regimes[activeTimeframe]) {
                currentRegime = regimes[activeTimeframe].regime || "";
                currentSubRegime = regimes[activeTimeframe].sub_regime || "";
            }

            // Risk Module (Panel D) — fetch with current input values
            fetchRisk();

            // Tendency Engine (Panel B)
            if (tendency && !tendency.error) {
                tendencyData = tendency;
                updateTendencySummary(tendency.summary);
                updateActiveView();
            }

            // Setup Scanner (Panel C)
            if (setups && !setups.error) {
                updateSetupPanel(setups);
            }
            if (setupsAll && !setupsAll.error) {
                updateMtfStrip(setupsAll);
            }
        } catch (err) {
            console.error("Poll error:", err);
            updateConnection({ connected: false });
        }
    }

    async function fetchJSON(url) {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return resp.json();
    }

    // ── Connection Status ──────────────────────────────────────────────
    function updateConnection(status) {
        const dot = document.querySelector(".conn-dot");
        const text = document.querySelector(".conn-text");

        if (status.connected) {
            dot.className = "conn-dot live";
            text.textContent = "LIVE";
        } else if (status.has_api_token === false) {
            dot.className = "conn-dot error";
            text.textContent = "NO API TOKEN";
        } else {
            dot.className = "conn-dot";
            text.textContent = "DISCONNECTED";
        }
    }

    function updatePrice(status) {
        const el = document.getElementById("currentPrice");
        if (status.latest_tick) {
            el.textContent = Number(status.latest_tick.price).toFixed(2);
        }
    }

    // ── Regime Panel ───────────────────────────────────────────────────
    function updateRegimePanel(regimes) {
        // Update multi-timeframe strip
        const tfKeys = ["1m", "5m", "15m", "1h", "4h"];
        for (const tf of tfKeys) {
            const data = regimes[tf];
            const dot = document.getElementById(`dot-${tf}`);
            const text = document.getElementById(`regime-${tf}`);

            if (data && data.regime !== "insufficient_data") {
                dot.className = `tf-regime-dot ${data.regime}`;
                text.textContent = data.regime.toUpperCase();
            } else {
                dot.className = "tf-regime-dot";
                text.textContent = "—";
            }
        }

        // Update primary regime display from active timeframe
        const primary = regimes[activeTimeframe];
        if (!primary) return;

        const meta = REGIME_META[primary.regime] || REGIME_META.insufficient_data;
        const badge = document.getElementById("regimeBadge");
        const icon = document.getElementById("regimeIcon");
        const name = document.getElementById("regimeName");
        const sub = document.getElementById("regimeSub");
        const confBar = document.getElementById("confBar");
        const confVal = document.getElementById("confValue");

        // Remove old regime classes and add new
        badge.className = `regime-badge ${primary.regime}`;
        icon.textContent = meta.icon;
        name.textContent = meta.label;
        name.style.color = meta.color;
        sub.textContent = SUB_REGIME_LABELS[primary.sub_regime] || primary.sub_regime;

        confBar.style.width = `${primary.confidence}%`;
        confVal.textContent = `${primary.confidence}%`;

        // Update score bars
        if (primary.scores) {
            const maxScore = Math.max(...Object.values(primary.scores), 1);
            for (const [regime, score] of Object.entries(primary.scores)) {
                const barId = `score${regime.charAt(0).toUpperCase() + regime.slice(1)}`;
                const valId = `val${regime.charAt(0).toUpperCase() + regime.slice(1)}`;
                const bar = document.getElementById(barId);
                const val = document.getElementById(valId);
                if (bar) bar.style.width = `${(score / maxScore) * 100}%`;
                if (val) val.textContent = score;
            }
        }
    }

    // ── Metrics Panel ──────────────────────────────────────────────────
    function updateMetrics(data) {
        if (data.error) return;

        const setMetric = (id, value, decimals = 2) => {
            const el = document.getElementById(id);
            if (!el) return;
            if (value === null || value === undefined) {
                el.textContent = "—";
                return;
            }
            el.textContent = Number(value).toFixed(decimals);
        };

        // From regime metrics (via the metrics endpoint)
        if (data.volatility) {
            setMetric("metricAtrRatio", null);  // comes from regime endpoint
            setMetric("metricBBWidth", data.volatility.bb_width, 3);
            setMetric("metricBBPos", data.volatility.bb_position, 3);
        }
        if (data.behavior) {
            setMetric("metricHurst", data.behavior.hurst, 3);
            setMetric("metricAutocorr", data.behavior.autocorrelation, 4);
        }

        // Fetch regime data for ADX and ATR ratio
        fetchJSON(`/api/regime`).then(regimes => {
            const r = regimes[activeTimeframe];
            if (r && r.metrics) {
                setMetric("metricAdx", r.metrics.adx, 1);
                setMetric("metricAtrRatio", r.metrics.atr_ratio, 3);
            }
        }).catch(() => {});
    }

    // ── Streak Panel ───────────────────────────────────────────────────
    function updateStreak(data) {
        if (data.error || !data.behavior || !data.behavior.streak) return;

        const s = data.behavior.streak;
        const count = document.getElementById("streakCount");
        const dir = document.getElementById("streakDir");

        count.textContent = s.current_streak;
        count.className = `streak-count ${s.direction === "bullish" ? "bullish" : s.direction === "bearish" ? "bearish" : ""}`;
        dir.textContent = s.direction.toUpperCase();

        document.getElementById("streakAvg").textContent = s.avg_streak ? s.avg_streak.toFixed(1) : "—";
        document.getElementById("streakMax").textContent = s.max_streak || "—";
        document.getElementById("streakStd").textContent = s.streak_std ? s.streak_std.toFixed(2) : "—";
    }

    // ── Price Chart ────────────────────────────────────────────────────
    function initChart() {
        const ctx = document.getElementById("priceChart").getContext("2d");

        priceChart = new Chart(ctx, {
            type: "line",
            data: {
                labels: [],
                datasets: [{
                    label: "V75 Close",
                    data: [],
                    borderColor: "#d4a843",
                    borderWidth: 1.5,
                    backgroundColor: "rgba(212, 168, 67, 0.05)",
                    fill: true,
                    pointRadius: 0,
                    pointHitRadius: 8,
                    tension: 0.1,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: { duration: 300 },
                interaction: {
                    mode: "index",
                    intersect: false,
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        backgroundColor: "#151d2e",
                        borderColor: "#2d3f56",
                        borderWidth: 1,
                        titleColor: "#8492a6",
                        bodyColor: "#e2e8f0",
                        titleFont: { family: "'SF Mono', monospace", size: 11 },
                        bodyFont: { family: "'SF Mono', monospace", size: 12 },
                        padding: 10,
                        displayColors: false,
                        callbacks: {
                            label: (ctx) => `Price: ${ctx.parsed.y.toFixed(2)}`,
                        },
                    },
                },
                scales: {
                    x: {
                        grid: { color: "rgba(30, 42, 58, 0.5)", drawBorder: false },
                        ticks: {
                            color: "#4a5568",
                            font: { family: "'SF Mono', monospace", size: 10 },
                            maxTicksLimit: 10,
                            maxRotation: 0,
                        },
                    },
                    y: {
                        position: "right",
                        grid: { color: "rgba(30, 42, 58, 0.5)", drawBorder: false },
                        ticks: {
                            color: "#4a5568",
                            font: { family: "'SF Mono', monospace", size: 10 },
                        },
                    },
                },
            },
        });
    }

    function updateChart(candles) {
        if (!candles || !candles.length || !priceChart) return;

        const labels = candles.map(c => {
            const d = new Date(c.time);
            return `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
        });
        const prices = candles.map(c => c.close);

        priceChart.data.labels = labels;
        priceChart.data.datasets[0].data = prices;
        priceChart.update("none");
    }

    // ── Tendency Engine (Panel B) ──────────────────────────────────────

    function bindTendencyTabs() {
        document.querySelectorAll(".tendency-tab").forEach(tab => {
            tab.addEventListener("click", () => {
                document.querySelectorAll(".tendency-tab").forEach(t => t.classList.remove("active"));
                tab.classList.add("active");
                document.querySelectorAll(".tendency-view").forEach(v => v.classList.remove("active"));
                const target = document.getElementById(`view-${tab.dataset.view}`);
                if (target) target.classList.add("active");
                updateActiveView();
            });
        });
    }

    function updateActiveView() {
        if (!tendencyData) return;
        const activeTab = document.querySelector(".tendency-tab.active");
        if (!activeTab) return;
        const view = activeTab.dataset.view;
        switch (view) {
            case "hourly":    renderHourlyHeatmap(tendencyData.hourly); break;
            case "weekday":   renderTendencyBars("weekdayBars", tendencyData.weekday); break;
            case "session":   renderTendencyBars("sessionBars", tendencyData.session); break;
            case "monthly":   renderMonthlyStrip(tendencyData.monthly); break;
            case "quarterly": renderQuarterly(tendencyData.quarterly); break;
            case "rolling":   renderRolling(tendencyData.rolling); break;
        }
    }

    function updateTendencySummary(summary) {
        if (!summary) return;
        const biasEl = document.getElementById("tendencyBias");
        biasEl.textContent = summary.tendency.toUpperCase();
        biasEl.className = `tendency-bias ${summary.tendency}`;

        const pct = Math.round(summary.tendency_strength * 100);
        document.getElementById("tendencyStrengthBar").style.width = `${pct}%`;
        document.getElementById("tendencyStrengthVal").textContent = `${pct}%`;

        // Context items
        const setCtx = (id, profile, key) => {
            const el = document.getElementById(id);
            if (!el) return;
            if (!profile || profile.sample_size === 0) { el.textContent = "—"; el.className = "ctx-value"; return; }
            const bull = profile.bullish_pct;
            if (bull > 55) { el.textContent = `${bull.toFixed(0)}% Bull`; el.className = "ctx-value bullish"; }
            else if (bull < 45) { el.textContent = `${(100 - bull).toFixed(0)}% Bear`; el.className = "ctx-value bearish"; }
            else { el.textContent = "Neutral"; el.className = "ctx-value"; }
        };
        setCtx("ctxHour", summary.current_hour);
        setCtx("ctxDay", summary.current_day);
        setCtx("ctxSession", summary.current_session);

        const qualEl = document.getElementById("ctxQuality");
        const q = summary.window_quality;
        qualEl.textContent = q >= 0.6 ? "HIGH" : q >= 0.35 ? "MED" : "LOW";
        qualEl.className = `ctx-value ${q >= 0.6 ? "bullish" : q >= 0.35 ? "" : "bearish"}`;
    }

    // Hourly heatmap
    function renderHourlyHeatmap(hourly) {
        const container = document.getElementById("hourlyHeatmap");
        if (!container || !hourly) return;

        container.innerHTML = hourly.map(h => {
            const bullPct = h.bullish_pct;
            const bg = heatmapColor(bullPct);
            const sigMark = h.significance === "very_high" ? "***" :
                            h.significance === "high" ? "**" :
                            h.significance === "moderate" ? "*" : "";
            return `<div class="heatmap-cell" style="background:${bg}" title="Z: ${h.z_score} | Vol: ${h.volatility.toFixed(3)}% | n=${h.sample_size}">
                <span class="cell-hour">${h.label}</span>
                <span class="cell-bias">${bullPct.toFixed(0)}%</span>
                <span class="cell-vol">vol ${h.volatility.toFixed(2)}%</span>
                ${sigMark ? `<span class="cell-sig">${sigMark}</span>` : ""}
            </div>`;
        }).join("");
    }

    function heatmapColor(bullPct) {
        // 0% = full bearish red, 50% = neutral grey, 100% = full bullish green
        const t = bullPct / 100; // 0-1
        if (t >= 0.5) {
            const g = (t - 0.5) * 2; // 0-1 for bullish intensity
            return `rgba(16, 185, 129, ${0.15 + g * 0.55})`;
        } else {
            const r = (0.5 - t) * 2; // 0-1 for bearish intensity
            return `rgba(239, 68, 68, ${0.15 + r * 0.55})`;
        }
    }

    // Bar charts (weekday, session, quarterly)
    function renderTendencyBars(containerId, data) {
        const container = document.getElementById(containerId);
        if (!container || !data) return;

        const maxBull = Math.max(...data.map(d => d.bullish_pct), 60);

        container.innerHTML = data.map(d => {
            const bull = d.bullish_pct;
            const isBullish = bull > 52;
            const isBearish = bull < 48;
            const barClass = isBullish ? "bullish" : isBearish ? "bearish" : "neutral";
            const barHeight = Math.max((bull / maxBull) * 100, 8);
            const retSign = d.avg_return_pct > 0 ? "+" : "";

            return `<div class="tendency-bar-item">
                <div class="bar-visual">
                    <span class="bar-pct">${bull.toFixed(0)}%</span>
                    <div class="bar-fill ${barClass}" style="height:${barHeight}%"></div>
                </div>
                <span class="bar-label">${d.label}</span>
                <span class="bar-detail">${retSign}${d.avg_return_pct.toFixed(3)}%</span>
                <span class="bar-sig ${d.significance}">${d.significance === "low" ? "" : d.significance.replace("_", " ")}</span>
            </div>`;
        }).join("");
    }

    // Monthly seasonal strip
    function renderMonthlyStrip(monthly) {
        const container = document.getElementById("monthlyStrip");
        if (!container || !monthly) return;

        container.innerHTML = monthly.map(m => {
            const bull = m.bullish_pct;
            const bg = heatmapColor(bull);
            const retSign = m.avg_return_pct > 0 ? "+" : "";
            return `<div class="seasonal-month" style="background:${bg}" title="Z: ${m.z_score} | n=${m.sample_size}">
                <span class="month-name" style="color:rgba(255,255,255,0.9)">${m.label}</span>
                <span class="month-bias" style="color:rgba(255,255,255,0.95)">${bull.toFixed(0)}%</span>
                <span class="month-detail">${retSign}${m.avg_return_pct.toFixed(3)}%</span>
                <span class="month-detail">vol ${m.volatility.toFixed(2)}%</span>
            </div>`;
        }).join("");
    }

    // Quarterly view
    function renderQuarterly(data) {
        if (!data) return;

        // Quarter bars
        renderTendencyBars("quarterlyBars", data.quarterly);

        // Phase grid
        const phasesEl = document.getElementById("quarterlyPhases");
        if (phasesEl && data.phases) {
            const quarters = ["Q1", "Q2", "Q3", "Q4"];
            const phaseNames = ["early", "mid", "late"];

            phasesEl.innerHTML = quarters.map((q, qi) => {
                const qPhases = data.phases.filter(p => p.bucket && p.bucket.startsWith(q));
                return `<div class="q-phase-group">
                    <div class="q-phase-title">${q} Phases</div>
                    ${qPhases.map(p => {
                        const valClass = p.bullish_pct > 52 ? "bullish" : p.bullish_pct < 48 ? "bearish" : "";
                        const phaseName = p.bucket.split("_")[1] || "";
                        return `<div class="q-phase-cell">
                            <span class="phase-name">${phaseName}</span>
                            <span class="phase-val ${valClass}">${p.bullish_pct.toFixed(0)}%</span>
                        </div>`;
                    }).join("")}
                </div>`;
            }).join("");
        }

        // Shift analysis
        const shiftEl = document.getElementById("shiftAnalysis");
        if (shiftEl && data.shift_analysis) {
            const sa = data.shift_analysis;
            const preClass = sa.pre_shift_avg_return > 0 ? "bullish" : sa.pre_shift_avg_return < 0 ? "bearish" : "";
            const postClass = sa.post_shift_avg_return > 0 ? "bullish" : sa.post_shift_avg_return < 0 ? "bearish" : "";

            shiftEl.innerHTML = `
                <div class="shift-item">
                    <span class="shift-label">Pre-Quarter Shift</span>
                    <span class="shift-value ${preClass}">${sa.pre_shift_avg_return > 0 ? "+" : ""}${sa.pre_shift_avg_return.toFixed(4)}%</span>
                    <span class="shift-detail">vol ${sa.pre_shift_volatility.toFixed(3)}% | n=${sa.pre_shift_samples}</span>
                </div>
                <div class="shift-item">
                    <span class="shift-label">Post-Quarter Shift</span>
                    <span class="shift-value ${postClass}">${sa.post_shift_avg_return > 0 ? "+" : ""}${sa.post_shift_avg_return.toFixed(4)}%</span>
                    <span class="shift-detail">vol ${sa.post_shift_volatility.toFixed(3)}% | n=${sa.post_shift_samples}</span>
                </div>
            `;
        }
    }

    // Rolling momentum cards
    function renderRolling(rolling) {
        const container = document.getElementById("rollingCards");
        if (!container || !rolling) return;

        const windows = ["20_bar", "40_bar", "60_bar"];
        const labels = { "20_bar": "20-Bar", "40_bar": "40-Bar", "60_bar": "60-Bar" };

        container.innerHTML = windows.map(w => {
            const d = rolling[w];
            if (!d) return "";
            const retSign = d.return_pct > 0 ? "+" : "";
            const retClass = d.return_pct > 0 ? "positive" : d.return_pct < 0 ? "negative" : "";

            return `<div class="rolling-card ${d.direction}">
                <span class="rolling-window">${labels[w]}</span>
                <span class="rolling-direction ${d.direction}">${d.direction}</span>
                <span class="rolling-return ${retClass}">${retSign}${d.return_pct.toFixed(3)}%</span>
                <div class="rolling-meta">
                    <div class="rolling-meta-row">
                        <span class="meta-label">Consistency</span>
                        <span class="meta-val">${d.consistency}% bullish bars</span>
                    </div>
                    <div class="rolling-meta-row">
                        <span class="meta-label">Bars</span>
                        <span class="meta-val">${d.bullish_bars || "—"} / ${d.total_bars || "—"}</span>
                    </div>
                </div>
                <div class="rolling-strength-track">
                    <div class="rolling-strength-fill ${d.direction}" style="width:${Math.round(d.strength * 100)}%"></div>
                </div>
            </div>`;
        }).join("");
    }

    // ── Setup Scanner (Panel C) ────────────────────────────────────────

    function updateSetupPanel(data) {
        const countEl = document.getElementById("setupCount");
        const ctxEl = document.getElementById("setupRegimeCtx");
        const cardsEl = document.getElementById("setupCards");
        const emptyEl = document.getElementById("setupEmpty");

        if (!countEl || !cardsEl) return;

        const setups = data.setups || [];
        const n = setups.length;

        // Status bar
        countEl.innerHTML = n > 0
            ? `<span class="count-num">${n}</span> active setup${n > 1 ? "s" : ""} detected`
            : "No active setups — clean slate";
        ctxEl.textContent = data.regime
            ? `Regime: ${data.regime} / ${data.sub_regime}`
            : "";

        // Cards
        if (n === 0) {
            cardsEl.innerHTML = `<div class="setup-empty">
                <span class="empty-icon">🔍</span>
                <span class="empty-text">No setups on ${activeTimeframe.toUpperCase()} — market is between patterns</span>
            </div>`;
            return;
        }

        cardsEl.innerHTML = setups.map((s, i) => {
            const conf = s.confidence || 0;
            const composite = s.composite_score || 0;
            const isTop = i === 0 && composite >= 50;

            // Gauge circle math (circumference of r=22 circle)
            const circumference = 2 * Math.PI * 22;
            const offset = circumference - (conf / 100) * circumference;
            const gaugeClass = conf >= 65 ? "high" : conf >= 40 ? "mid" : "low";
            const compositeClass = composite >= 60 ? "high" : composite >= 35 ? "mid" : "low";

            // Map setup type to explain key
            const explainKey = s.type || "";

            return `<div class="setup-card explainable${isTop ? " top-pick" : ""}" data-explain="${explainKey}">
                <div class="setup-gauge explainable" data-explain="setup_confidence">
                    <svg viewBox="0 0 52 52">
                        <circle class="gauge-bg" cx="26" cy="26" r="22"/>
                        <circle class="gauge-fill ${gaugeClass}" cx="26" cy="26" r="22"
                            stroke-dasharray="${circumference}"
                            stroke-dashoffset="${offset}"/>
                    </svg>
                    <span class="gauge-value ${gaugeClass}">${conf}</span>
                </div>
                <div class="setup-body">
                    <div class="setup-name">
                        ${s.name || s.type}
                        <span class="setup-direction ${s.direction}">${s.direction}</span>
                    </div>
                    <div class="setup-context">${s.context || ""}</div>
                    <div class="setup-stage">Stage: ${s.stage || "—"}</div>
                </div>
                <div class="setup-right">
                    <span class="regime-tag explainable ${s.regime_tag || ""}" data-explain="regime_tag">${s.regime_tag || "—"}</span>
                    <div style="text-align:right" class="explainable" data-explain="composite_score">
                        <div class="composite-score ${compositeClass}">${composite.toFixed(0)}</div>
                        <div class="composite-label">composite</div>
                    </div>
                </div>
            </div>`;
        }).join("");
    }

    function updateMtfStrip(allData) {
        const container = document.getElementById("mtfItems");
        if (!container) return;

        const timeframes = ["1m", "5m", "15m", "1h", "4h"];

        container.innerHTML = timeframes.map(tf => {
            const d = allData[tf];
            if (!d) return `<div class="mtf-item">
                <span class="mtf-tf">${tf}</span>
                <span class="mtf-count none">—</span>
            </div>`;

            const count = d.count || 0;
            const best = d.setups && d.setups.length > 0 ? d.setups[0] : null;
            const hasSetups = count > 0;
            const isActive = tf === activeTimeframe;

            return `<div class="mtf-item${hasSetups ? " has-setups" : ""}" style="${isActive ? "border:1px solid var(--gold-dim);border-radius:var(--radius-sm)" : ""}">
                <span class="mtf-tf">${tf.toUpperCase()}</span>
                <span class="mtf-count ${hasSetups ? "active" : "none"}">${count}</span>
                ${best ? `<span class="mtf-best">${abbreviateSetup(best.type)} ${best.composite_score.toFixed(0)}</span>` : `<span class="mtf-best">—</span>`}
            </div>`;
        }).join("");
    }

    function abbreviateSetup(type) {
        const map = {
            "compression_breakout": "COMP",
            "pullback_to_trend": "PULL",
            "mean_reversion": "MR",
            "streak_exhaustion": "EXHST",
            "order_block_touch": "OB",
        };
        return map[type] || type.substring(0, 4).toUpperCase();
    }

    // ── Alert System (Panel F) ──────────────────────────────────────

    let alertShowHistory = false;
    let lastAlertCount = 0;
    let notificationsEnabled = false;

    function initAlerts() {
        // Dismiss all button
        const dismissAllBtn = document.getElementById("alertDismissAll");
        if (dismissAllBtn) {
            dismissAllBtn.addEventListener("click", async () => {
                try {
                    await fetch("/api/alerts/dismiss_all", { method: "POST" });
                    fetchAlerts();
                } catch (e) { console.error("Dismiss all failed:", e); }
            });
        }

        // History toggle
        const histBtn = document.getElementById("alertToggleHistory");
        if (histBtn) {
            histBtn.addEventListener("click", () => {
                alertShowHistory = !alertShowHistory;
                histBtn.textContent = alertShowHistory ? "Active" : "History";
                fetchAlerts();
            });
        }

        // Request browser notification permission
        if ("Notification" in window && Notification.permission === "default") {
            Notification.requestPermission().then(p => {
                notificationsEnabled = p === "granted";
            });
        } else if ("Notification" in window) {
            notificationsEnabled = Notification.permission === "granted";
        }
    }

    async function fetchAlerts() {
        try {
            const url = alertShowHistory ? "/api/alerts?all=1&limit=30" : "/api/alerts?limit=20";
            const alerts = await fetchJSON(url);
            renderAlerts(alerts);

            // Badge count
            const countData = await fetchJSON("/api/alerts/count");
            const badge = document.getElementById("alertBadge");
            if (badge) {
                if (countData.count > 0) {
                    badge.textContent = countData.count;
                    badge.style.display = "inline-flex";
                } else {
                    badge.style.display = "none";
                }
            }

            // Browser notification for new alerts
            if (countData.count > lastAlertCount && lastAlertCount > 0 && alerts.length > 0) {
                const newest = alerts[0];
                sendBrowserNotification(newest);
            }
            lastAlertCount = countData.count;

        } catch (e) {
            console.error("Alert fetch error:", e);
        }
    }

    function renderAlerts(alerts) {
        const feed = document.getElementById("alertFeed");
        if (!feed) return;

        if (!alerts || alerts.length === 0) {
            feed.innerHTML = `<div class="alert-empty">
                <span class="empty-text">${alertShowHistory ? "No alert history yet" : "No active alerts — all clear"}</span>
            </div>`;
            return;
        }

        feed.innerHTML = alerts.map(a => {
            const icon = alertIcon(a.alert_type, a.severity);
            const ts = new Date(a.timestamp * 1000);
            const timeStr = ts.toLocaleTimeString("en-ZA", { hour: "2-digit", minute: "2-digit", hour12: false });
            const dismissed = a.dismissed ? " dismissed" : "";

            const explainKey = a.alert_type + "_alert";

            return `<div class="alert-item explainable ${a.severity}${dismissed}" data-id="${a.id}" data-explain="${explainKey}">
                <span class="alert-icon">${icon}</span>
                <div class="alert-body">
                    <div class="alert-title">${a.title}</div>
                    <div class="alert-message">${a.message}</div>
                    <div class="alert-meta">
                        <span class="alert-time">${timeStr}</span>
                        ${a.timeframe ? `<span class="alert-tf-tag">${a.timeframe.toUpperCase()}</span>` : ""}
                        <span class="alert-type-tag">${a.alert_type.replace(/_/g, " ")}</span>
                    </div>
                </div>
                ${!a.dismissed ? `<button class="alert-dismiss" onclick="dismissAlert(${a.id})">Dismiss</button>` : ""}
            </div>`;
        }).join("");
    }

    function alertIcon(type, severity) {
        const icons = {
            regime_shift: "\u26A0\uFE0F",
            compression: "\u2B55",
            time_window: "\u23F0",
            overtrading: "\uD83D\uDED1",
            streak_exhaustion: "\uD83D\uDD25",
            setup_confluence: "\u2B50",
        };
        return icons[type] || "\uD83D\uDD14";
    }

    // Must be global for inline onclick
    window.dismissAlert = async function(id) {
        try {
            await fetch(`/api/alerts/dismiss/${id}`, { method: "POST" });
            const item = document.querySelector(`.alert-item[data-id="${id}"]`);
            if (item) {
                item.classList.add("dismissed");
                setTimeout(() => fetchAlerts(), 400);
            }
        } catch (e) { console.error("Dismiss failed:", e); }
    };

    function sendBrowserNotification(alert) {
        if (!notificationsEnabled) return;
        try {
            const n = new Notification(`V75: ${alert.title}`, {
                body: alert.message,
                icon: "/static/favicon.ico",
                tag: `v75-alert-${alert.id}`,
                requireInteraction: alert.severity === "critical",
            });
            // Auto-close non-critical after 8s
            if (alert.severity !== "critical") {
                setTimeout(() => n.close(), 8000);
            }
        } catch (e) { /* notification blocked or unavailable */ }
    }

    // ── Risk Module (Panel D) ─────────────────────────────────────────

    let riskDebounce = null;

    function bindRiskInputs() {
        const ids = ["riskBalance", "riskPct", "riskStopType"];
        ids.forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.addEventListener("change", () => {
                    clearTimeout(riskDebounce);
                    riskDebounce = setTimeout(fetchRisk, 300);
                });
                el.addEventListener("input", () => {
                    clearTimeout(riskDebounce);
                    riskDebounce = setTimeout(fetchRisk, 500);
                });
            }
        });
    }

    async function fetchRisk() {
        const balance = document.getElementById("riskBalance")?.value || 1000;
        const riskPct = document.getElementById("riskPct")?.value || 1;
        const stopType = document.getElementById("riskStopType")?.value || "normal";

        try {
            const data = await fetchJSON(
                `/api/risk/${activeTimeframe}?balance=${balance}&risk_pct=${riskPct}&stop_type=${stopType}`
            );
            if (data && !data.error) updateRiskPanel(data);
        } catch (e) {
            console.error("Risk fetch error:", e);
        }
    }

    function updateRiskPanel(data) {
        // Volatility adjustment
        const va = data.vol_adjustment || {};
        const condEl = document.getElementById("volCondition");
        if (condEl) {
            condEl.textContent = va.vol_condition || "—";
            condEl.className = "vol-value";
            if (va.vol_condition?.includes("HIGH")) condEl.classList.add("high-vol");
            else if (va.vol_condition?.includes("ELEVATED")) condEl.classList.add("elevated-vol");
            else if (va.vol_condition?.includes("LOW")) condEl.classList.add("low-vol");
            else condEl.classList.add("normal-vol");
        }
        setText("volAtrRatio", va.atr_ratio?.toFixed(3) || "—");
        setText("volScale", `${va.base_risk_pct}% → ${va.adjusted_risk_pct}% (×${va.scale_factor})`);

        // Stop
        const stop = data.stop || {};
        setText("stopDistance", stop.stop_distance?.toFixed(2) || "—");
        setText("stopLong", stop.stop_long?.toFixed(2) || "—");
        setText("stopShort", stop.stop_short?.toFixed(2) || "—");
        setText("stopPct", stop.stop_pct ? `${stop.stop_pct.toFixed(3)}%` : "—");

        // Position
        const pos = data.position || {};
        setText("positionLots", pos.position_lots?.toFixed(4) || "—");
        setText("riskAmount", pos.risk_amount ? `$${pos.risk_amount.toFixed(2)}` : "—");
        setText("effectiveRisk", pos.effective_risk_pct ? `${pos.effective_risk_pct}%` : "—");

        // R:R targets
        const rrEl = document.getElementById("rrTargets");
        if (rrEl && data.rr_targets) {
            rrEl.innerHTML = Object.entries(data.rr_targets).map(([label, t]) => `
                <div class="rr-target-row">
                    <span class="rr-label">${label}</span>
                    <span class="rr-value">+${t.tp_distance.toFixed(2)} pts</span>
                </div>
            `).join("");
        }

        // Stop comparison
        const compEl = document.getElementById("stopCompItems");
        if (compEl && data.all_stops) {
            const currentType = document.getElementById("riskStopType")?.value || "normal";
            compEl.innerHTML = Object.entries(data.all_stops).map(([type, s]) => `
                <div class="stop-comp-item${type === currentType ? " active" : ""}">
                    <span class="stop-comp-type">${type}</span>
                    <span class="stop-comp-dist">${s.stop_distance.toFixed(2)}</span>
                    <span class="stop-comp-lots">${s.position?.position_lots?.toFixed(4) || "—"} lots</span>
                </div>
            `).join("");
        }

        // Frequency governor
        const freq = data.frequency || {};
        const lightEl = document.getElementById("freqLight");
        const textEl = document.getElementById("freqText");
        const detailEl = document.getElementById("freqDetail");

        if (lightEl && textEl) {
            if (freq.allowed) {
                lightEl.className = "freq-light green";
                textEl.textContent = "CLEAR TO TRADE";
            } else {
                lightEl.className = "freq-light red";
                textEl.textContent = "HOLD — " + (freq.reasons?.[0] || "Limit reached");
            }
        }
        if (detailEl) {
            detailEl.innerHTML = `
                <span>Session: ${freq.session_trades}/${freq.session_limit}</span>
                <span>Day: ${freq.day_trades}/${freq.day_limit}</span>
                <span>Loss streak: ${freq.consecutive_losses}</span>
            `;
        }
    }

    function setText(id, val) {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    }

    // ── Performance Tracker (Panel E) ─────────────────────────────────

    let equityChart = null;
    let perfData = null;

    function bindPerfTabs() {
        document.querySelectorAll(".perf-tab").forEach(tab => {
            tab.addEventListener("click", () => {
                document.querySelectorAll(".perf-tab").forEach(t => t.classList.remove("active"));
                tab.classList.add("active");
                document.querySelectorAll(".perf-view").forEach(v => v.classList.remove("active"));
                const target = document.getElementById(`pview-${tab.dataset.pview}`);
                if (target) target.classList.add("active");
                if (perfData) renderActivePerf();
            });
        });
    }

    function bindTradeForm() {
        const btn = document.getElementById("tradeSubmit");
        if (btn) {
            btn.addEventListener("click", async () => {
                const entry = parseFloat(document.getElementById("tradeEntry")?.value);
                const exit_p = parseFloat(document.getElementById("tradeExit")?.value);
                const sl = parseFloat(document.getElementById("tradeSL")?.value);
                const dir = document.getElementById("tradeDirection")?.value || "long";
                const setup = document.getElementById("tradeSetup")?.value || "";
                const notes = document.getElementById("tradeNotes")?.value || "";

                if (!entry || !exit_p) {
                    alert("Entry and Exit prices are required.");
                    return;
                }

                try {
                    const resp = await fetch("/api/trades", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            entry_price: entry,
                            exit_price: exit_p,
                            stop_loss: sl || 0,
                            direction: dir,
                            setup_type: setup,
                            notes: notes,
                            regime: currentRegime || "",
                            sub_regime: currentSubRegime || "",
                            timeframe: activeTimeframe,
                        }),
                    });
                    if (resp.ok) {
                        // Clear form
                        ["tradeEntry", "tradeExit", "tradeSL", "tradeNotes"].forEach(id => {
                            const el = document.getElementById(id);
                            if (el) el.value = "";
                        });
                        fetchPerformance();
                        fetchRisk(); // refresh frequency governor
                    }
                } catch (e) {
                    console.error("Trade log error:", e);
                }
            });
        }
    }

    let currentRegime = "";
    let currentSubRegime = "";

    async function fetchPerformance() {
        try {
            const [perf, trades] = await Promise.all([
                fetchJSON("/api/performance"),
                fetchJSON("/api/trades?limit=50"),
            ]);
            if (perf && !perf.error) {
                perfData = perf;
                renderActivePerf();
            }
            if (trades) {
                renderTradeLog(trades);
            }
        } catch (e) {
            console.error("Performance fetch error:", e);
        }
    }

    function renderActivePerf() {
        if (!perfData) return;
        const activeTab = document.querySelector(".perf-tab.active");
        if (!activeTab) return;
        const view = activeTab.dataset.pview;

        switch (view) {
            case "overview": renderPerfOverview(perfData.overall); break;
            case "by-regime": renderPerfBreakdown("perfByRegime", perfData.by_regime); break;
            case "by-time": renderPerfByTime(perfData.by_time); break;
            case "by-setup": renderPerfBreakdown("perfBySetup", perfData.by_setup); break;
        }
    }

    function renderPerfOverview(stats) {
        const grid = document.getElementById("perfStatsGrid");
        if (!grid || !stats) return;

        const items = [
            { label: "Total Trades", value: stats.total_trades, cls: "gold" },
            { label: "Win Rate", value: `${stats.win_rate}%`, cls: stats.win_rate >= 50 ? "positive" : "negative" },
            { label: "Profit Factor", value: stats.profit_factor, cls: stats.profit_factor >= 1.5 ? "positive" : stats.profit_factor >= 1 ? "gold" : "negative" },
            { label: "Expectancy (R)", value: stats.expectancy_r, cls: stats.expectancy_r > 0 ? "positive" : "negative" },
            { label: "Total P&L %", value: `${stats.total_pnl_pct > 0 ? "+" : ""}${stats.total_pnl_pct}%`, cls: stats.total_pnl_pct >= 0 ? "positive" : "negative" },
            { label: "Avg Win", value: stats.avg_win?.toFixed(2), cls: "positive" },
            { label: "Avg Loss", value: stats.avg_loss?.toFixed(2), cls: "negative" },
            { label: "Max Drawdown", value: `${stats.max_drawdown_pct}%`, cls: "negative" },
            { label: "Win Streak", value: stats.max_win_streak, cls: "positive" },
            { label: "Loss Streak", value: stats.max_loss_streak, cls: "negative" },
            { label: "Avg R-Multiple", value: stats.avg_r_multiple, cls: stats.avg_r_multiple > 0 ? "positive" : "negative" },
            { label: "Current Streak", value: stats.current_streak > 0 ? `+${stats.current_streak}` : stats.current_streak, cls: stats.current_streak >= 0 ? "positive" : "negative" },
        ];

        grid.innerHTML = items.map(i => `
            <div class="perf-stat">
                <span class="perf-stat-label">${i.label}</span>
                <span class="perf-stat-value ${i.cls}">${i.value}</span>
            </div>
        `).join("");

        // Equity chart
        fetchJSON("/api/performance/equity").then(curve => {
            if (curve && curve.length > 1) renderEquityChart(curve);
        });
    }

    function renderEquityChart(curve) {
        const ctx = document.getElementById("equityChart");
        if (!ctx) return;

        if (equityChart) equityChart.destroy();

        const labels = curve.map(c => c.trade_num);
        const data = curve.map(c => c.equity_pct);
        const colors = curve.map(c =>
            c.result === "win" ? "rgba(16,185,129,0.8)" :
            c.result === "loss" ? "rgba(239,68,68,0.8)" : "rgba(148,163,184,0.5)"
        );

        equityChart = new Chart(ctx, {
            type: "line",
            data: {
                labels,
                datasets: [{
                    label: "Equity %",
                    data,
                    borderColor: "rgba(212,168,67,0.8)",
                    backgroundColor: "rgba(212,168,67,0.1)",
                    fill: true,
                    tension: 0.3,
                    pointRadius: 3,
                    pointBackgroundColor: colors,
                    borderWidth: 2,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `Equity: ${ctx.parsed.y.toFixed(2)}%`,
                        },
                    },
                },
                scales: {
                    x: {
                        title: { display: true, text: "Trade #", color: "#64748b", font: { size: 10 } },
                        grid: { color: "rgba(71,85,105,0.15)" },
                        ticks: { color: "#64748b", font: { size: 9 } },
                    },
                    y: {
                        title: { display: true, text: "Cumulative %", color: "#64748b", font: { size: 10 } },
                        grid: { color: "rgba(71,85,105,0.15)" },
                        ticks: { color: "#64748b", font: { size: 9 } },
                    },
                },
            },
        });
    }

    function renderPerfBreakdown(containerId, breakdown) {
        const el = document.getElementById(containerId);
        if (!el || !breakdown) return;

        const keys = Object.keys(breakdown);
        if (keys.length === 0) {
            el.innerHTML = `<div style="color:var(--text-muted);text-align:center;padding:24px;font-size:0.8rem">No data yet — log trades to see breakdowns</div>`;
            return;
        }

        el.innerHTML = `
            <div class="perf-breakdown-row header">
                <span></span>
                <span>Trades</span>
                <span>Win %</span>
                <span>PF</span>
                <span>Exp R</span>
                <span>P&L %</span>
            </div>
            ${keys.map(k => {
                const s = breakdown[k];
                return `<div class="perf-breakdown-row">
                    <span class="perf-bd-label">${k}</span>
                    <span class="perf-bd-val">${s.total_trades}</span>
                    <span class="perf-bd-val ${s.win_rate >= 50 ? "positive" : "negative"}">${s.win_rate}%</span>
                    <span class="perf-bd-val">${s.profit_factor}</span>
                    <span class="perf-bd-val ${s.expectancy_r > 0 ? "positive" : "negative"}">${s.expectancy_r}</span>
                    <span class="perf-bd-val ${s.total_pnl_pct >= 0 ? "positive" : "negative"}">${s.total_pnl_pct}%</span>
                </div>`;
            }).join("")}
        `;
    }

    function renderPerfByTime(byTime) {
        if (!byTime) return;
        renderPerfBreakdown("perfBySession", byTime.by_session);
        renderPerfBreakdown("perfByDay", byTime.by_day);
    }

    function renderTradeLog(trades) {
        const tbody = document.getElementById("tradeTableBody");
        if (!tbody) return;

        if (!trades || trades.length === 0) {
            tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;color:var(--text-muted);padding:20px">No trades logged yet</td></tr>`;
            return;
        }

        tbody.innerHTML = trades.map(t => {
            const time = t.entry_time ? new Date(t.entry_time * 1000).toLocaleString("en-ZA", {
                timeZone: "Africa/Johannesburg", hour12: false,
                month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
            }) : "—";
            const pnlClass = t.result === "win" ? "win" : t.result === "loss" ? "loss" : "";
            const pnlSign = t.pnl_points > 0 ? "+" : "";

            return `<tr>
                <td>${time}</td>
                <td>${t.direction?.toUpperCase()?.charAt(0) || "—"}</td>
                <td>${t.entry_price?.toFixed(2) || "—"}</td>
                <td>${t.exit_price?.toFixed(2) || "—"}</td>
                <td class="${pnlClass}">${pnlSign}${t.pnl_points?.toFixed(2) || 0}</td>
                <td class="${pnlClass}">${t.r_multiple?.toFixed(2) || "—"}R</td>
                <td>${t.regime || "—"}</td>
                <td>${abbreviateSetup(t.setup_type || "")}</td>
                <td><button class="delete-btn" onclick="deleteTrade(${t.id})">✕</button></td>
            </tr>`;
        }).join("");
    }

    // Make deleteTrade global for inline onclick
    window.deleteTrade = async function(id) {
        if (!confirm("Delete this trade?")) return;
        try {
            await fetch(`/api/trades/${id}`, { method: "DELETE" });
            fetchPerformance();
            fetchRisk();
        } catch (e) {
            console.error("Delete error:", e);
        }
    };

    // ── Timeframe Selectors ────────────────────────────────────────────
    function bindTimeframeSelectors() {
        // Timeframe strip (regime)
        document.querySelectorAll(".tf-item").forEach(item => {
            item.addEventListener("click", () => {
                document.querySelectorAll(".tf-item").forEach(i => i.classList.remove("active"));
                item.classList.add("active");
                activeTimeframe = item.dataset.tf;
                poll();
            });
        });

        // Chart timeframe buttons
        document.querySelectorAll(".tf-btn").forEach(btn => {
            btn.addEventListener("click", () => {
                document.querySelectorAll(".tf-btn").forEach(b => b.classList.remove("active"));
                btn.classList.add("active");
                chartTimeframe = btn.dataset.tf;
                poll();
            });
        });
    }

    // ── AI Interpreter (Panel G) ────────────────────────────────────
    let interpTimer = null;

    async function fetchInterpretation() {
        try {
            const data = await fetchJSON(`/api/interpret/${activeTimeframe}`);
            if (data && !data.error) updateInterpreterPanel(data);
        } catch (e) {
            console.error("Interpreter fetch error:", e);
        }
    }

    function updateInterpreterPanel(d) {
        const banner = document.getElementById("interpBanner");
        const actionEl = document.getElementById("interpAction");
        const convEl = document.getElementById("interpConviction");
        const narrativeEl = document.getElementById("interpNarrative");
        const reasoningEl = document.getElementById("interpReasoning");
        const warningsEl = document.getElementById("interpWarnings");
        const warningsSec = document.getElementById("interpWarningsSection");
        const regimePill = document.getElementById("interpRegimePill");
        const tendencyPill = document.getElementById("interpTendencyPill");
        const setupPill = document.getElementById("interpSetupPill");
        const callout = document.getElementById("interpSetupCallout");

        if (!banner) return;

        // Action banner class
        banner.className = "interp-action-banner";
        if (d.action.includes("LONG")) banner.classList.add("look-longs");
        else if (d.action.includes("SHORT")) banner.classList.add("look-shorts");
        else if (d.action === "SIT OUT") banner.classList.add("sit-out");
        else banner.classList.add("wait");

        actionEl.textContent = d.action;

        // Conviction badge
        convEl.textContent = d.conviction + " CONVICTION";
        convEl.className = "interp-conviction " + (d.conviction || "none").toLowerCase();

        // Context pills
        regimePill.textContent = (d.regime || "—").toUpperCase();
        regimePill.style.borderColor =
            d.regime === "trending" ? "#10b981" :
            d.regime === "ranging" ? "#f59e0b" :
            d.regime === "expanding" ? "#ef4444" :
            d.regime === "choppy" ? "#8b5cf6" : "var(--border)";

        const tBias = (d.tendency_bias || "neutral").toUpperCase();
        const tStr = d.tendency_strength ? ` ${Math.round(d.tendency_strength)}%` : "";
        tendencyPill.textContent = `${tBias}${tStr}`;

        setupPill.textContent = d.setup_count > 0
            ? `${d.setup_count} SETUP${d.setup_count > 1 ? "S" : ""}`
            : "NO SETUPS";

        // Narrative
        narrativeEl.textContent = d.narrative || "Waiting for data...";

        // Reasoning
        reasoningEl.innerHTML = (d.reasoning || [])
            .map(r => `<div class="interp-item">${r}</div>`).join("");

        // Warnings
        if (d.warnings && d.warnings.length > 0) {
            warningsSec.style.display = "";
            warningsEl.innerHTML = d.warnings
                .map(w => `<div class="interp-item">${w}</div>`).join("");
        } else {
            warningsSec.style.display = "none";
        }

        // Best setup callout
        if (d.best_setup && d.best_setup.composite >= 30) {
            callout.style.display = "";
            document.getElementById("interpSetupName").textContent = d.best_setup.name;
            const dirEl = document.getElementById("interpSetupDir");
            dirEl.textContent = d.best_setup.direction;
            dirEl.className = "callout-dir " + (d.best_setup.direction || "");
            document.getElementById("interpSetupScore").textContent =
                `Composite: ${Math.round(d.best_setup.composite)}`;
        } else {
            callout.style.display = "none";
        }
    }

    // ── Meta-Analysis Banner ───────────────────────────────────────
    async function fetchMetaAnalysis() {
        try {
            const data = await fetchJSON(`/api/meta/${activeTimeframe}`);
            if (data && !data.error) updateMetaBanner(data);
        } catch (err) {
            console.error("Meta fetch error:", err);
        }
    }

    function updateMetaBanner(d) {
        const score = d.alignment_score || 0;
        const label = d.alignment_label || "—";
        const ring = document.getElementById("metaScoreRing");
        const val = document.getElementById("metaScoreValue");
        const status = document.getElementById("metaScoreStatus");
        const conflictsEl = document.getElementById("metaConflicts");
        const fatigueEl = document.getElementById("metaFatigue");

        if (!ring || !val) return;

        val.textContent = score;
        ring.className = "meta-score-ring " + label.toLowerCase();
        status.textContent = d.meta_narrative ? d.meta_narrative.split(".")[0] + "." : label;

        // Conflict pills
        const conflicts = d.conflicts || [];
        if (conflicts.length > 0) {
            conflictsEl.innerHTML = conflicts.slice(0, 4).map(c => {
                const sevClass = c.severity === "high" ? "high" : c.severity === "medium" ? "medium" : "low-sev";
                // Short label from type
                const labels = {
                    "regime_vs_tendency": "REGIME/TENDENCY",
                    "regime_vs_setup": "REGIME/SETUP",
                    "setup_vs_regime_direction": "SETUP DIR",
                    "indicator_conflict": "INDICATORS",
                    "conviction_mismatch": "CONVICTION",
                    "alert_overload": "ALERT OVERLOAD",
                    "alert_vs_regime": "ALERTS/REGIME",
                    "compression_in_trend": "COMPRESSION",
                    "timeframe_hierarchy": "TF HIERARCHY",
                };
                const lbl = labels[c.type] || c.type.toUpperCase();
                return `<span class="meta-conflict-pill ${sevClass}" title="${c.description}">${lbl}</span>`;
            }).join("");
        } else {
            conflictsEl.innerHTML = '<span class="meta-conflict-pill low-sev">NO CONFLICTS</span>';
        }

        // Fatigue warning
        const fatigue = d.regime_fatigue || {};
        if (fatigue.is_fatigued) {
            fatigueEl.style.display = "flex";
            fatigueEl.innerHTML = `⏱ REGIME FATIGUE — ${fatigue.duration_readings} readings` +
                (fatigue.likely_next ? ` → likely ${fatigue.likely_next.toUpperCase()} (${Math.round(fatigue.transition_prob)}%)` : "");
        } else {
            fatigueEl.style.display = "none";
        }
    }

    // Start interpreter polling (every 10s — heavier endpoint)
    function initInterpreter() {
        fetchInterpretation();
        fetchMetaAnalysis();
        interpTimer = setInterval(fetchInterpretation, 10000);
        setInterval(fetchMetaAnalysis, 15000);  // meta every 15s
    }

    // ── Click-to-Explain System ─────────────────────────────────────
    function initExplainSystem() {
        const overlay = document.getElementById("explainOverlay");
        const closeBtn = document.getElementById("explainClose");
        if (!overlay || !closeBtn) return;

        // Click any explainable element
        document.addEventListener("click", async (e) => {
            // Block if the actual click target is an interactive element
            const tag = e.target.tagName.toLowerCase();
            if (tag === "input" || tag === "select" || tag === "textarea") return;
            if (e.target.closest(".alert-dismiss, .delete-btn, .form-submit, .tendency-tab, .perf-tab, .tf-btn")) return;

            const el = e.target.closest(".explainable");
            if (!el) return;

            const key = el.dataset.explain;
            if (!key) return;

            try {
                const data = await fetchJSON(`/api/explain/${key}`);
                if (data && !data.error) {
                    document.getElementById("explainTitle").textContent = data.title || key;
                    document.getElementById("explainBody").textContent = data.explanation || "";
                    document.getElementById("explainUsage").textContent = data.how_to_use || "";
                    overlay.style.display = "flex";
                }
            } catch (err) {
                console.error("Explain fetch error:", err);
            }
        });

        // Close modal
        closeBtn.addEventListener("click", () => { overlay.style.display = "none"; });
        overlay.addEventListener("click", (e) => {
            if (e.target === overlay) overlay.style.display = "none";
        });

        // ESC key closes
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape" && overlay.style.display !== "none") {
                overlay.style.display = "none";
            }
        });
    }

    // ── Chat Assistant (Panel H) ────────────────────────────────────
    function initChat() {
        const input = document.getElementById("chatInput");
        const sendBtn = document.getElementById("chatSend");
        const chips = document.getElementById("chatChips");
        if (!input || !sendBtn) return;

        // Send on button click
        sendBtn.addEventListener("click", () => sendChatMessage());

        // Send on Enter key
        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendChatMessage();
            }
        });

        // Quick question chips
        if (chips) {
            chips.addEventListener("click", (e) => {
                const chip = e.target.closest(".chat-chip");
                if (!chip) return;
                const q = chip.dataset.q;
                if (q) {
                    input.value = q;
                    sendChatMessage();
                }
            });
        }
    }

    async function sendChatMessage() {
        const input = document.getElementById("chatInput");
        const sendBtn = document.getElementById("chatSend");
        const messages = document.getElementById("chatMessages");
        if (!input || !messages) return;

        const question = input.value.trim();
        if (!question) return;

        // Clear input and disable
        input.value = "";
        sendBtn.disabled = true;

        // Add user message
        appendChatMsg("user", question);

        // Add typing indicator
        const typingId = "typing-" + Date.now();
        const typingHtml = `<div class="chat-msg assistant" id="${typingId}">
            <div class="chat-msg-avatar">&#9670;</div>
            <div class="chat-msg-bubble">
                <div class="chat-msg-typing"><span></span><span></span><span></span></div>
            </div>
        </div>`;
        messages.insertAdjacentHTML("beforeend", typingHtml);
        messages.scrollTop = messages.scrollHeight;

        try {
            const resp = await fetch("/api/ask", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ question, timeframe: activeTimeframe }),
            });
            const data = await resp.json();

            // Remove typing indicator
            const typingEl = document.getElementById(typingId);
            if (typingEl) typingEl.remove();

            if (data.answer) {
                appendChatMsg("assistant", data.answer);
            } else if (data.error) {
                appendChatMsg("assistant", "Sorry, I couldn't process that. Try rephrasing your question.");
            }
        } catch (err) {
            const typingEl = document.getElementById(typingId);
            if (typingEl) typingEl.remove();
            appendChatMsg("assistant", "Connection error. Make sure the dashboard is running.");
            console.error("Chat error:", err);
        }

        sendBtn.disabled = false;
        input.focus();
    }

    function appendChatMsg(role, text) {
        const messages = document.getElementById("chatMessages");
        if (!messages) return;

        const avatar = role === "user" ? "YOU" : "&#9670;";

        // Convert markdown-style bold **text** to <strong>
        const formatted = text
            .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
            .replace(/\n/g, "<br>");

        const html = `<div class="chat-msg ${role}">
            <div class="chat-msg-avatar">${avatar}</div>
            <div class="chat-msg-bubble">
                <div class="chat-msg-text">${formatted}</div>
            </div>
        </div>`;

        messages.insertAdjacentHTML("beforeend", html);
        messages.scrollTop = messages.scrollHeight;
    }

    // ── Footer Time ────────────────────────────────────────────────────
    function updateFooterTime() {
        const el = document.getElementById("footerTime");
        if (el) {
            const now = new Date();
            el.textContent = now.toLocaleString("en-ZA", {
                timeZone: "Africa/Johannesburg",
                hour12: false,
                year: "numeric",
                month: "short",
                day: "numeric",
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
            }) + " SAST";
        }
    }

})();
