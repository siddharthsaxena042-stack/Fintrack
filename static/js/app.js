(function () {
  "use strict";

  const THEME_KEY = "fintrack_theme";
  const SIDEBAR_KEY = "fintrack_sidebar_collapsed";

  function applyTheme(theme) {
    const t = theme === "light" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", t);
    localStorage.setItem(THEME_KEY, t);
    const themeIcon = document.getElementById("themeToggleIcon");
    if (themeIcon) {
      themeIcon.textContent = t === "light" ? "🌙" : "☀️";
    }
    window.dispatchEvent(new CustomEvent("fintrack:theme", { detail: { theme: t } }));
  }

  function formatINR(value) {
    const num = Number(value || 0);
    const neg = num < 0;
    const abs = Math.abs(num);
    const parts = abs.toFixed(2).split(".");
    let whole = parts[0];
    if (whole.length > 3) {
      const last3 = whole.slice(-3);
      let rest = whole.slice(0, -3);
      const groups = [];
      while (rest.length > 2) {
        groups.unshift(rest.slice(-2));
        rest = rest.slice(0, -2);
      }
      if (rest) groups.unshift(rest);
      whole = groups.join(",") + "," + last3;
    }
    return (neg ? "-₹" : "₹") + whole + "." + parts[1];
  }

  window.FinTrack = { formatINR };

  document.addEventListener("DOMContentLoaded", function () {
    // 1. Theme Initialization
    const savedTheme = localStorage.getItem(THEME_KEY) || "dark";
    applyTheme(savedTheme);

    const themeBtn = document.getElementById("themeToggleBtn");
    if (themeBtn) {
      themeBtn.addEventListener("click", function () {
        const current = document.documentElement.getAttribute("data-theme") || "dark";
        applyTheme(current === "dark" ? "light" : "dark");
      });
    }

    // 2. Sidebar Collapse & Mobile Drawer
    if (localStorage.getItem(SIDEBAR_KEY) === "1") {
      document.body.classList.add("sidebar-collapsed");
    }

    const collapseBtn = document.getElementById("sidebarCollapseBtn");
    if (collapseBtn) {
      collapseBtn.addEventListener("click", function () {
        document.body.classList.toggle("sidebar-collapsed");
        localStorage.setItem(
          SIDEBAR_KEY,
          document.body.classList.contains("sidebar-collapsed") ? "1" : "0"
        );
      });
    }

    const mobileMenuBtn = document.getElementById("mobileMenuBtn");
    if (mobileMenuBtn) {
      mobileMenuBtn.addEventListener("click", function () {
        document.body.classList.toggle("mobile-sidebar-open");
      });
    }

    // 3. Notifications Bell Dropdown
    const notifBtn = document.getElementById("notifBellBtn");
    const notifMenu = document.getElementById("notifDropdown");
    const notifList = document.getElementById("notifList");
    const notifBadge = document.getElementById("notifUnreadBadge");
    const markAllBtn = document.getElementById("markAllReadBtn");

    async function loadNotifications() {
      if (!notifList) return;
      try {
        const res = await fetch("/api/notifications");
        if (!res.ok) return;
        const data = await res.json();
        const count = data.unread_count || 0;
        if (notifBadge) {
          notifBadge.textContent = count > 9 ? "9+" : String(count);
          notifBadge.style.display = count > 0 ? "inline-flex" : "none";
        }
        if (!data.notifications || data.notifications.length === 0) {
          notifList.innerHTML = '<div style="padding:16px;color:var(--text-muted);text-align:center;">No notifications yet.</div>';
          return;
        }
        notifList.innerHTML = data.notifications
          .map(
            (n) => `
            <div class="notif-item ${n.is_read ? "" : "unread"}" data-notif-id="${n.id}">
              <div>${escapeHtml(n.message)}</div>
              <div style="font-size:11px;color:var(--text-muted);margin-top:4px;">${escapeHtml(n.created_at)}</div>
            </div>`
          )
          .join("");

        notifList.querySelectorAll(".notif-item.unread").forEach((el) => {
          el.addEventListener("click", async () => {
            await fetch("/api/notifications/read", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ id: Number(el.dataset.notifId) }),
            });
            loadNotifications();
          });
        });
      } catch (err) {
        // Ignore network errors while offline
      }
    }

    window.FinTrack.refreshNotifications = loadNotifications;

    if (notifBtn && notifMenu) {
      loadNotifications();
      notifBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        notifMenu.classList.toggle("open");
        if (notifMenu.classList.contains("open")) {
          loadNotifications();
        }
      });
      document.addEventListener("click", function (e) {
        if (!notifMenu.contains(e.target) && e.target !== notifBtn) {
          notifMenu.classList.remove("open");
        }
      });
    }

    if (markAllBtn) {
      markAllBtn.addEventListener("click", async function (e) {
        e.stopPropagation();
        await fetch("/api/notifications/read", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
        loadNotifications();
      });
    }

    // 4. AI Finance Helper Drawer
    const aiOpenBtn = document.getElementById("aiHelperOpenBtn");
    const aiCloseBtn = document.getElementById("aiHelperCloseBtn");
    const aiDrawer = document.getElementById("aiDrawer");
    const aiForm = document.getElementById("aiChatForm");
    const aiInput = document.getElementById("aiPromptInput");
    const aiMessages = document.getElementById("aiMessages");

    async function sendAiPrompt(text) {
      if (!text.trim() || !aiMessages) return;
      const userBubble = document.createElement("div");
      userBubble.className = "ai-bubble user";
      userBubble.textContent = text;
      aiMessages.appendChild(userBubble);
      aiMessages.scrollTop = aiMessages.scrollHeight;

      try {
        const res = await fetch("/api/ai-assistant", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ prompt: text }),
        });
        const data = await res.json();
        const botBubble = document.createElement("div");
        botBubble.className = "ai-bubble bot";
        botBubble.textContent = data.reply || "Unable to generate insight right now.";
        aiMessages.appendChild(botBubble);
      } catch (err) {
        const errBubble = document.createElement("div");
        errBubble.className = "ai-bubble bot";
        errBubble.textContent = "Connection error while contacting AI Finance Helper.";
        aiMessages.appendChild(errBubble);
      }
      aiMessages.scrollTop = aiMessages.scrollHeight;
    }

    if (aiOpenBtn && aiDrawer) {
      aiOpenBtn.addEventListener("click", () => aiDrawer.classList.add("open"));
    }
    if (aiCloseBtn && aiDrawer) {
      aiCloseBtn.addEventListener("click", () => aiDrawer.classList.remove("open"));
    }
    if (aiForm && aiInput) {
      aiForm.addEventListener("submit", function (e) {
        e.preventDefault();
        const val = aiInput.value;
        aiInput.value = "";
        sendAiPrompt(val);
      });
    }
    document.querySelectorAll("[data-ai-chip]").forEach((btn) => {
      btn.addEventListener("click", () => sendAiPrompt(btn.dataset.aiChip));
    });

    // 5. Global Socket.IO Real-time Market Stream
    if (typeof io !== "undefined" && document.getElementById("globalMarketStatusPill")) {
      const socket = io();
      window.FinTrack.socket = socket;

      const lastPrices = {};

      socket.on("market_tick", function (payload) {
        if (!payload) return;
        const status = payload.status;
        if (status) {
          updateStatusPill(status);
        }

        const quotes = payload.quotes || {};
        Object.keys(quotes).forEach((sym) => {
          const q = quotes[sym];
          const prev = lastPrices[sym];
          const dir = prev !== undefined ? (q.ltp > prev ? "tick-up" : q.ltp < prev ? "tick-down" : "") : "";
          lastPrices[sym] = q.ltp;

          document.querySelectorAll(`[data-live-symbol="${CSS.escape(sym)}"]`).forEach((row) => {
            const ltpEl = row.querySelector('[data-field="ltp"]');
            const chgEl = row.querySelector('[data-field="change_pct"]');
            const absChgEl = row.querySelector('[data-field="change"]');
            const isPos = Number(q.change_pct) >= 0;

            if (ltpEl) {
              ltpEl.textContent = formatINR(q.ltp);
              if (dir) {
                ltpEl.classList.remove("tick-up", "tick-down");
                void ltpEl.offsetWidth;
                ltpEl.classList.add(dir);
              }
            }
            if (chgEl) {
              chgEl.textContent = `${isPos ? "+" : ""}${Number(q.change_pct).toFixed(2)}%`;
              chgEl.classList.toggle("text-green", isPos);
              chgEl.classList.toggle("text-red", !isPos);
              if (chgEl.classList.contains("badge")) {
                chgEl.classList.toggle("badge-green", isPos);
                chgEl.classList.toggle("badge-red", !isPos);
              }
            }
            if (absChgEl) {
              absChgEl.textContent = `${isPos ? "+" : ""}${formatINR(q.change)}`;
              absChgEl.classList.toggle("text-green", isPos);
              absChgEl.classList.toggle("text-red", !isPos);
            }
          });
        });

        window.dispatchEvent(new CustomEvent("fintrack:market_tick", { detail: payload }));
      });
    }
  });

  function updateStatusPill(status) {
    const pill = document.getElementById("globalMarketStatusPill");
    if (!pill) return;
    pill.setAttribute("data-badge", status.badge);
    pill.setAttribute("title", `${status.source} — ${status.detail}`);
    const badgeText = document.getElementById("globalStatusBadgeText");
    const timeText = document.getElementById("globalStatusTime");
    if (badgeText) badgeText.textContent = status.badge;
    if (timeText) timeText.textContent = `${status.source} • ${status.timestamp}`;

    const termBadge = document.getElementById("terminalStatusBadge");
    const termSource = document.getElementById("terminalStatusSource");
    if (termBadge) termBadge.textContent = status.badge;
    if (termSource) termSource.textContent = `${status.source} (${status.timestamp})`;
  }

  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
})();
