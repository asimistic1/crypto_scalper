/**
 * Streamlit bidirectional live chart — Binance WS + Lightweight Charts v5.
 * Communicates via postMessage (Streamlit custom component protocol).
 */
(function () {
  const UP = "#0ECB81";
  const DOWN = "#F6465D";
  const EMA_COLORS = { 9: "#FFEB3B", 21: "#FF9800", 50: "#2196F3", 200: "#9C27B0" };
  const PK_TZ = "Asia/Karachi";
  const BACKOFF = [1000, 2000, 5000, 10000, 30000];

  const el = (id) => document.getElementById(id);

  let chart = null;
  let candleSeries = null;
  let volumeSeries = null;
  let vwapSeries = null;
  const emaLineSeries = {};
  let riskAreaSeries = null;
  let rewardAreaSeries = null;

  let ws = null;
  let backoffIx = 0;
  let reconnectTimer = null;
  let wsOpenTimer = null;
  let lastWsError = "";
  let candles = [];
  let precision = { type: "price", minMove: 0.1, precision: 1 };
  let lastAggPrice = null;
  let currentPriceLine = null;
  let crosshairActive = false;

  let renderArgs = {};
  let currentSymbol = "";
  let currentTf = "";
  let overlaySignature = "";

  let priceLineHandles = [];
  let zoneBandSeries = [];
  let pendingPrice = null;
  let rafScheduled = false;

  let setupState = null;
  let setupStatus = "ACTIVE";
  let lastEventNonce = "";
  let lastClosedCandleTime = null;

  const {
    createChart,
    CandlestickSeries,
    HistogramSeries,
    LineSeries,
    AreaSeries,
    CrosshairMode,
  } = LightweightCharts;

  function sendToStreamlit(type, payload) {
    window.parent.postMessage(
      Object.assign({ isStreamlitMessage: true, type: type }, payload),
      "*"
    );
  }

  function setFrameHeight(px) {
    sendToStreamlit("streamlit:setFrameHeight", { height: px });
  }

  function setComponentValue(value) {
    sendToStreamlit("streamlit:setComponentValue", {
      value: value,
      dataType: "json",
    });
  }

  function fmtTime(utcSec) {
    return new Date(utcSec * 1000).toLocaleString("en-GB", {
      timeZone: PK_TZ,
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function precisionFromTickSize(tickSize) {
    const s = String(tickSize);
    if (!s.includes(".")) return 0;
    return s.split(".")[1].length;
  }

  function fmtNum(n, prec) {
    if (n == null || !Number.isFinite(n)) return "—";
    const p = prec != null ? prec : precision.precision;
    return Number(n).toLocaleString("en-US", {
      minimumFractionDigits: p,
      maximumFractionDigits: p,
    });
  }

  function fmtPrice(n) {
    return fmtNum(n, precision.precision);
  }

  function chartPriceFormat() {
    return {
      type: "price",
      precision: precision.precision,
      minMove: precision.minMove,
    };
  }

  function fmtVol(n) {
    if (n >= 1e9) return (n / 1e9).toFixed(2) + "B";
    if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
    return String(n);
  }

  function setStatus(mode, text) {
    el("status-dot").className = mode;
    el("conn-text").textContent = text;
  }

  function scheduleUiRefresh(price) {
    pendingPrice = price;
    if (rafScheduled) return;
    rafScheduled = true;
    requestAnimationFrame(() => {
      rafScheduled = false;
      const p = pendingPrice;
      pendingPrice = null;
      if (p != null) {
        flashPrice(p);
        updatePriceLine(p);
        updateSetupLifecycle(p);
      }
      if (!crosshairActive && candles.length) {
        renderEmaLegend(candles.length - 1);
      }
    });
  }

  function flashPrice(price) {
    const p = el("last-price");
    p.textContent = fmtNum(price, precision.precision);
    if (lastAggPrice != null) {
      p.classList.remove("flash-up", "flash-down");
      void p.offsetWidth;
      if (price > lastAggPrice) p.classList.add("flash-up");
      else if (price < lastAggPrice) p.classList.add("flash-down");
    }
    lastAggPrice = price;
  }

  function calcEMA(closes, period) {
    const out = new Array(closes.length).fill(null);
    if (closes.length < period) return out;
    let sum = 0;
    for (let i = 0; i < period; i++) sum += closes[i];
    let prev = sum / period;
    out[period - 1] = prev;
    const k = 2 / (period + 1);
    for (let i = period; i < closes.length; i++) {
      prev = closes[i] * k + prev * (1 - k);
      out[i] = prev;
    }
    return out;
  }

  function calcRSI(closes, period) {
    if (closes.length < period + 1) return null;
    let gains = 0,
      losses = 0;
    for (let i = closes.length - period; i < closes.length; i++) {
      const d = closes[i] - closes[i - 1];
      if (d >= 0) gains += d;
      else losses -= d;
    }
    const avgL = losses / period;
    if (avgL === 0) return 100;
    const rs = gains / period / avgL;
    return 100 - 100 / (1 + rs);
  }

  function calcATR(data, period) {
    if (data.length < period + 1) return null;
    const trs = [];
    for (let i = 1; i < data.length; i++) {
      const h = data[i].high,
        l = data[i].low,
        pc = data[i - 1].close;
      trs.push(Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc)));
    }
    return trs.slice(-period).reduce((a, b) => a + b, 0) / period;
  }

  function updateIndicators() {
    const closes = candles.map((c) => c.close);
    el("rsi").textContent =
      calcRSI(closes, 14) != null ? calcRSI(closes, 14).toFixed(2) : "—";
    const atr = calcATR(candles, 14);
    el("atr").textContent = atr != null ? atr.toFixed(2) : "—";
  }

  function emaSeriesData(period) {
    const closes = candles.map((c) => c.close);
    const ema = calcEMA(closes, period);
    const data = [];
    for (let i = 0; i < candles.length; i++) {
      if (ema[i] != null) data.push({ time: candles[i].time, value: ema[i] });
    }
    return data;
  }

  function emaAtIndex(candleIdx, period) {
    if (candleIdx < 0 || !candles.length) return null;
    const ema = calcEMA(
      candles.map((c) => c.close),
      period
    );
    return ema[candleIdx];
  }

  function renderEmaLegend(candleIdx) {
    const box = el("ema-legend");
    box.replaceChildren();
    const toggles = renderArgs.toggles || {};
    if (!toggles.emas || !candles.length || candleIdx == null || candleIdx < 0)
      return;
    [9, 21, 50, 200].forEach((p) => {
      const v = emaAtIndex(candleIdx, p);
      if (v == null) return;
      const span = document.createElement("span");
      span.className = "ema-item";
      span.style.color = EMA_COLORS[p];
      span.textContent = "EMA " + p + ": " + fmtPrice(v);
      box.appendChild(span);
    });
  }

  function refreshVwap() {
    if (!vwapSeries || !candles.length) return;
    const toggles = renderArgs.toggles || {};
    if (toggles.vwap !== true) {
      vwapSeries.applyOptions({ visible: false });
      return;
    }
    vwapSeries.applyOptions({ visible: true });
    const closes = candles.map((c) => c.close);
    const vols = candles.map((c) => c.volume);
    let cumPv = 0;
    let cumV = 0;
    const data = candles.map((c, i) => {
      const tp = (c.high + c.low + closes[i]) / 3;
      cumPv += tp * vols[i];
      cumV += vols[i];
      return { time: c.time, value: cumV ? cumPv / cumV : closes[i] };
    });
    vwapSeries.setData(data);
  }

  function refreshEmaLines() {
    const toggles = renderArgs.toggles || {};
    const show = toggles.emas !== false;
    [9, 21, 50, 200].forEach((p) => {
      emaLineSeries[p].applyOptions({ visible: show });
      if (!show) return;
      emaLineSeries[p].setData(emaSeriesData(p));
      const v = emaAtIndex(candles.length - 1, p);
      if (v != null)
        emaLineSeries[p].applyOptions({ title: "EMA " + p + " " + fmtPrice(v) });
    });
    if (!crosshairActive) renderEmaLegend(candles.length - 1);
  }

  function clearOverlayLines() {
    priceLineHandles.forEach((h) => {
      try {
        candleSeries.removePriceLine(h);
      } catch (_) {}
    });
    priceLineHandles = [];
    zoneBandSeries.forEach((s) => {
      try {
        chart.removeSeries(s);
      } catch (_) {}
    });
    zoneBandSeries = [];
    if (riskAreaSeries) {
      riskAreaSeries.setData([]);
    }
    if (rewardAreaSeries) {
      rewardAreaSeries.setData([]);
    }
  }

  function pctFromEntry(entry, price) {
    if (!entry || !Number.isFinite(price)) return "";
    const pct = ((price - entry) / entry) * 100;
    const sign = pct >= 0 ? "+" : "";
    return sign + pct.toFixed(2) + "%";
  }

  function applyOverlays() {
    clearOverlayLines();
    const ov = renderArgs.overlays || {};
    const toggles = renderArgs.toggles || {};
    const lines = ov.lines || [];
    const zones = ov.zones || [];
    const markers = ov.markers || [];
    const setup = ov.setup;

    if (toggles.setup_lines !== false && setup) {
      setupState = setup;
      setupStatus = setup.status || "ACTIVE";
      updateSetupBadge();
      const entry = +setup.entry;
      const sl = +setup.sl;
      const tps = [setup.tp1, setup.tp2, setup.tp3].map(Number);
      if (Number.isFinite(entry)) {
        priceLineHandles.push(
          candleSeries.createPriceLine({
            price: entry,
            color: "#2962FF",
            lineWidth: 2,
            lineStyle: 0,
            title: "Entry " + fmtPrice(entry),
          })
        );
      }
      if (Number.isFinite(sl)) {
        priceLineHandles.push(
          candleSeries.createPriceLine({
            price: sl,
            color: DOWN,
            lineWidth: 1,
            lineStyle: 2,
            title:
              "SL " + fmtPrice(sl) + " (" + pctFromEntry(entry, sl) + ")",
          })
        );
      }
      tps.forEach((tp, ix) => {
        if (!Number.isFinite(tp)) return;
        priceLineHandles.push(
          candleSeries.createPriceLine({
            price: tp,
            color: UP,
            lineWidth: 1,
            lineStyle: 2,
            title:
              "TP" +
              (ix + 1) +
              " " +
              fmtPrice(tp) +
              " (" +
              pctFromEntry(entry, tp) +
              ")",
          })
        );
      });
      paintRiskReward(setup);
    } else {
      setupState = null;
      el("setup-badge").classList.add("hidden");
      if (riskAreaSeries) riskAreaSeries.setData([]);
      if (rewardAreaSeries) rewardAreaSeries.setData([]);
    }

    if (toggles.zones !== false && candles.length) {
      const ref = candles[candles.length - 1].close;
      const usedLabels = new Set();
      zones.forEach((z) => {
        if (!Number.isFinite(z.from) || !Number.isFinite(z.to)) return;
        const lo = Math.min(z.from, z.to);
        const hi = Math.max(z.from, z.to);
        const color = z.color || "rgba(14,203,129,0.25)";
        const near =
          Number.isFinite(z.near) ? z.near : Math.abs(ref - lo) <= Math.abs(ref - hi) ? lo : hi;
        const far = near === lo ? hi : lo;
        const lbl = (z.label || "").trim();
        if (lbl && usedLabels.has(lbl)) return;
        if (lbl) usedLabels.add(lbl);

        const band = chart.addSeries(AreaSeries, {
          topColor: color,
          bottomColor: "rgba(0,0,0,0)",
          lineColor: "rgba(0,0,0,0)",
          lineWidth: 0,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        try {
          band.applyOptions({ baseValue: { type: "price", price: lo } });
        } catch (_) {}
        band.setData(candles.map((c) => ({ time: c.time, value: hi })));
        zoneBandSeries.push(band);

        priceLineHandles.push(
          candleSeries.createPriceLine({
            price: near,
            color: color.replace("0.22", "0.55"),
            lineStyle: 2,
            lineWidth: 1,
            title: lbl,
            axisLabelVisible: !!lbl,
          })
        );
        priceLineHandles.push(
          candleSeries.createPriceLine({
            price: far,
            color: color.replace("0.22", "0.45"),
            lineStyle: 2,
            lineWidth: 1,
            title: "",
            axisLabelVisible: false,
          })
        );
      });
    }

    if (toggles.setup_lines !== false) {
      lines.forEach((line) => {
        if (!Number.isFinite(line.price)) return;
        priceLineHandles.push(
          candleSeries.createPriceLine({
            price: line.price,
            color: line.color || "#2962FF",
            title: line.title || "",
            lineStyle: line.style === "dashed" ? 2 : 0,
          })
        );
      });
    }

    refreshVwap();

    const showMarkers =
      toggles.swings !== false || toggles.setup_lines !== false;
    if (showMarkers && markers.length) {
      candleSeries.setMarkers(
        markers.map((m) => ({
          time: m.time,
          position: m.position || "belowBar",
          color: m.color || UP,
          shape: m.shape || "circle",
          text: m.text || "",
        }))
      );
    } else {
      candleSeries.setMarkers([]);
    }
  }

  function paintRiskReward(setup) {
    if (!candles.length || !riskAreaSeries || !rewardAreaSeries) return;
    if (!setup || !Number.isFinite(+setup.entry)) {
      riskAreaSeries.setData([]);
      rewardAreaSeries.setData([]);
      return;
    }
    const signal = setup.signal_time
      ? Math.floor(new Date(setup.signal_time).getTime() / 1000)
      : candles[Math.max(0, candles.length - 20)].time;
    const entry = +setup.entry;
    const sl = +setup.sl;
    const tp2 = +setup.tp2;
    const tail = candles.filter((c) => c.time >= signal);
    if (!tail.length) return;
    const riskLo = Math.min(entry, sl);
    const riskHi = Math.max(entry, sl);
    try {
      riskAreaSeries.applyOptions({ baseValue: { type: "price", price: riskLo } });
      rewardAreaSeries.applyOptions({ baseValue: { type: "price", price: entry } });
    } catch (_) {}
    riskAreaSeries.setData(tail.map((c) => ({ time: c.time, value: riskHi })));
    const rewardLevel = Number.isFinite(tp2) ? tp2 : entry;
    const rewardBase = Math.min(entry, rewardLevel);
    const rewardTop = Math.max(entry, rewardLevel);
    rewardAreaSeries.applyOptions({ baseValue: { type: "price", price: rewardBase } });
    rewardAreaSeries.setData(tail.map((c) => ({ time: c.time, value: rewardTop })));
  }

  function updateSetupBadge() {
    const badge = el("setup-badge");
    if (!setupState) {
      badge.classList.add("hidden");
      return;
    }
    badge.classList.remove("hidden");
    badge.textContent = (setupState.direction || "") + " · " + setupStatus;
    badge.style.color =
      setupStatus.includes("SL") || setupStatus === "INVALIDATED"
        ? DOWN
        : setupStatus.includes("TP") || setupStatus === "TRIGGERED"
          ? UP
          : "#eaecef";
  }

  function updateEntryOffset(price) {
    if (!setupState || !Number.isFinite(+setupState.entry)) {
      el("entry-offset").textContent = "";
      return;
    }
    const entry = +setupState.entry;
    const pct = ((price - entry) / entry) * 100;
    const dir = pct >= 0 ? "above" : "below";
    el("entry-offset").textContent =
      "Price is " + Math.abs(pct).toFixed(2) + "% " + dir + " entry";
  }

  function emitCandleClosed(candleSec, closeMs) {
    const nonce = Date.now() + "-candle_closed-" + closeMs;
    if (nonce === lastEventNonce) return;
    lastEventNonce = nonce;
    setComponentValue({
      event: "candle_closed",
      symbol: currentSymbol,
      timeframe: currentTf,
      time: candleSec,
      close_ms: closeMs,
      nonce: nonce,
    });
  }

  function emitComponentEvent(kind) {
    if (!setupState) return;
    const nonce = Date.now() + "-" + kind;
    if (nonce === lastEventNonce) return;
    lastEventNonce = nonce;
    setComponentValue({
      event: kind,
      symbol: currentSymbol,
      timeframe: currentTf,
      time: candles.length ? candles[candles.length - 1].time : null,
      status: setupStatus,
      setup_id: setupState.setup_id || "",
      nonce: nonce,
    });
  }

  function updateSetupLifecycle(price) {
    if (!setupState) return;
    const entry = +setupState.entry;
    const sl = +setupState.sl;
    const tp1 = +setupState.tp1;
    const dir = (setupState.direction || "LONG").toUpperCase();
    const prev = setupStatus;

    if (setupState.expires_at) {
      const exp = new Date(setupState.expires_at).getTime();
      if (Date.now() > exp && setupStatus === "ACTIVE") {
        setupStatus = "EXPIRED";
      }
    }

    if (dir === "LONG") {
      if (setupStatus === "ACTIVE") {
        if (price <= entry) setupStatus = "TRIGGERED";
        else if (price <= sl || (Number.isFinite(tp1) && price >= tp1))
          setupStatus = "INVALIDATED";
      } else if (setupStatus === "TRIGGERED") {
        if (price <= sl) setupStatus = "SL_HIT";
        else if (Number.isFinite(tp1) && price >= tp1) setupStatus = "TP1_HIT";
      }
    } else if (dir === "SHORT") {
      if (setupStatus === "ACTIVE") {
        if (price >= entry) setupStatus = "TRIGGERED";
        else if (price >= sl || (Number.isFinite(tp1) && price <= tp1))
          setupStatus = "INVALIDATED";
      } else if (setupStatus === "TRIGGERED") {
        if (price >= sl) setupStatus = "SL_HIT";
        else if (Number.isFinite(tp1) && price <= tp1) setupStatus = "TP1_HIT";
      }
    }

    updateSetupBadge();
    updateEntryOffset(price);
    if (setupStatus !== prev) emitComponentEvent("status_changed");
  }

  function initChart(height) {
    const container = el("chart-container");
    container.style.height = height + "px";

    chart = createChart(container, {
      layout: {
        background: { color: "#161A1E" },
        textColor: "#b7bdc6",
        attributionLogo: true,
      },
      grid: { vertLines: { color: "#22262a" }, horzLines: { color: "#22262a" } },
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: { timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderColor: "#2b3139" },
    });

    candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: UP,
      downColor: DOWN,
      borderUpColor: UP,
      borderDownColor: DOWN,
      wickUpColor: UP,
      wickDownColor: DOWN,
      priceFormat: chartPriceFormat(),
    });

    volumeSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      priceLineVisible: false,
      lastValueVisible: false,
    });
    chart.priceScale("volume").applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
    });
    chart.priceScale("right").applyOptions({
      scaleMargins: { top: 0.05, bottom: 0.22 },
    });

    vwapSeries = chart.addSeries(LineSeries, {
      color: "#00BCD4",
      lineWidth: 1,
      title: "VWAP",
      visible: false,
      priceLineVisible: false,
    });

    [9, 21, 50, 200].forEach((p) => {
      emaLineSeries[p] = chart.addSeries(LineSeries, {
        color: EMA_COLORS[p],
        lineWidth: 1,
        title: "EMA " + p,
        priceLineVisible: false,
        lastValueVisible: true,
        priceFormat: chartPriceFormat(),
      });
    });

    riskAreaSeries = chart.addSeries(AreaSeries, {
      lineColor: "rgba(246,70,93,0.35)",
      topColor: "rgba(246,70,93,0.18)",
      bottomColor: "rgba(246,70,93,0.02)",
      lineWidth: 0,
      priceLineVisible: false,
      lastValueVisible: false,
    });
    rewardAreaSeries = chart.addSeries(AreaSeries, {
      lineColor: "rgba(14,203,129,0.35)",
      topColor: "rgba(14,203,129,0.15)",
      bottomColor: "rgba(14,203,129,0.02)",
      lineWidth: 0,
      priceLineVisible: false,
      lastValueVisible: false,
    });

    chart.subscribeCrosshairMove((param) => {
      const leg = el("legend");
      if (!param.time || !param.seriesData.size) {
        crosshairActive = false;
        leg.style.display = "none";
        renderEmaLegend(candles.length - 1);
        return;
      }
      const c = param.seriesData.get(candleSeries);
      const v = param.seriesData.get(volumeSeries);
      if (!c) {
        crosshairActive = false;
        leg.style.display = "none";
        renderEmaLegend(candles.length - 1);
        return;
      }
      crosshairActive = true;
      const idx = candles.findIndex((row) => row.time === param.time);
      renderEmaLegend(idx >= 0 ? idx : candles.length - 1);
      leg.style.display = "block";
      leg.textContent =
        fmtTime(param.time) +
        " O " +
        fmtPrice(c.open) +
        " H " +
        fmtPrice(c.high) +
        " L " +
        fmtPrice(c.low) +
        " C " +
        fmtPrice(c.close) +
        (v ? " Vol " + fmtVol(v.value) : "");
    });

    new ResizeObserver(() => {
      const w = container.clientWidth;
      if (w > 0) chart.applyOptions({ width: w, height: height });
    }).observe(container);
  }

  function applyPriceFormatAll() {
    const pf = chartPriceFormat();
    candleSeries.applyOptions({ priceFormat: pf });
    [9, 21, 50, 200].forEach((p) =>
      emaLineSeries[p].applyOptions({ priceFormat: pf })
    );
    chart.applyOptions({
      localization: {
        timeFormatter: (t) => fmtTime(t),
        priceFormatter: (price) => fmtPrice(price),
      },
    });
  }

  function setCandles(data, replace) {
    candles = replace
      ? data.slice()
      : mergeCandles(candles, data);
    candleSeries.setData(candles);
    volumeSeries.setData(
      candles.map((c) => ({
        time: c.time,
        value: c.volume,
        color:
          c.close >= c.open
            ? "rgba(14,203,129,0.5)"
            : "rgba(246,70,93,0.5)",
      }))
    );
    refreshEmaLines();
    updateIndicators();
    applyOverlays();
  }

  function mergeCandles(existing, incoming) {
    const map = new Map(existing.map((c) => [c.time, c]));
    incoming.forEach((c) => map.set(c.time, c));
    return Array.from(map.values()).sort((a, b) => a.time - b.time);
  }

  function klineToCandle(k) {
    return {
      time: Math.floor(k.t / 1000),
      open: +k.o,
      high: +k.h,
      low: +k.l,
      close: +k.c,
      volume: +k.v,
    };
  }

  function onKline(k) {
    const c = klineToCandle(k);
    if (k.x === true && c.time !== lastClosedCandleTime) {
      lastClosedCandleTime = c.time;
      const closeMs = k.T != null ? +k.T : c.time * 1000;
      emitCandleClosed(c.time, closeMs);
    }
    if (!candles.length) {
      setCandles([c], true);
      return;
    }
    const last = candles[candles.length - 1];
    if (c.time === last.time) candles[candles.length - 1] = c;
    else if (c.time > last.time) candles.push(c);
    else {
      const idx = candles.findIndex((x) => x.time === c.time);
      if (idx >= 0) candles[idx] = c;
    }
    candleSeries.update(candles[candles.length - 1]);
    const lastC = candles[candles.length - 1];
    volumeSeries.update({
      time: lastC.time,
      value: lastC.volume,
      color:
        lastC.close >= lastC.open
          ? "rgba(14,203,129,0.5)"
          : "rgba(246,70,93,0.5)",
    });
    refreshEmaLines();
    refreshVwap();
    updateIndicators();
  }

  function updatePriceLine(price) {
    if (currentPriceLine) candleSeries.removePriceLine(currentPriceLine);
    currentPriceLine = candleSeries.createPriceLine({
      price: price,
      color: "#848E9C",
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: true,
      title: "",
    });
  }

  async function fetchPrecision(restSymbol, tickSize) {
    if (Number.isFinite(tickSize) && tickSize > 0) {
      precision = {
        type: "price",
        minMove: tickSize,
        precision: precisionFromTickSize(tickSize),
      };
      applyPriceFormatAll();
      return;
    }
    try {
      const r = await fetch(
        "https://fapi.binance.com/fapi/v1/exchangeInfo"
      );
      const j = await r.json();
      const sym = j.symbols.find((s) => s.symbol === restSymbol);
      if (!sym) return;
      const tick = sym.filters.find((f) => f.filterType === "PRICE_FILTER");
      const tickSizeStr = tick ? tick.tickSize : "0.1";
      const minMove = parseFloat(tickSizeStr);
      precision = {
        type: "price",
        minMove: minMove,
        precision: precisionFromTickSize(tickSizeStr),
      };
      applyPriceFormatAll();
    } catch (e) {
      console.warn("exchangeInfo", e);
    }
  }

  async function fetchHistory(restSymbol, tf, limit, fallback) {
    const url =
      "https://fapi.binance.com/fapi/v1/klines?symbol=" +
      encodeURIComponent(restSymbol) +
      "&interval=" +
      encodeURIComponent(tf) +
      "&limit=" +
      limit;
    try {
      const r = await fetch(url);
      if (!r.ok) throw new Error("HTTP " + r.status);
      const raw = await r.json();
      const data = raw.map((row) => ({
        time: Math.floor(row[0] / 1000),
        open: +row[1],
        high: +row[2],
        low: +row[3],
        close: +row[4],
        volume: +row[5],
      }));
      setCandles(data, true);
      return true;
    } catch (e) {
      console.warn("klines", e);
      if (fallback && fallback.length) {
        setCandles(fallback, true);
        return true;
      }
      return false;
    }
  }

  function wsUrl(wsSymbol, tf) {
    const streams = [
      wsSymbol + "@kline_" + tf,
      wsSymbol + "@aggTrade",
      wsSymbol + "@ticker",
    ].join("/");
    return "wss://fstream.binance.com/market/stream?streams=" + streams;
  }

  function closeWs() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (wsOpenTimer) {
      clearTimeout(wsOpenTimer);
      wsOpenTimer = null;
    }
    if (ws) {
      ws.onclose = null;
      ws.onerror = null;
      ws.close();
      ws = null;
    }
  }

  function scheduleReconnect() {
    setStatus("reconnecting", "Reconnecting…");
    const delay = BACKOFF[Math.min(backoffIx, BACKOFF.length - 1)];
    backoffIx++;
    reconnectTimer = setTimeout(async () => {
      await fetchHistory(
        currentSymbol,
        currentTf,
        100,
        renderArgs.fallback_candles || []
      );
      connectWs();
    }, delay);
  }

  function validWsMessage(msg, wsSymbol) {
    if (!msg || typeof msg !== "object") return false;
    const stream = String(msg.stream || "");
    if (!stream || stream.indexOf(wsSymbol) !== 0) return false;
    const d = msg.data;
    return d && typeof d === "object";
  }

  function connectWs() {
    closeWs();
    const wsSymbol = currentSymbol.toLowerCase();
    lastWsError = "";
    setStatus("reconnecting", "Starting…");
    const url = wsUrl(wsSymbol, currentTf);
    ws = new WebSocket(url);
    wsOpenTimer = setTimeout(() => {
      if (ws && ws.readyState !== WebSocket.OPEN) {
        const msg = lastWsError || "WebSocket still closed after 10s (" + url + ")";
        setStatus("", msg);
      }
    }, 10000);
    ws.onopen = () => {
      if (wsOpenTimer) {
        clearTimeout(wsOpenTimer);
        wsOpenTimer = null;
      }
      backoffIx = 0;
      setStatus("live", "Live");
    };
    ws.onmessage = (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (!validWsMessage(msg, wsSymbol)) return;
      const stream = msg.stream;
      const d = msg.data;
      if (stream.endsWith("@aggTrade")) {
        const price = +d.p;
        if (!Number.isFinite(price)) return;
        const lat = Date.now() - d.E;
        el("latency").textContent = "Latency: " + lat + " ms";
        scheduleUiRefresh(price);
      } else if (stream.includes("@kline_")) {
        if (d && d.k) onKline(d.k);
      } else if (stream.endsWith("@ticker")) {
        const last = +d.c;
        if (!Number.isFinite(last)) return;
        scheduleUiRefresh(last);
        el("chg").textContent = (+d.P).toFixed(2) + "%";
        el("chg").style.color = +d.P >= 0 ? UP : DOWN;
        el("hi").textContent = fmtNum(+d.h, precision.precision);
        el("lo").textContent = fmtNum(+d.l, precision.precision);
        el("vol").textContent = fmtVol(+d.q);
      }
    };
    ws.onerror = () => {
      if (wsOpenTimer) {
        clearTimeout(wsOpenTimer);
        wsOpenTimer = null;
      }
      lastWsError = "WebSocket error (check CSP / network)";
      setStatus("", lastWsError);
    };
    ws.onclose = (ev) => {
      if (wsOpenTimer) {
        clearTimeout(wsOpenTimer);
        wsOpenTimer = null;
      }
      if (!lastWsError && ev && ev.code) {
        lastWsError = "WebSocket closed (" + ev.code + ")";
      }
      scheduleReconnect();
    };
  }

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    if (renderArgs.streaming_enabled === false) return;
    if (!currentSymbol) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) connectWs();
  });

  function overlaySig(args) {
    return JSON.stringify({
      overlays: args.overlays || {},
      toggles: args.toggles || {},
    });
  }

  async function onSymbolTfChange(args) {
    currentSymbol = args.symbol;
    currentTf = args.timeframe;
    el("symbol").textContent =
      (args.display_symbol || args.symbol) + " · " + currentTf;
    await fetchPrecision(currentSymbol, +args.tick_size);
    const ok = await fetchHistory(
      currentSymbol,
      currentTf,
      Math.min(+args.history_limit || 500, 1000),
      args.fallback_candles || []
    );
    if (!ok) setStatus("", "No history");
    if (args.streaming_enabled !== false) connectWs();
    else {
      closeWs();
      setStatus("", "Paused");
    }
    applyOverlays();
  }

  function onRender(args) {
    renderArgs = args || {};
    const height = +args.height || 750;
    if (!chart) initChart(height);
    else
      chart.applyOptions({ height: height });
    setFrameHeight(height + 88);

    const sym = args.symbol || "";
    const tf = args.timeframe || "15m";
    const sig = overlaySig(args);
    const marketChanged = sym !== currentSymbol || tf !== currentTf;

    if (marketChanged) {
      overlaySignature = sig;
      onSymbolTfChange(args);
      return;
    }

    if (sig !== overlaySignature) {
      overlaySignature = sig;
      applyOverlays();
    }

    if (!ws && args.streaming_enabled !== false && candles.length) connectWs();
    if (args.streaming_enabled === false) {
      closeWs();
      setStatus("", "Paused");
    }
  }

  window.addEventListener("message", (event) => {
    if (!event.data || event.data.type !== "streamlit:render") return;
    onRender(event.data.args || {});
  });

  sendToStreamlit("streamlit:componentReady", { apiVersion: 1 });
  setFrameHeight(838);
  window.addEventListener("beforeunload", closeWs);
})();