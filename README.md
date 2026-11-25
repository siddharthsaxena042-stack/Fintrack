# FinTrack — Personal Finance & Live Stock Market Paper-Trading Dashboard

FinTrack is a full-stack web application built with **Python 3, Flask (modular Blueprints), Flask-SocketIO, SQLite (ACID transactions), TradingView Lightweight Charts, and Chart.js**.

## Project Structure

```text
fintrack/
├── app.py                  # Flask + Socket.IO application factory & entry point
├── config.py               # Environment config & NSE instrument registry
├── database.py             # SQLite connection helpers & BEGIN IMMEDIATE ACID manager
├── init_db.py              # Idempotent 8-table SQLite schema initializer
├── market_service.py       # Upstox API v3 REST/WebSocket + yfinance/simulated fallback
├── trading_service.py      # Atomic BUY/SELL paper trading engine & live P&L
├── finance_service.py      # Expense analytics, savings goal planner & risk scoring
├── routes/
│   ├── auth.py             # Signup, Login, Logout & user-isolation guard
│   ├── main.py             # Unified Dashboard, Notifications API & AI Finance Helper
│   ├── market.py           # Live Market Terminal, Watchlist & Candle/Quote APIs
│   ├── trading.py          # Paper Portfolio & Order execution APIs
│   └── finance.py          # Expenses CRUD/CSV, Savings Goals & Risk Reports
├── templates/              # Jinja2 HTML5 templates
├── static/
│   ├── css/style.css       # Responsive Dark/Light theme styles
│   └── js/                 # Socket.IO client, Lightweight Charts terminal & UI scripts
├── requirements.txt
└── .env.example
```

## Quick Start

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment (optional for Upstox API v3):**
   ```bash
   cp .env.example .env
   ```
   Set `UPSTOX_ACCESS_TOKEN` in `.env` for live Upstox API v3 market quotes & WebSocket streaming during NSE market hours (`09:15–15:30 IST`, Mon–Fri). When omitted or when the market is closed, FinTrack automatically activates its `yfinance` + simulated tick fallback engine and truthfully displays `DELAYED` or `OFFLINE/FALLBACK` in the header status pill.

3. **Initialize the SQLite database:**
   ```bash
   python init_db.py
   ```

4. **Start the server:**
   ```bash
   python app.py
   ```
   Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.
