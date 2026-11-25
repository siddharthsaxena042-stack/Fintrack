from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from database import atomic_transaction, query_all, query_one
from finance_service import generate_risk_and_report, get_expense_analytics, get_goals_summary
from market_service import market_service
from routes.auth import login_required
from trading_service import get_portfolio_summary, get_trade_history

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("main.dashboard"))
    return redirect(url_for("auth.login"))


@main_bp.route("/dashboard")
@login_required
def dashboard():
    user_id = session["user_id"]
    portfolio = get_portfolio_summary(user_id)
    expenses = get_expense_analytics(user_id)
    goals = get_goals_summary(user_id)
    recent_trades = get_trade_history(user_id, limit=6)

    watchlist_rows = query_all(
        "SELECT symbol, instrument_key, exchange FROM watchlist WHERE user_id = ? ORDER BY id ASC",
        (user_id,),
    )
    quotes = market_service.get_quotes([r["symbol"] for r in watchlist_rows])
    watchlist_items = []
    for r in watchlist_rows:
        q = quotes.get(r["symbol"])
        if q:
            watchlist_items.append(q)

    return render_template(
        "dashboard.html",
        active_page="dashboard",
        portfolio=portfolio,
        monthly_expenses=expenses["monthly_total"],
        expense_categories=expenses["category_breakdown"][:4],
        goals_summary=goals,
        watchlist_items=watchlist_items,
        recent_trades=recent_trades,
        market_status=market_service.get_status(),
    )


@main_bp.route("/api/notifications", methods=["GET"])
@login_required
def api_notifications():
    user_id = session["user_id"]
    rows = query_all(
        "SELECT id, message, is_read, created_at FROM notifications WHERE user_id = ? ORDER BY id DESC LIMIT 20",
        (user_id,),
    )
    unread_row = query_one(
        "SELECT COUNT(*) AS cnt FROM notifications WHERE user_id = ? AND is_read = 0",
        (user_id,),
    )
    return jsonify(
        {
            "notifications": [dict(r) for r in rows],
            "unread_count": int(unread_row["cnt"]) if unread_row else 0,
        }
    )


@main_bp.route("/api/notifications/read", methods=["POST"])
@login_required
def api_notifications_read():
    user_id = session["user_id"]
    payload = request.get_json(silent=True) or {}
    notif_id = payload.get("id")

    with atomic_transaction() as tx:
        if notif_id:
            tx.execute(
                "UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?",
                (int(notif_id), user_id),
            )
        else:
            tx.execute(
                "UPDATE notifications SET is_read = 1 WHERE user_id = ?",
                (user_id,),
            )

    return jsonify({"ok": True})


@main_bp.route("/api/ai-assistant", methods=["POST"])
@login_required
def api_ai_assistant():
    """Data-driven Personal Finance & Portfolio Assistant grounded in the user's live SQLite records."""
    user_id = session["user_id"]
    payload = request.get_json(silent=True) or {}
    prompt = (payload.get("prompt") or "").strip().lower()

    report = generate_risk_and_report(user_id)
    portfolio = report["portfolio"]
    expenses = report["expenses"]
    goals = report["goals"]

    cash = portfolio["virtual_balance"]
    port_val = portfolio["total_portfolio_value"]
    unrealized = portfolio["total_unrealized_pnl"]
    realized = portfolio["total_realized_pnl"]
    monthly_exp = expenses["monthly_total"]
    top_cat = expenses["category_breakdown"][0] if expenses["category_breakdown"] else None

    if any(k in prompt for k in ("risk", "diversif", "sector", "concentrat", "portfolio")):
        lines = [
            f"Your current Diversification Score is {report['diversification_score']}/100 ({report['risk_grade']}).",
            f"Allocation: {report['equity_pct']}% Equity (₹{portfolio['total_holdings_value']:,.2f}) vs {report['cash_pct']}% Virtual Cash (₹{cash:,.2f}).",
        ]
        if report["max_stock_symbol"]:
            lines.append(
                f"Largest single position: {report['max_stock_symbol']} ({report['max_stock_weight']}% of invested equity)."
            )
        for f in report["findings"][:2]:
            lines.append(f"• {f['title']}: {f['detail']}")
        reply = "\n".join(lines)
    elif any(k in prompt for k in ("expense", "spend", "budget", "save", "saving", "goal")):
        lines = [
            f"This month's recorded expenses total ₹{monthly_exp:,.2f} (All-time: ₹{expenses['all_time_total']:,.2f}).",
        ]
        if top_cat:
            lines.append(f"Highest spending category: {top_cat['category']} at ₹{top_cat['amount']:,.2f}.")
        lines.append(
            f"Goals progress: ₹{goals['total_saved']:,.2f} saved out of ₹{goals['total_target']:,.2f} ({goals['overall_progress_pct']}%)."
        )
        if goals["goals"]:
            urgent = goals["goals"][0]
            lines.append(
                f"Priority goal '{urgent['title']}': requires ₹{urgent['monthly_required']:,.2f}/month over {urgent['months_left']} month(s) to hit deadline {urgent['deadline']}."
            )
        lines.append(
            f"Expense-to-Savings ratio: {report['expense_ratio']}% spent vs {report['savings_ratio']}% saved."
        )
        reply = "\n".join(lines)
    elif any(k in prompt for k in ("trade", "buy", "sell", "stock", "market", "pnl", "profit")):
        status = market_service.get_status()
        lines = [
            f"Market feed status: {status['badge']} ({status['source']}).",
            f"Paper Trading Summary: Total Portfolio ₹{port_val:,.2f} | Cash ₹{cash:,.2f}.",
            f"Unrealized P&L: ₹{unrealized:,.2f} | Realized P&L: ₹{realized:,.2f}.",
            "Tip: Keep position sizes under 25-30% of capital and verify candlestick trends across 5m and 1D timeframes before entering.",
        ]
        reply = "\n".join(lines)
    else:
        lines = [
            f"Here is your live FinTrack snapshot:",
            f"• Paper Portfolio Value: ₹{port_val:,.2f} (Cash: ₹{cash:,.2f}, Unrealized P&L: ₹{unrealized:,.2f})",
            f"• Monthly Expenses: ₹{monthly_exp:,.2f}" + (f" (Top: {top_cat['category']})" if top_cat else ""),
            f"• Savings Goals: {goals['overall_progress_pct']}% funded across {len(goals['goals'])} goal(s)",
            f"• Risk Grade: {report['risk_grade']} ({report['diversification_score']}/100)",
            "Ask me about 'portfolio risk', 'monthly expenses & goals', or 'trading P&L'.",
        ]
        reply = "\n".join(lines)

    return jsonify({"reply": reply})
