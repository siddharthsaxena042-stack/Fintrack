import csv
import io
from datetime import date, datetime
from flask import Blueprint, Response, flash, jsonify, redirect, render_template, request, session, url_for

from config import EXPENSE_CATEGORIES
from database import atomic_transaction, query_all, query_one
from finance_service import generate_risk_and_report, get_expense_analytics, get_goals_summary
from market_service import market_service
from routes.auth import login_required

finance_bp = Blueprint("finance", __name__)


@finance_bp.route("/expenses", methods=["GET", "POST"])
@login_required
def expenses_page():
    user_id = session["user_id"]
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        category = (request.form.get("category") or "Other").strip()
        amount_raw = request.form.get("amount", "")
        expense_date = (request.form.get("expense_date") or date.today().isoformat()).strip()

        if len(title) < 1:
            flash("Expense title is required.", "danger")
            return redirect(url_for("finance.expenses_page"))
        if category not in EXPENSE_CATEGORIES:
            category = "Other"

        try:
            amount = round(float(amount_raw), 2)
        except (TypeError, ValueError):
            amount = 0.0

        if amount <= 0:
            flash("Expense amount must be greater than zero.", "danger")
            return redirect(url_for("finance.expenses_page"))

        try:
            datetime.strptime(expense_date, "%Y-%m-%d")
        except ValueError:
            expense_date = date.today().isoformat()

        with atomic_transaction() as tx:
            tx.execute(
                "INSERT INTO expenses (user_id, title, category, amount, expense_date) VALUES (?, ?, ?, ?, ?)",
                (user_id, title, category, amount, expense_date),
            )
        flash(f"Added expense '{title}' (₹{amount:,.2f}).", "success")
        return redirect(url_for("finance.expenses_page"))

    analytics = get_expense_analytics(user_id)
    return render_template(
        "expenses.html",
        active_page="expenses",
        categories=EXPENSE_CATEGORIES,
        today_iso=date.today().isoformat(),
        analytics=analytics,
        market_status=market_service.get_status(),
    )


@finance_bp.route("/expenses/<int:expense_id>/delete", methods=["POST"])
@login_required
def delete_expense(expense_id: int):
    user_id = session["user_id"]
    with atomic_transaction() as tx:
        cur = tx.execute(
            "DELETE FROM expenses WHERE id = ? AND user_id = ?",
            (expense_id, user_id),
        )
    if cur.rowcount > 0:
        flash("Expense deleted.", "info")
    else:
        flash("Expense not found.", "warning")
    return redirect(url_for("finance.expenses_page"))


@finance_bp.route("/api/expenses/<int:expense_id>", methods=["DELETE"])
@login_required
def api_delete_expense(expense_id: int):
    user_id = session["user_id"]
    with atomic_transaction() as tx:
        cur = tx.execute(
            "DELETE FROM expenses WHERE id = ? AND user_id = ?",
            (expense_id, user_id),
        )
    if cur.rowcount == 0:
        return jsonify({"error": "Expense not found."}), 404
    return jsonify({"ok": True})


@finance_bp.route("/expenses/export", methods=["GET"])
@login_required
def export_expenses_csv():
    user_id = session["user_id"]
    rows = query_all(
        "SELECT id, title, category, amount, expense_date FROM expenses WHERE user_id = ? ORDER BY expense_date DESC, id DESC",
        (user_id,),
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Title", "Category", "Amount (INR)", "Date"])
    for r in rows:
        writer.writerow([r["id"], r["title"], r["category"], f"{float(r['amount']):.2f}", r["expense_date"]])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=fintrack_expenses_{date.today().isoformat()}.csv"},
    )


@finance_bp.route("/goals", methods=["GET", "POST"])
@login_required
def goals_page():
    user_id = session["user_id"]
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        target_raw = request.form.get("target_amount", "")
        saved_raw = request.form.get("saved_amount", "0")
        deadline = (request.form.get("deadline") or "").strip()

        if len(title) < 1:
            flash("Goal title is required.", "danger")
            return redirect(url_for("finance.goals_page"))

        try:
            target_amount = round(float(target_raw), 2)
            saved_amount = round(float(saved_raw or 0), 2)
        except (TypeError, ValueError):
            target_amount, saved_amount = 0.0, 0.0

        if target_amount <= 0:
            flash("Target amount must be greater than zero.", "danger")
            return redirect(url_for("finance.goals_page"))
        if saved_amount < 0:
            flash("Initial saved amount cannot be negative.", "danger")
            return redirect(url_for("finance.goals_page"))

        try:
            datetime.strptime(deadline, "%Y-%m-%d")
        except ValueError:
            flash("Please provide a valid deadline date (YYYY-MM-DD).", "danger")
            return redirect(url_for("finance.goals_page"))

        with atomic_transaction() as tx:
            tx.execute(
                "INSERT INTO goals (user_id, title, target_amount, saved_amount, deadline) VALUES (?, ?, ?, ?, ?)",
                (user_id, title, target_amount, saved_amount, deadline),
            )
            tx.execute(
                "INSERT INTO notifications (user_id, message) VALUES (?, ?)",
                (user_id, f"New savings goal created: '{title}' targeting ₹{target_amount:,.2f} by {deadline}."),
            )
        flash(f"Savings goal '{title}' created!", "success")
        return redirect(url_for("finance.goals_page"))

    summary = get_goals_summary(user_id)
    return render_template(
        "goals.html",
        active_page="goals",
        summary=summary,
        today_iso=date.today().isoformat(),
        market_status=market_service.get_status(),
    )


@finance_bp.route("/goals/<int:goal_id>/contribute", methods=["POST"])
@login_required
def contribute_goal(goal_id: int):
    user_id = session["user_id"]
    amount_raw = request.form.get("amount", "")
    try:
        amount = round(float(amount_raw), 2)
    except (TypeError, ValueError):
        amount = 0.0

    if amount <= 0:
        flash("Contribution amount must be greater than zero.", "danger")
        return redirect(url_for("finance.goals_page"))

    with atomic_transaction() as tx:
        goal = query_one(
            "SELECT id, title, target_amount, saved_amount FROM goals WHERE id = ? AND user_id = ?",
            (goal_id, user_id),
            conn=tx,
        )
        if goal is None:
            flash("Savings goal not found.", "warning")
            return redirect(url_for("finance.goals_page"))

        new_saved = round(float(goal["saved_amount"]) + amount, 2)
        tx.execute(
            "UPDATE goals SET saved_amount = ? WHERE id = ? AND user_id = ?",
            (new_saved, goal_id, user_id),
        )
        if new_saved >= float(goal["target_amount"]):
            tx.execute(
                "INSERT INTO notifications (user_id, message) VALUES (?, ?)",
                (user_id, f"Goal achieved! '{goal['title']}' reached ₹{new_saved:,.2f}."),
            )

    flash(f"Added ₹{amount:,.2f} toward '{goal['title']}'.", "success")
    return redirect(url_for("finance.goals_page"))


@finance_bp.route("/goals/<int:goal_id>/delete", methods=["POST"])
@login_required
def delete_goal(goal_id: int):
    user_id = session["user_id"]
    with atomic_transaction() as tx:
        cur = tx.execute(
            "DELETE FROM goals WHERE id = ? AND user_id = ?",
            (goal_id, user_id),
        )
    if cur.rowcount > 0:
        flash("Savings goal removed.", "info")
    else:
        flash("Savings goal not found.", "warning")
    return redirect(url_for("finance.goals_page"))


@finance_bp.route("/reports")
@login_required
def reports_page():
    user_id = session["user_id"]
    report = generate_risk_and_report(user_id)
    return render_template(
        "reports.html",
        active_page="reports",
        report=report,
        market_status=market_service.get_status(),
    )


@finance_bp.route("/reports/download", methods=["GET"])
@login_required
def download_report():
    user_id = session["user_id"]
    fmt = (request.args.get("format") or "csv").lower()
    report = generate_risk_and_report(user_id)
    portfolio = report["portfolio"]
    user_name = session.get("user_name", "FinTrack User")

    if fmt == "txt":
        lines = [
            "============================================================",
            "FINTRACK - PERSONAL FINANCE & PORTFOLIO RISK SUMMARY REPORT",
            "============================================================",
            f"Account Holder : {user_name}",
            f"Generated On   : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "--- PAPER PORTFOLIO SUMMARY ---",
            f"Virtual Cash Balance : INR {portfolio['virtual_balance']:,.2f}",
            f"Invested Equity      : INR {portfolio['total_invested']:,.2f}",
            f"Holdings Market Val  : INR {portfolio['total_holdings_value']:,.2f}",
            f"Total Portfolio Val  : INR {portfolio['total_portfolio_value']:,.2f}",
            f"Unrealized P&L       : INR {portfolio['total_unrealized_pnl']:,.2f}",
            f"Realized P&L         : INR {portfolio['total_realized_pnl']:,.2f}",
            "",
            "--- RISK & DIVERSIFICATION ---",
            f"Diversification Score: {report['diversification_score']}/100 ({report['risk_grade']})",
            f"Cash vs Equity Split : {report['cash_pct']}% Cash / {report['equity_pct']}% Equity",
            f"Expense-to-Savings   : {report['expense_ratio']}% Expenses / {report['savings_ratio']}% Saved",
            "",
            "--- FINDINGS ---",
        ]
        for f in report["findings"]:
            lines.append(f"[{f['level'].upper()}] {f['title']}: {f['detail']}")
        lines.append("")
        lines.append("--- HOLDINGS ---")
        if portfolio["holdings"]:
            for h in portfolio["holdings"]:
                lines.append(
                    f"{h['symbol']:<12} Qty:{h['quantity']:<5} Avg:INR {h['avg_buy_price']:,.2f} LTP:INR {h['ltp']:,.2f} P&L:INR {h['unrealized_pnl']:,.2f}"
                )
        else:
            lines.append("No active equity holdings.")

        return Response(
            "\n".join(lines),
            mimetype="text/plain",
            headers={"Content-Disposition": f"attachment; filename=fintrack_summary_{date.today().isoformat()}.txt"},
        )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Section", "Metric", "Value"])
    writer.writerow(["Account", "Holder", user_name])
    writer.writerow(["Portfolio", "Virtual Cash Balance (INR)", f"{portfolio['virtual_balance']:.2f}"])
    writer.writerow(["Portfolio", "Total Holdings Value (INR)", f"{portfolio['total_holdings_value']:.2f}"])
    writer.writerow(["Portfolio", "Total Portfolio Value (INR)", f"{portfolio['total_portfolio_value']:.2f}"])
    writer.writerow(["Portfolio", "Unrealized P&L (INR)", f"{portfolio['total_unrealized_pnl']:.2f}"])
    writer.writerow(["Portfolio", "Realized P&L (INR)", f"{portfolio['total_realized_pnl']:.2f}"])
    writer.writerow(["Risk", "Diversification Score", f"{report['diversification_score']}/100"])
    writer.writerow(["Risk", "Risk Grade", report["risk_grade"]])
    writer.writerow(["Personal Finance", "Monthly Expenses (INR)", f"{report['expenses']['monthly_total']:.2f}"])
    writer.writerow(["Personal Finance", "All-time Expenses (INR)", f"{report['total_expenses']:.2f}"])
    writer.writerow(["Personal Finance", "Total Saved in Goals (INR)", f"{report['total_saved']:.2f}"])
    writer.writerow(["Personal Finance", "Expense Ratio (%)", f"{report['expense_ratio']:.1f}"])
    writer.writerow(["Personal Finance", "Savings Ratio (%)", f"{report['savings_ratio']:.1f}"])
    writer.writerow([])
    writer.writerow(["Holdings Symbol", "Sector", "Quantity", "Avg Buy Price", "LTP", "Current Value", "Unrealized P&L"])
    for h in portfolio["holdings"]:
        writer.writerow([
            h["symbol"],
            h["sector"],
            h["quantity"],
            f"{h['avg_buy_price']:.2f}",
            f"{h['ltp']:.2f}",
            f"{h['current_value']:.2f}",
            f"{h['unrealized_pnl']:.2f}",
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=fintrack_report_{date.today().isoformat()}.csv"},
    )
