import json
import math
import random
import threading
import time
from datetime import datetime, timedelta
from typing import Any

import pytz
import requests

from config import Config, NSE_INSTRUMENTS

IST = pytz.timezone("Asia/Kolkata")

TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1D": 86400,
}


class MarketDataService:
    """Central Market Data Service supporting Upstox API v3 with yfinance & simulated fallback."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._quotes: dict[str, dict[str, Any]] = {}
        self._candles_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._yf_hydrated_at: dict[str, float] = {}
        self._upstox_ws_connected = False
        self._upstox_rest_ok = False
        self._upstox_error: str | None = None
        self._hydration_started = False
        self._rng = random.Random(42)

        now_ist = self.now_ist()
        for symbol, meta in NSE_INSTRUMENTS.items():
            base = float(meta["ref_price"])
            self._quotes[symbol] = {
                "symbol": symbol,
                "name": meta["name"],
                "exchange": meta["exchange"],
                "instrument_key": meta["instrument_key"],
                "sector": meta["sector"],
                "ltp": base,
                "prev_close": base,
                "open": base,
                "high": base,
                "low": base,
                "change": 0.0,
                "change_pct": 0.0,
                "volume": 125000,
                "timestamp": now_ist.strftime("%Y-%m-%d %H:%M:%S IST"),
                "epoch": int(time.time()),
                "source": "Reference Baseline",
            }

    @staticmethod
    def now_ist() -> datetime:
        return datetime.now(IST)

    @classmethod
    def is_nse_market_open(cls) -> bool:
        """Check whether Indian NSE cash market is currently open (Mon-Fri 09:15-15:30 IST)."""
        now = cls.now_ist()
        if now.weekday() >= 5:
            return False
        minutes = now.hour * 60 + now.minute
        return (9 * 60 + 15) <= minutes <= (15 * 60 + 30)

    def get_status(self) -> dict[str, Any]:
        """Return truthful market feed status badge and source metadata."""
        has_token = bool(Config.UPSTOX_ACCESS_TOKEN)
        market_open = self.is_nse_market_open()
        now_str = self.now_ist().strftime("%d %b %Y, %H:%M:%S IST")

        with self._lock:
            ws_ok = self._upstox_ws_connected
            rest_ok = self._upstox_rest_ok
            err = self._upstox_error
            any_yf = any(
                q.get("source", "").startswith("Yahoo Finance")
                for q in self._quotes.values()
            )

        if has_token and market_open and ws_ok:
            badge = "LIVE STREAM"
            source = "Upstox API v3 WebSocket"
            mode_detail = "Real-time NSE streaming feed active"
        elif has_token and market_open and rest_ok:
            badge = "SNAPSHOT"
            source = "Upstox API v3 REST"
            mode_detail = "Upstox REST polling snapshot active"
        elif has_token and not market_open:
            badge = "OFFLINE/FALLBACK"
            source = "Fallback Simulator (NSE Closed)"
            mode_detail = "NSE market closed (09:15-15:30 IST); running simulated fallback anchored to last close"
        elif not has_token and market_open and any_yf:
            badge = "DELAYED"
            source = "Yahoo Finance + Simulated Tick Fallback"
            mode_detail = "UPSTOX_ACCESS_TOKEN not configured; using delayed yfinance quote + fallback ticks"
        else:
            badge = "OFFLINE/FALLBACK"
            if not has_token:
                reason = "UPSTOX_ACCESS_TOKEN not configured"
            elif err:
                reason = f"Upstox unavailable ({err})"
            else:
                reason = "NSE market closed"
            source = "Fallback Engine (yfinance + Simulated Ticks)"
            mode_detail = f"{reason}; displaying fallback data (not live exchange stream)"

        return {
            "badge": badge,
            "source": source,
            "detail": mode_detail,
            "market_open": market_open,
            "upstox_configured": has_token,
            "timestamp": now_str,
        }

    def list_instruments(self, query: str = "") -> list[dict[str, Any]]:
        """Search supported NSE instruments by symbol, company name, or sector."""
        q = (query or "").strip().lower()
        results = []
        with self._lock:
            for sym, meta in NSE_INSTRUMENTS.items():
                if (
                    not q
                    or q in sym.lower()
                    or q in meta["name"].lower()
                    or q in meta["sector"].lower()
                ):
                    quote = dict(self._quotes[sym])
                    results.append(quote)
        return results

    def get_quote(self, symbol: str, refresh: bool = False) -> dict[str, Any] | None:
        """Get latest quote for a single symbol."""
        sym = self.normalize_symbol(symbol)
        if not sym:
            return None
        if refresh:
            self.refresh_quotes([sym])
        with self._lock:
            return dict(self._quotes[sym])

    def get_quotes(self, symbols: list[str] | None = None) -> dict[str, dict[str, Any]]:
        """Get latest quotes keyed by symbol."""
        with self._lock:
            if not symbols:
                return {k: dict(v) for k, v in self._quotes.items()}
            out = {}
            for raw in symbols:
                sym = self.normalize_symbol(raw)
                if sym and sym in self._quotes:
                    out[sym] = dict(self._quotes[sym])
            return out

    @staticmethod
    def normalize_symbol(symbol: str | None) -> str | None:
        if not symbol:
            return None
        cleaned = symbol.strip().upper()
        if cleaned in NSE_INSTRUMENTS:
            return cleaned
        if cleaned == "NIFTY50" or cleaned == "NIFTY":
            return "NIFTY 50"
        return None

    def refresh_quotes(self, symbols: list[str] | None = None) -> None:
        """Refresh quotes from Upstox v3 REST when configured & open, else yfinance."""
        target_symbols = [
            s for s in (symbols or list(NSE_INSTRUMENTS.keys())) if s in NSE_INSTRUMENTS
        ]
        if not target_symbols:
            return

        if Config.UPSTOX_ACCESS_TOKEN and self.is_nse_market_open():
            if self._fetch_upstox_rest_quotes(target_symbols):
                return

        self._hydrate_from_yfinance(target_symbols)

    def _fetch_upstox_rest_quotes(self, symbols: list[str]) -> bool:
        """Fetch quotes using Upstox API v3 Market Quote endpoint."""
        token = Config.UPSTOX_ACCESS_TOKEN
        if not token:
            return False

        keys = [NSE_INSTRUMENTS[s]["instrument_key"] for s in symbols]
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        url = f"{Config.UPSTOX_API_BASE}/market-quote/ohlc"
        try:
            resp = requests.get(
                url,
                headers=headers,
                params={"instrument_key": ",".join(keys), "interval": "1d"},
                timeout=4,
            )
            if resp.status_code != 200:
                with self._lock:
                    self._upstox_rest_ok = False
                    self._upstox_error = f"HTTP {resp.status_code}"
                return False

            payload = resp.json()
            data = payload.get("data") or {}
            if not data:
                return False

            key_to_symbol = {NSE_INSTRUMENTS[s]["instrument_key"]: s for s in symbols}
            now_str = self.now_ist().strftime("%Y-%m-%d %H:%M:%S IST")
            now_epoch = int(time.time())

            updated = 0
            with self._lock:
                for resp_key, item in data.items():
                    sym = key_to_symbol.get(resp_key)
                    if not sym:
                        # Upstox sometimes keys response as NSE_EQ:RELIANCE
                        token_part = resp_key.split(":")[-1].strip().upper()
                        sym = self.normalize_symbol(token_part)
                    if not sym or sym not in self._quotes:
                        continue

                    ltp = float(item.get("last_price") or 0)
                    ohlc = item.get("live_ohlc") or item.get("prev_ohlc") or {}
                    prev_close = float(
                        (item.get("prev_ohlc") or {}).get("close")
                        or self._quotes[sym]["prev_close"]
                    )
                    if ltp <= 0:
                        continue
                    change = round(ltp - prev_close, 2)
                    change_pct = round((change / prev_close) * 100, 2) if prev_close else 0.0
                    self._quotes[sym].update(
                        {
                            "ltp": round(ltp, 2),
                            "prev_close": round(prev_close, 2),
                            "open": round(float(ohlc.get("open") or ltp), 2),
                            "high": round(float(ohlc.get("high") or ltp), 2),
                            "low": round(float(ohlc.get("low") or ltp), 2),
                            "volume": int(ohlc.get("volume") or self._quotes[sym]["volume"]),
                            "change": change,
                            "change_pct": change_pct,
                            "timestamp": now_str,
                            "epoch": now_epoch,
                            "source": "Upstox API v3 REST",
                        }
                    )
                    updated += 1

                if updated > 0:
                    self._upstox_rest_ok = True
                    self._upstox_error = None
                    return True
        except Exception as exc:
            with self._lock:
                self._upstox_rest_ok = False
                self._upstox_error = str(exc)[:80]
        return False

    def _hydrate_from_yfinance(self, symbols: list[str]) -> None:
        """Fetch latest delayed/close quote via yfinance with caching so UI stays responsive."""
        now_ts = time.time()
        to_fetch = []
        with self._lock:
            for s in symbols:
                if now_ts - self._yf_hydrated_at.get(s, 0.0) > 120:
                    to_fetch.append(s)

        if not to_fetch:
            return

        try:
            import yfinance as yf
        except Exception:
            return

        now_str = self.now_ist().strftime("%Y-%m-%d %H:%M:%S IST")
        now_epoch = int(now_ts)
        # Fetch in small batch using yf.download to avoid slow sequential loops
        yf_tickers = [NSE_INSTRUMENTS[s]["yf_symbol"] for s in to_fetch]
        try:
            df = yf.download(
                tickers=" ".join(yf_tickers),
                period="5d",
                interval="1d",
                progress=False,
                threads=True,
                auto_adjust=False,
                timeout=6,
            )
            if df is None or df.empty:
                return

            with self._lock:
                for sym in to_fetch:
                    yf_sym = NSE_INSTRUMENTS[sym]["yf_symbol"]
                    self._yf_hydrated_at[sym] = now_ts
                    try:
                        if len(to_fetch) == 1:
                            sub = df
                        else:
                            if yf_sym not in df["Close"]:
                                continue
                            sub = df.xs(yf_sym, axis=1, level=1, drop_level=True)
                        sub = sub.dropna(subset=["Close"])
                        if sub.empty:
                            continue
                        last_row = sub.iloc[-1]
                        prev_row = sub.iloc[-2] if len(sub) >= 2 else last_row
                        ltp = float(last_row["Close"])
                        prev_close = float(prev_row["Close"])
                        if math.isnan(ltp) or ltp <= 0:
                            continue
                        if math.isnan(prev_close) or prev_close <= 0:
                            prev_close = ltp
                        change = round(ltp - prev_close, 2)
                        change_pct = round((change / prev_close) * 100, 2) if prev_close else 0.0
                        vol_raw = last_row.get("Volume", 0)
                        vol = int(vol_raw) if not math.isnan(float(vol_raw)) else 100000
                        self._quotes[sym].update(
                            {
                                "ltp": round(ltp, 2),
                                "prev_close": round(prev_close, 2),
                                "open": round(float(last_row.get("Open", ltp)), 2),
                                "high": round(float(last_row.get("High", ltp)), 2),
                                "low": round(float(last_row.get("Low", ltp)), 2),
                                "volume": max(vol, 1000),
                                "change": change,
                                "change_pct": change_pct,
                                "timestamp": now_str,
                                "epoch": now_epoch,
                                "source": "Yahoo Finance (Delayed/Last Close)",
                            }
                        )
                    except Exception:
                        continue
        except Exception:
            with self._lock:
                for sym in to_fetch:
                    self._yf_hydrated_at[sym] = now_ts

    def get_candles(self, symbol: str, timeframe: str = "5m") -> list[dict[str, Any]]:
        """Return OHLCV candles formatted for TradingView Lightweight Charts."""
        sym = self.normalize_symbol(symbol) or "RELIANCE"
        tf = timeframe if timeframe in TIMEFRAME_SECONDS else "5m"

        with self._lock:
            cached = self._candles_cache.get((sym, tf))
            if cached and len(cached) >= 20:
                return [dict(c) for c in cached]

        candles: list[dict[str, Any]] = []
        if Config.UPSTOX_ACCESS_TOKEN:
            candles = self._fetch_upstox_candles(sym, tf)

        if not candles:
            candles = self._fetch_yfinance_candles(sym, tf)

        if not candles:
            candles = self._generate_synthetic_candles(sym, tf, count=120)

        # Ensure strictly ascending unique timestamps and update quote LTP from latest candle
        candles = self._normalize_candles(candles)
        with self._lock:
            self._candles_cache[(sym, tf)] = candles
            if candles:
                last_c = candles[-1]
                quote = self._quotes[sym]
                # Keep quote coherent with chart close if quote is still at baseline
                if quote["source"] == "Reference Baseline":
                    prev_close = candles[0]["open"] if len(candles) < 2 else candles[-2]["close"]
                    ltp = last_c["close"]
                    change = round(ltp - prev_close, 2)
                    change_pct = round((change / prev_close) * 100, 2) if prev_close else 0.0
                    quote.update(
                        {
                            "ltp": ltp,
                            "prev_close": prev_close,
                            "change": change,
                            "change_pct": change_pct,
                        }
                    )
        return [dict(c) for c in candles]

    def _fetch_upstox_candles(self, symbol: str, timeframe: str) -> list[dict[str, Any]]:
        """Fetch historical/intraday candles from Upstox API v3 when token is configured."""
        token = Config.UPSTOX_ACCESS_TOKEN
        if not token:
            return []

        inst_key = NSE_INSTRUMENTS[symbol]["instrument_key"]
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        now_ist = self.now_ist()
        to_date = now_ist.strftime("%Y-%m-%d")
        from_date = (now_ist - timedelta(days=90 if timeframe == "1D" else 5)).strftime("%Y-%m-%d")

        if timeframe == "1D":
            url = f"{Config.UPSTOX_API_BASE}/historical-candle/{inst_key}/days/1/{to_date}/{from_date}"
        else:
            interval_num = timeframe.replace("m", "")
            url = f"{Config.UPSTOX_API_BASE}/historical-candle/intraday/{inst_key}/minutes/{interval_num}"

        try:
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code != 200:
                return []
            raw_candles = (resp.json().get("data") or {}).get("candles") or []
            parsed = []
            for row in raw_candles:
                # Upstox candle format: [timestamp_iso, open, high, low, close, volume, oi]
                dt = datetime.fromisoformat(str(row[0]))
                parsed.append(
                    {
                        "time": int(dt.timestamp()),
                        "open": round(float(row[1]), 2),
                        "high": round(float(row[2]), 2),
                        "low": round(float(row[3]), 2),
                        "close": round(float(row[4]), 2),
                        "volume": int(row[5] or 0),
                    }
                )
            return parsed
        except Exception:
            return []

    def _fetch_yfinance_candles(self, symbol: str, timeframe: str) -> list[dict[str, Any]]:
        """Fetch OHLCV candles from yfinance as fallback."""
        try:
            import yfinance as yf
        except Exception:
            return []

        yf_sym = NSE_INSTRUMENTS[symbol]["yf_symbol"]
        tf_map = {
            "1m": ("2d", "1m"),
            "5m": ("5d", "5m"),
            "15m": ("15d", "15m"),
            "1D": ("6mo", "1d"),
        }
        period, interval = tf_map.get(timeframe, ("5d", "5m"))
        try:
            ticker = yf.Ticker(yf_sym)
            df = ticker.history(period=period, interval=interval, auto_adjust=False)
            if df is None or df.empty:
                return []
            df = df.dropna(subset=["Open", "High", "Low", "Close"]).tail(120)
            candles = []
            for idx, row in df.iterrows():
                ts = int(idx.timestamp())
                candles.append(
                    {
                        "time": ts,
                        "open": round(float(row["Open"]), 2),
                        "high": round(float(row["High"]), 2),
                        "low": round(float(row["Low"]), 2),
                        "close": round(float(row["Close"]), 2),
                        "volume": int(row.get("Volume", 0) or 0),
                    }
                )
            return candles
        except Exception:
            return []

    def _generate_synthetic_candles(
        self, symbol: str, timeframe: str, count: int = 90
    ) -> list[dict[str, Any]]:
        """Generate realistic OHLCV candlestick history anchored to current reference quote."""
        meta = NSE_INSTRUMENTS[symbol]
        with self._lock:
            anchor = float(self._quotes[symbol]["ltp"])
        vol_pct = float(meta["volatility"])
        step_sec = TIMEFRAME_SECONDS[timeframe]

        now_epoch = int(time.time())
        aligned_now = (now_epoch // step_sec) * step_sec
        candles: list[dict[str, Any]] = []

        # Walk backward/forward smoothly so the last candle finishes near anchor
        price = anchor * (1.0 - self._rng.uniform(-0.012, 0.012))
        for i in range(count):
            bar_time = aligned_now - (count - 1 - i) * step_sec
            drift = (anchor - price) * 0.04
            shock = price * self._rng.gauss(0, vol_pct)
            open_p = price
            close_p = max(1.0, open_p + drift + shock)
            wick_up = abs(self._rng.gauss(0, vol_pct * 0.7)) * open_p
            wick_down = abs(self._rng.gauss(0, vol_pct * 0.7)) * open_p
            high_p = max(open_p, close_p) + wick_up
            low_p = max(0.5, min(open_p, close_p) - wick_down)
            volume = int(self._rng.randint(15000, 180000))
            candles.append(
                {
                    "time": bar_time,
                    "open": round(open_p, 2),
                    "high": round(high_p, 2),
                    "low": round(low_p, 2),
                    "close": round(close_p, 2),
                    "volume": volume,
                }
            )
            price = close_p

        if candles:
            candles[-1]["close"] = round(anchor, 2)
            candles[-1]["high"] = round(max(candles[-1]["high"], anchor), 2)
            candles[-1]["low"] = round(min(candles[-1]["low"], anchor), 2)
        return candles

    @staticmethod
    def _normalize_candles(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        dedup: dict[int, dict[str, Any]] = {}
        for c in candles:
            dedup[int(c["time"])] = c
        return [dedup[t] for t in sorted(dedup.keys())]

    def step_ticks_and_candles(self) -> dict[str, Any]:
        """Advance live prices (Upstox REST/WS when active, else fallback tick simulator)."""
        has_token = bool(Config.UPSTOX_ACCESS_TOKEN)
        market_open = self.is_nse_market_open()

        if has_token and market_open and not self._upstox_ws_connected:
            self._fetch_upstox_rest_quotes(list(NSE_INSTRUMENTS.keys()))

        now_ist = self.now_ist()
        now_str = now_ist.strftime("%Y-%m-%d %H:%M:%S IST")
        now_epoch = int(time.time())

        # If Upstox live stream or REST is NOT active, run fallback simulated tick generator
        use_simulator = not (has_token and market_open and (self._upstox_ws_connected or self._upstox_rest_ok))

        updated_quotes: dict[str, dict[str, Any]] = {}
        updated_candles: dict[str, dict[str, dict[str, Any]]] = {}

        with self._lock:
            for sym, meta in NSE_INSTRUMENTS.items():
                q = self._quotes[sym]
                if use_simulator:
                    vol = float(meta["volatility"]) * 0.45
                    prev_ltp = float(q["ltp"])
                    # Mean-reverting random walk around prev_close so prices stay realistic
                    mean_revert = (float(q["prev_close"]) - prev_ltp) * 0.008
                    delta = prev_ltp * self._rng.gauss(0, vol) + mean_revert
                    new_ltp = round(max(1.0, prev_ltp + delta), 2)
                    prev_close = float(q["prev_close"])
                    change = round(new_ltp - prev_close, 2)
                    change_pct = round((change / prev_close) * 100, 2) if prev_close else 0.0
                    q.update(
                        {
                            "ltp": new_ltp,
                            "high": round(max(float(q["high"]), new_ltp), 2),
                            "low": round(min(float(q["low"]), new_ltp), 2),
                            "volume": int(q["volume"]) + self._rng.randint(50, 1200),
                            "change": change,
                            "change_pct": change_pct,
                            "timestamp": now_str,
                            "epoch": now_epoch,
                            "source": "Fallback Simulator" if not market_open or not has_token else "Yahoo Finance + Fallback Ticks",
                        }
                    )

                updated_quotes[sym] = dict(q)

                # Update any cached candlestick series with the latest tick
                ltp = float(q["ltp"])
                for (c_sym, tf), bars in self._candles_cache.items():
                    if c_sym != sym or not bars:
                        continue
                    step_sec = TIMEFRAME_SECONDS[tf]
                    bucket_time = (now_epoch // step_sec) * step_sec
                    last_bar = bars[-1]
                    if bucket_time > last_bar["time"]:
                        new_bar = {
                            "time": bucket_time,
                            "open": last_bar["close"],
                            "high": max(last_bar["close"], ltp),
                            "low": min(last_bar["close"], ltp),
                            "close": ltp,
                            "volume": self._rng.randint(500, 5000),
                        }
                        bars.append(new_bar)
                        if len(bars) > 180:
                            del bars[0]
                    else:
                        last_bar["close"] = ltp
                        last_bar["high"] = round(max(last_bar["high"], ltp), 2)
                        last_bar["low"] = round(min(last_bar["low"], ltp), 2)
                        last_bar["volume"] = int(last_bar["volume"]) + self._rng.randint(25, 450)
                    updated_candles.setdefault(sym, {})[tf] = dict(bars[-1])

        return {
            "status": self.get_status(),
            "quotes": updated_quotes,
            "latest_candles": updated_candles,
        }

    def _start_upstox_websocket_listener(self) -> None:
        """Attempt authorized Upstox API v3 WebSocket connection when token & market are active."""
        if not Config.UPSTOX_ACCESS_TOKEN or not self.is_nse_market_open():
            return

        def _ws_worker() -> None:
            try:
                import websocket
            except Exception:
                return

            headers = {
                "Authorization": f"Bearer {Config.UPSTOX_ACCESS_TOKEN}",
                "Accept": "application/json",
            }
            try:
                auth_resp = requests.get(
                    f"{Config.UPSTOX_API_BASE}/market-data-feed/authorize",
                    headers=headers,
                    timeout=5,
                )
                if auth_resp.status_code != 200:
                    with self._lock:
                        self._upstox_ws_connected = False
                        self._upstox_error = f"WS auth HTTP {auth_resp.status_code}"
                    return
                wss_url = (auth_resp.json().get("data") or {}).get("authorized_redirect_uri")
                if not wss_url:
                    return

                def on_open(ws):
                    with self._lock:
                        self._upstox_ws_connected = True
                        self._upstox_error = None
                    sub_payload = {
                        "guid": "fintrack-feed-1",
                        "method": "sub",
                        "data": {
                            "mode": "ltpc",
                            "instrumentKeys": [
                                m["instrument_key"] for m in NSE_INSTRUMENTS.values()
                            ],
                        },
                    }
                    ws.send(json.dumps(sub_payload).encode("utf-8"))

                def on_message(ws, message):
                    # Handle JSON text frames if received; binary protobuf frames fall back to REST polling
                    if isinstance(message, str):
                        try:
                            data = json.loads(message)
                            feeds = data.get("feeds") or {}
                            if feeds:
                                now_str = self.now_ist().strftime("%Y-%m-%d %H:%M:%S IST")
                                with self._lock:
                                    key_map = {m["instrument_key"]: s for s, m in NSE_INSTRUMENTS.items()}
                                    for ikey, fdata in feeds.items():
                                        sym = key_map.get(ikey)
                                        ltpc = (fdata.get("ltpc") or {})
                                        ltp = ltpc.get("ltp")
                                        if sym and ltp:
                                            prev = self._quotes[sym]["prev_close"]
                                            ltp_f = round(float(ltp), 2)
                                            chg = round(ltp_f - prev, 2)
                                            chg_p = round((chg / prev) * 100, 2) if prev else 0.0
                                            self._quotes[sym].update(
                                                {
                                                    "ltp": ltp_f,
                                                    "change": chg,
                                                    "change_pct": chg_p,
                                                    "timestamp": now_str,
                                                    "epoch": int(time.time()),
                                                    "source": "Upstox API v3 WebSocket",
                                                }
                                            )
                        except Exception:
                            pass

                def on_error(ws, error):
                    with self._lock:
                        self._upstox_ws_connected = False
                        self._upstox_error = str(error)[:80]

                def on_close(ws, close_status_code, close_msg):
                    with self._lock:
                        self._upstox_ws_connected = False

                ws_app = websocket.WebSocketApp(
                    wss_url,
                    on_open=on_open,
                    on_message=on_message,
                    on_error=on_error,
                    on_close=on_close,
                )
                ws_app.run_forever(ping_interval=30, ping_timeout=10)
            except Exception as exc:
                with self._lock:
                    self._upstox_ws_connected = False
                    self._upstox_error = str(exc)[:80]

        t = threading.Thread(target=_ws_worker, daemon=True, name="upstox-ws-feed")
        t.start()

    def start_background_hydration(self) -> bool:
        """Start market data hydration once, returning whether it was started."""
        with self._lock:
            if self._hydration_started:
                return False
            self._hydration_started = True

        # Initial asynchronous hydration so server boots immediately
        def _initial_hydrate() -> None:
            self.refresh_quotes(list(NSE_INSTRUMENTS.keys()))
            self._start_upstox_websocket_listener()

        threading.Thread(target=_initial_hydrate, daemon=True, name="market-init").start()
        return True


market_service = MarketDataService()
