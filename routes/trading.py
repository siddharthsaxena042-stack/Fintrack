from flask import Blueprint, jsonify, render_template, request, session

from market_service import market_service
from routes.auth import login_required
from trading_service import (
    TradeValidationError,
    execute_paper_order,
    get_portfolio_summary,
    get_trade_history,
)

trading_bp = Blueprint("trading", __name__)


@trading_bp.route("/portfolio")
@login_required
def portfolio_page():
    user_id = session["user_id"]
    summary = get_portfolio_summary(user_id)
    trades = get_trade_history(user_id, limit=100)
    return render_template(
        "portfolio.html",
        active_page="portfolio",
        portfolio=summary,
        trades=trades,
        market_status=market_service.get_status(),
    )


@trading_bp.route("/api/portfolio", methods=["GET"])
@login_required
def api_portfolio():
    user_id = session["user_id"]
    summary = get_portfolio_summary(user_id)
    trades = get_trade_history(user_id, limit=50)
    return jsonify({"portfolio": summary, "trades": trades})


@trading_bp.route("/api/trade/order", methods=["POST"])
@login_required
def api_place_order():
    user_id = session["user_id"]
    payload = request.get_json(silent=True) or {}
    symbol = payload.get("symbol", "")
    side = payload.get("side", "")
    quantity = payload.get("quantity", 0)

    try:
        result = execute_paper_order(user_id, symbol, side, quantity)
    except TradeValidationError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Order execution failed and was rolled back: {exc}"}), 500

    portfolio = get_portfolio_summary(user_id)
    return jsonify({"ok": True, "order": result, "portfolio": portfolio})
