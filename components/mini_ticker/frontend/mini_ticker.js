/**
 * Binance futures !miniTicker@arr — one WS, filtered symbols to Streamlit.
 */
(function () {
  const WS_URL = "wss://fstream.binance.com/ws/!miniTicker@arr";
  let ws = null;
  let symbols = new Set();
  let cache = {};
  let pushTimer = null;
  let lastPush = 0;

  function sendToStreamlit(type, payload) {
    window.parent.postMessage(
      Object.assign({ isStreamlitMessage: true, type: type }, payload),
      "*"
    );
  }

  function setComponentValue(value) {
    sendToStreamlit("streamlit:setComponentValue", {
      value: value,
      dataType: "json",
    });
  }

  function validTicker(t) {
    return (
      t &&
      typeof t.s === "string" &&
      t.s.endsWith("USDT") &&
      Number.isFinite(+t.c) &&
      Number.isFinite(+t.P)
    );
  }

  function maybePush() {
    const now = Date.now();
    if (now - lastPush < 800) return;
    lastPush = now;
    const out = {};
    symbols.forEach((sym) => {
      if (cache[sym]) out[sym] = cache[sym];
    });
    if (Object.keys(out).length) {
      setComponentValue({ event: "watch_prices", prices: out, nonce: String(now) });
    }
  }

  function connect() {
    if (ws) {
      try {
        ws.close();
      } catch (_) {}
    }
    ws = new WebSocket(WS_URL);
    ws.onopen = () => {
      document.getElementById("status").textContent = "live";
    };
    ws.onmessage = (ev) => {
      let data;
      try {
        data = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (!Array.isArray(data)) return;
      data.forEach((t) => {
        if (!validTicker(t) || !symbols.has(t.s)) return;
        cache[t.s] = { c: +t.c, P: +t.P, v: +t.q || 0 };
      });
      maybePush();
    };
    ws.onerror = () => {
      document.getElementById("status").textContent = "error";
    };
    ws.onclose = () => {
      document.getElementById("status").textContent = "reconnecting";
      setTimeout(connect, 3000);
    };
  }

  function onRender(args) {
    sendToStreamlit("streamlit:setFrameHeight", { height: 4 });
    const list = (args && args.symbols) || [];
    symbols = new Set(list.map((s) => String(s).toUpperCase()));
    if (!ws) connect();
    maybePush();
  }

  window.addEventListener("message", (event) => {
    if (!event.data || event.data.type !== "streamlit:render") return;
    onRender(event.data.args || {});
  });

  sendToStreamlit("streamlit:componentReady", { apiVersion: 1 });
  sendToStreamlit("streamlit:setFrameHeight", { height: 4 });
})();