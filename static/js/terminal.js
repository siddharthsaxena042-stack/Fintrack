(function () {
  "use strict";

  document.addEventListener("DOMContentLoaded", function () {
    const configEl = document.getElementById("terminalConfig");
    if (!configEl) return;

    let currentSymbol = configEl.dataset.symbol || "RELIANCE";
    let currentTimeframe = "5m";
    let chartType = "candlestick"; // 'candlestick' | 'area'
    let currentSide = "BUY";
    let currentLtp = Number(configEl.dataset.ltp || 0);
    let inWatchlist = configEl.dataset.inWatchlist === "1";
    let lastBar = null;
    let candlesData = [];
    let lastSocketTickAt = 0;
    let fallbackPollInFlight = false;

    const chartContainer = document.getElementById("tvChartContainer");
    let chart = null;
    let candleSeries = null;
    let areaSeries = null;

    function getChartColors() {
      const isLight = document.documentElement.getAttribute("data-theme") === "light";
      return {
        bg: isLight ? "#ffffff" : "#0f1a31",
        text: isLight ? "#334155" : "#94a3b8",
        grid: isLight ? "rgba(15, 23, 42, 0.06)" : "rgba(148, 163, 184, 0.08)",
        border: isLight ? "rgba(15, 23, 42, 0.14)" : "rgba(148, 163, 184, 0.18)",
      };
    }

    function initChart() {
      if (!chartContainer || typeof LightweightCharts === "undefined") return;
      if (chart) {
        chart.remove();
        chart = null;
      }
      const colors = getChartColors();
      chart = LightweightCharts.createChart(chartContainer, {
        width: chartContainer.clientWidth,
        height: 450,
        layout: {
          background: { type: "solid", color: colors.bg },
          textColor: colors.text,
        },
        grid: {
          vertLines: { color: colors.grid },
          horzLines: { color: colors.grid },
        },
        crosshair: {
          mode: LightweightCharts.CrosshairMode.Normal,
        },
        rightPriceScale: {
          borderColor: colors.border,
        },
        timeScale: {
          borderColor: colors.border,
          timeVisible: true,
          secondsVisible: false,
        },
      });

      candleSeries = chart.addCandlestickSeries({
        upColor: "#10b981",
        downColor: "#ef4444",
        borderUpColor: "#10b981",
        borderDownColor: "#ef4444",
        wickUpColor: "#10b981",
        wickDownColor: "#ef4444",
      });

      areaSeries = chart.addAreaSeries({
        lineColor: "#38bdf8",
        topColor: "rgba(56, 189, 248, 0.35)",
        bottomColor: "rgba(56, 189, 248, 0.02)",
        lineWidth: 2,
      });

      renderActiveSeries();
    }

    function renderActiveSeries() {
      if (!candleSeries || !areaSeries) return;
      if (chartType === "candlestick") {
        candleSeries.applyOptions({ visible: true });
        areaSeries.applyOptions({ visible: false });
        candleSeries.setData(candlesData);
      } else {
        candleSeries.applyOptions({ visible: false });
        areaSeries.applyOptions({ visible: true });
        areaSeries.setData(
          candlesData.map((c) => ({ time: c.time, value: c.close }))
        );
      }
      if (chart && candlesData.length > 0) {
        chart.timeScale().fitContent();
      }
    }

    function updateLatestCandle(bar) {
      if (!bar) return;
      const existingIndex = candlesData.findIndex((candle) => candle.time === bar.time);
      if (existingIndex >= 0) {
        candlesData[existingIndex] = bar;
      } else if (!lastBar || bar.time > lastBar.time) {
        candlesData.push(bar);
      } else {
        return;
      }
      lastBar = bar;

      if (chartType === "candlestick" && candleSeries) {
        candleSeries.update(bar);
      } else if (chartType === "area" && areaSeries) {
        areaSeries.update({ time: bar.time, value: bar.close });
      }
    }

    window.addEventListener("resize", function () {
      if (chart && chartContainer) {
        chart.applyOptions({ width: chartContainer.clientWidth });
      }
    });

    window.addEventListener("fintrack:theme", function () {
      if (!chart) return;
      const colors = getChartColors();
      chart.applyOptions({
        layout: { background: { type: "solid", color: colors.bg }, textColor: colors.text },
        grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
        rightPriceScale: { borderColor: colors.border },
        timeScale: { borderColor: colors.border },
      });
    });

    async function loadSymbolData(symbol, timeframe) {
      currentSymbol = symbol;
      currentTimeframe = timeframe;
      try {
        const res = await fetch(
          `/api/market/candles/${encodeURIComponent(symbol)}?timeframe=${encodeURIComponent(timeframe)}`
        );
        if (!res.ok) return;
        const data = await res.json();
        candlesData = data.candles || [];
        lastBar = candlesData.length ? candlesData[candlesData.length - 1] : null;
        renderActiveSeries();
        updateQuoteUI(data.quote, data.holding, data.in_watchlist);

        const nextUrl = `/market?symbol=${encodeURIComponent(data.symbol)}`;
        window.history.replaceState({}, "", nextUrl);
      } catch (err) {
        console.error("Failed to load market candles:", err);
      }
    }

    function updateQuoteUI(quote, holding, watchedFlag) {
      if (!quote) return;
      currentLtp = Number(quote.ltp || 0);
      const isPos = Number(quote.change_pct || 0) >= 0;

      const symTitle = document.getElementById("termSymbolTitle");
      const symSub = document.getElementById("termCompanyName");
      const ltpEl = document.getElementById("termLtp");
      const chgEl = document.getElementById("termChange");
      const openEl = document.getElementById("termOpen");
      const highEl = document.getElementById("termHigh");
      const lowEl = document.getElementById("termLow");
      const volEl = document.getElementById("termVolume");
      const orderSym = document.getElementById("orderPanelSymbol");

      if (symTitle) symTitle.textContent = quote.symbol;
      if (symSub) symSub.textContent = `${quote.name} • ${quote.exchange} • ${quote.sector}`;
      if (orderSym) orderSym.textContent = quote.symbol;
      if (ltpEl) ltpEl.textContent = window.FinTrack.formatINR(quote.ltp);
      if (chgEl) {
        chgEl.textContent = `${isPos ? "+" : ""}${window.FinTrack.formatINR(quote.change)} (${isPos ? "+" : ""}${Number(quote.change_pct).toFixed(2)}%)`;
        chgEl.classList.toggle("text-green", isPos);
        chgEl.classList.toggle("text-red", !isPos);
      }
      if (openEl) openEl.textContent = window.FinTrack.formatINR(quote.open);
      if (highEl) highEl.textContent = window.FinTrack.formatINR(quote.high);
      if (lowEl) lowEl.textContent = window.FinTrack.formatINR(quote.low);
      if (volEl) volEl.textContent = Number(quote.volume || 0).toLocaleString("en-IN");

      if (holding !== undefined) {
        updateHoldingInfo(holding);
      }
      if (watchedFlag !== undefined) {
        inWatchlist = Boolean(watchedFlag);
        updateWatchlistBtn();
      }
      updateEstimatedTotal();
    }

    function updateHoldingInfo(holding) {
      const holdQtyEl = document.getElementById("orderHoldingQty");
      const holdAvgEl = document.getElementById("orderHoldingAvg");
      if (holding) {
        if (holdQtyEl) holdQtyEl.textContent = `${holding.quantity} qty`;
        if (holdAvgEl) holdAvgEl.textContent = `Avg ${window.FinTrack.formatINR(holding.avg_buy_price)}`;
      } else {
        if (holdQtyEl) holdQtyEl.textContent = "0 qty";
        if (holdAvgEl) holdAvgEl.textContent = "No active position";
      }
    }

    function updateWatchlistBtn() {
      const btn = document.getElementById("toggleWatchlistBtn");
      if (!btn) return;
      if (inWatchlist) {
        btn.textContent = "✓ In Watchlist";
        btn.classList.remove("btn-ghost");
        btn.classList.add("btn-primary");
      } else {
        btn.textContent = "+ Watchlist";
        btn.classList.add("btn-ghost");
        btn.classList.remove("btn-primary");
      }
    }

    function updateEstimatedTotal() {
      const qtyInput = document.getElementById("orderQtyInput");
      const estEl = document.getElementById("orderEstimatedValue");
      const execPriceEl = document.getElementById("orderExecPrice");
      const qty = Math.max(0, parseInt(qtyInput ? qtyInput.value : "0", 10) || 0);
      if (execPriceEl) execPriceEl.textContent = window.FinTrack.formatINR(currentLtp);
      if (estEl) estEl.textContent = window.FinTrack.formatINR(qty * currentLtp);
    }

    // Timeframe selectors
    document.querySelectorAll("[data-timeframe]").forEach((btn) => {
      btn.addEventListener("click", function () {
        document.querySelectorAll("[data-timeframe]").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        loadSymbolData(currentSymbol, btn.dataset.timeframe);
      });
    });

    // Chart type selectors
    document.querySelectorAll("[data-chart-type]").forEach((btn) => {
      btn.addEventListener("click", function () {
        document.querySelectorAll("[data-chart-type]").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        chartType = btn.dataset.chartType;
        renderActiveSeries();
      });
    });

    // Search bar with dropdown
    const searchInput = document.getElementById("stockSearchInput");
    const searchDropdown = document.getElementById("stockSearchResults");

    async function performSearch(query) {
      if (!searchDropdown) return;
      try {
        const res = await fetch(`/api/market/search?q=${encodeURIComponent(query)}`);
        if (!res.ok) return;
        const data = await res.json();
        const list = data.instruments || [];
        if (list.length === 0) {
          searchDropdown.innerHTML = '<div style="padding:12px;color:var(--text-muted);">No matching NSE equities</div>';
        } else {
          searchDropdown.innerHTML = list
            .map((item) => {
              const pos = Number(item.change_pct) >= 0;
              return `
                <div class="search-result-item" data-pick-symbol="${item.symbol}">
                  <div>
                    <div style="font-weight:700;">${item.symbol}</div>
                    <div style="font-size:11.5px;color:var(--text-secondary);">${item.name}</div>
                  </div>
                  <div style="text-align:right;" class="mono">
                    <div style="font-weight:600;">${window.FinTrack.formatINR(item.ltp)}</div>
                    <div class="${pos ? "text-green" : "text-red"}" style="font-size:11.5px;">${pos ? "+" : ""}${Number(item.change_pct).toFixed(2)}%</div>
                  </div>
                </div>`;
            })
            .join("");

          searchDropdown.querySelectorAll("[data-pick-symbol]").forEach((el) => {
            el.addEventListener("click", function () {
              const picked = el.dataset.pickSymbol;
              searchDropdown.classList.remove("open");
              if (searchInput) searchInput.value = "";
              loadSymbolData(picked, currentTimeframe);
            });
          });
        }
        searchDropdown.classList.add("open");
      } catch (err) {
        // Ignore transient search error
      }
    }

    if (searchInput && searchDropdown) {
      searchInput.addEventListener("focus", () => performSearch(searchInput.value));
      searchInput.addEventListener("input", () => performSearch(searchInput.value));
      document.addEventListener("click", function (e) {
        if (!searchDropdown.contains(e.target) && e.target !== searchInput) {
          searchDropdown.classList.remove("open");
        }
      });
    }

    // Watchlist button
    const watchBtn = document.getElementById("toggleWatchlistBtn");
    if (watchBtn) {
      watchBtn.addEventListener("click", async function () {
        if (inWatchlist) {
          const res = await fetch(`/api/watchlist/${encodeURIComponent(currentSymbol)}`, {
            method: "DELETE",
          });
          if (res.ok) {
            inWatchlist = false;
            updateWatchlistBtn();
          }
        } else {
          const res = await fetch("/api/watchlist", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ symbol: currentSymbol }),
          });
          if (res.ok) {
            inWatchlist = true;
            updateWatchlistBtn();
          }
        }
      });
    }

    // Order Panel BUY/SELL tabs & quick qty
    const buyTab = document.getElementById("tabBuy");
    const sellTab = document.getElementById("tabSell");
    const submitBtn = document.getElementById("placeOrderBtn");
    const qtyInput = document.getElementById("orderQtyInput");

    function setOrderSide(side) {
      currentSide = side;
      if (buyTab && sellTab && submitBtn) {
        buyTab.classList.toggle("active-buy", side === "BUY");
        sellTab.classList.toggle("active-sell", side === "SELL");
        submitBtn.classList.toggle("btn-success", side === "BUY");
        submitBtn.classList.toggle("btn-danger", side === "SELL");
        submitBtn.textContent = side === "BUY" ? `Place BUY Order` : `Place SELL Order`;
      }
    }

    if (buyTab) buyTab.addEventListener("click", () => setOrderSide("BUY"));
    if (sellTab) sellTab.addEventListener("click", () => setOrderSide("SELL"));
    if (qtyInput) qtyInput.addEventListener("input", updateEstimatedTotal);

    document.querySelectorAll("[data-qty-preset]").forEach((btn) => {
      btn.addEventListener("click", function () {
        if (qtyInput) {
          qtyInput.value = btn.dataset.qtyPreset;
          updateEstimatedTotal();
        }
      });
    });

    // Submit atomic paper order
    const orderForm = document.getElementById("paperOrderForm");
    const feedbackBox = document.getElementById("orderFeedback");

    if (orderForm) {
      orderForm.addEventListener("submit", async function (e) {
        e.preventDefault();
        if (submitBtn) submitBtn.disabled = true;
        if (feedbackBox) {
          feedbackBox.innerHTML = "";
        }

        const quantity = parseInt(qtyInput ? qtyInput.value : "0", 10);
        try {
          const res = await fetch("/api/trade/order", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              symbol: currentSymbol,
              side: currentSide,
              quantity: quantity,
            }),
          });
          const data = await res.json();
          if (!res.ok) {
            if (feedbackBox) {
              feedbackBox.innerHTML = `<div class="alert alert-danger">${data.error || "Order rejected."}</div>`;
            }
          } else {
            if (feedbackBox) {
              feedbackBox.innerHTML = `<div class="alert alert-success">${data.order.message}</div>`;
            }
            const cashEl = document.getElementById("orderAvailableCash");
            if (cashEl && data.portfolio) {
              cashEl.textContent = window.FinTrack.formatINR(data.portfolio.virtual_balance);
            }
            const holdings = (data.portfolio && data.portfolio.holdings) || [];
            const match = holdings.find((h) => h.symbol === currentSymbol);
            updateHoldingInfo(match || null);
            if (window.FinTrack.refreshNotifications) {
              window.FinTrack.refreshNotifications();
            }
          }
        } catch (err) {
          if (feedbackBox) {
            feedbackBox.innerHTML = '<div class="alert alert-danger">Network error placing order.</div>';
          }
        } finally {
          if (submitBtn) submitBtn.disabled = false;
        }
      });
    }

    // Live WebSocket updates for active chart + quote
    window.addEventListener("fintrack:market_tick", function (e) {
      const payload = e.detail;
      if (!payload || !payload.quotes) return;
      if (payload.source !== "http-poll") lastSocketTickAt = Date.now();
      const q = payload.quotes[currentSymbol];
      if (q) {
        updateQuoteUI(q);
      }

      const latestBySymbol = (payload.latest_candles || {})[currentSymbol];
      const bar = latestBySymbol ? latestBySymbol[currentTimeframe] : null;
      updateLatestCandle(bar);
    });

    async function pollMarketFallback() {
      const socket = window.FinTrack && window.FinTrack.socket;
      if (socket && socket.connected && lastSocketTickAt && Date.now() - lastSocketTickAt <= 3000) return;
      if (fallbackPollInFlight) return;

      const symbol = currentSymbol;
      const timeframe = currentTimeframe;
      fallbackPollInFlight = true;
      try {
        const res = await fetch(
          `/api/market/candles/${encodeURIComponent(symbol)}?timeframe=${encodeURIComponent(timeframe)}`,
          { cache: "no-store" }
        );
        if (!res.ok) return;
        const data = await res.json();
        if (symbol !== currentSymbol || timeframe !== currentTimeframe) return;

        if (data.quote) updateQuoteUI(data.quote);
        const history = data.candles || [];
        if (!candlesData.length && history.length) {
          candlesData = history;
          lastBar = history[history.length - 1];
          renderActiveSeries();
        } else if (history.length) {
          updateLatestCandle(history[history.length - 1]);
        }
      } catch (err) {
        console.warn("Market candle polling failed:", err);
      } finally {
        fallbackPollInFlight = false;
      }
    }

    window.setInterval(pollMarketFallback, 2000);

    // Boot chart & load initial symbol
    initChart();
    loadSymbolData(currentSymbol, currentTimeframe);
  });
})();
