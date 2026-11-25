from flask import Blueprint, jsonify, render_template, request, session

from config import NSE_INSTRUMENTS
from database import atomic_transaction, query_all, query_one
from market_service import TIMEFRAME_SECONDS, market_service
from routes.auth import login_required
from trading_service import ensure_paper_account

market_bp = Blueprint("market", __name__)


@market_bp.route("/market")
@login_required
def terminal():
    user_id = session["user_id"]
    requested_symbol = request.args.get("symbol", "RELIANCE")
    symbol = market_service.normalize_symbol(requested_symbol) or "RELIANCE"
    quote = market_service.get_quote(symbol)
    virtual_balance = ensure_paper_account(user_id)

    holding = query_one(
        "SELECT quantity, avg_buy_price FROM paper_holdings WHERE user_id = ? AND symbol = ?",
        (user_id, symbol),
    )
    in_watchlist = (
        query_one(
            "SELECT id FROM watchlist WHERE user_id = ? AND symbol = ?",
            (user_id, symbol),
        )
        is not None
    )

    instruments = market_service.list_instruments()
    return render_template(
        "market.html",
        active_page="market",
        selected_symbol=symbol,
        quote=quote,
        virtual_balance=virtual_balance,
        holding=dict(holding) if holding else None,
        in_watchlist=in_watchlist,
        instruments=instruments,
        market_status=market_service.get_status(),
    )


@market_bp.route("/watchlist")
@login_required
def watchlist_page():
    user_id = session["user_id"]
    rows = query_all(
        "SELECT id, symbol, instrument_key, exchange FROM watchlist WHERE user_id = ? ORDER BY id ASC",
        (user_id,),
    )
    quotes = market_service.get_quotes([r["symbol"] for r in rows])
    items = []
    watched_symbols = set()
    for r in rows:
        watched_symbols.add(r["symbol"])
        q = quotes.get(r["symbol"]) or {
            "symbol": r["symbol"],
            "name": r["symbol"],
            "exchange": r["exchange"],
            "instrument_key": r["instrument_key"],
            "ltp": 0.0,
            "change": 0.0,
            "change_pct": 0.0,
            "sector": "NSE",
        }
        items.append(q)

    all_instruments = market_service.list_instruments()
    return render_template(
        "watchlist.html",
        active_page="watchlist",
        watchlist_items=items,
        watched_symbols=watched_symbols,
        all_instruments=all_instruments,
        market_status=market_service.get_status(),
    )


@market_bp.route("/api/market/status", methods=["GET"])
@login_required
def api_market_status():
    return jsonify(market_service.get_status())


@market_bp.route("/api/market/search", methods=["GET"])
@login_required
def api_market_search():
    q = request.args.get("q", "")
    return jsonify(
        {
            "instruments": market_service.list_instruments(q),
            "status": market_service.get_status(),
        }
    )


@market_bp.route("/api/market/quote/<path:symbol>", methods=["GET"])
@login_required
def api_market_quote(symbol: str):
    quote = market_service.get_quote(symbol)
    if not quote:
        return jsonify({"error": "Unknown NSE symbol."}), 404
    return jsonify({"quote": quote, "status": market_service.get_status()})


@market_bp.route("/api/market/candles/<path:symbol>", methods=["GET"])
@login_required
def api_market_candles(symbol: str):
    norm = market_service.normalize_symbol(symbol)
    if not norm:
        return jsonify({"error": "Unknown NSE symbol."}), 404
    timeframe = request.args.get("timeframe", "5m")
    if timeframe not in TIMEFRAME_SECONDS:
        timeframe = "5m"

    candles = market_service.get_candles(norm, timeframe)
    quote = market_service.get_quote(norm)
    user_id = session["user_id"]
    holding = query_one(
        "SELECT quantity, avg_buy_price FROM paper_holdings WHERE user_id = ? AND symbol = ?",
        (user_id, norm),
    )
    in_watchlist = (
        query_one(
            "SELECT id FROM watchlist WHERE user_id = ? AND symbol = ?",
            (user_id, norm),
        )
        is not None
    )

    return jsonify(
        {
            "symbol": norm,
            "timeframe": timeframe,
            "candles": candles,
            "quote": quote,
            "holding": dict(holding) if holding else None,
            "in_watchlist": in_watchlist,
            "status": market_service.get_status(),
        }
    )


@market_bp.route("/api/watchlist", methods=["GET"])
@login_required
def api_watchlist_list():
    user_id = session["user_id"]
    rows = query_all(
        "SELECT symbol, instrument_key, exchange FROM watchlist WHERE user_id = ? ORDER BY id ASC",
        (user_id,),
    )
    quotes = market_service.get_quotes([r["symbol"] for r in rows])
    return jsonify(
        {
            "watchlist": [quotes[r["symbol"]] for r in rows if r["symbol"] in quotes],
            "status": market_service.get_status(),
        }
    )


@market_bp.route("/api/watchlist", methods=["POST"])
@login_required
def api_watchlist_add():
    user_id = session["user_id"]
    payload = request.get_json(silent=True) or {}
    sym = market_service.normalize_symbol(payload.get("symbol"))
    if not sym or sym not in NSE_INSTRUMENTS:
        return jsonify({"error": "Invalid NSE symbol."}), 400

    meta = NSE_INSTRUMENTS[sym]
    with atomic_transaction() as tx:
        tx.execute(
            "INSERT OR IGNORE INTO watchlist (user_id, symbol, instrument_key, exchange) VALUES (?, ?, ?, ?)",
            (user_id, meta["symbol"], meta["instrument_key"], meta["exchange"]),
        )
    return jsonify({"ok": True, "symbol": sym, "quote": market_service.get_quote(sym)})


@market_bp.route("/api/watchlist/<path:symbol>", methods=["DELETE"])
@login_required
def api_watchlist_remove(symbol: str):
    user_id = session["user_id"]
    sym = market_service.normalize_symbol(symbol) or symbol.strip().upper()
    with atomic_transaction() as tx:
        tx.execute(
            "DELETE FROM watchlist WHERE user_id = ? AND symbol = ?",
            (user_id, sym),
        )
    return jsonify({"ok": True, "symbol": sym})
