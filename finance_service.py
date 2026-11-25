from datetime import date, datetime
from typing import Any

from database import query_all
from trading_service import get_portfolio_summary


def months_between(today: date, target: date) -> int:
    """Compute at least 1 month remaining for monthly goal contribution planning."""
    if target <= today:
        return 1
    diff_months = (target.year - today.year) * 12 + (target.month - today.month)
    if target.day > today.day:
        diff_months += 1
    return max(1, diff_months)


def compute_goal_metrics(goal_row: dict[str, Any]) -> dict[str, Any]:
    """Enrich a goal record with progress percentage, remaining amount, and monthly required contribution."""
    target_amount = float(goal_row["target_amount"])
    saved_amount = float(goal_row["saved_amount"])
    remaining = max(0.0, round(target_amount - saved_amount, 2))
    progress_pct = min(100.0, round((saved_amount / target_amount) * 100, 1)) if target_amount > 0 else 0.0

    today = date.today()
    try:
        deadline_date = datetime.strptime(goal_row["deadline"], "%Y-%m-%d").date()
    except ValueError:
        deadline_date = today

    months_left = months_between(today, deadline_date)
    monthly_required = round(remaining / months_left, 2) if remaining > 0 else 0.0
    is_overdue = deadline_date < today and remaining > 0

    return {
        "id": goal_row["id"],
        "title": goal_row["title"],
        "target_amount": round(target_amount, 2),
        "saved_amount": round(saved_amount, 2),
        "remaining_amount": remaining,
        "progress_pct": progress_pct,
        "deadline": goal_row["deadline"],
        "months_left": months_left,
        "monthly_required": monthly_required,
        "is_completed": remaining <= 0,
        "is_overdue": is_overdue,
    }


def get_expense_analytics(user_id: int) -> dict[str, Any]:
    """Compute current-month spend, all-time total, and category breakdown strictly for user_id."""
    current_month = date.today().strftime("%Y-%m")
    expenses = [
        dict(r)
        for r in query_all(
            "SELECT id, title, category, amount, expense_date FROM expenses WHERE user_id = ? ORDER BY expense_date DESC, id DESC",
            (user_id,),
        )
    ]

    monthly_total = 0.0
    all_time_total = 0.0
    category_totals: dict[str, float] = {}

    for exp in expenses:
        amt = float(exp["amount"])
        all_time_total += amt
        if str(exp["expense_date"]).startswith(current_month):
            monthly_total += amt
        cat = exp["category"]
        category_totals[cat] = round(category_totals.get(cat, 0.0) + amt, 2)

    sorted_categories = sorted(category_totals.items(), key=lambda x: x[1], reverse=True)
    return {
        "expenses": expenses,
        "monthly_total": round(monthly_total, 2),
        "all_time_total": round(all_time_total, 2),
        "category_labels": [c[0] for c in sorted_categories],
        "category_values": [c[1] for c in sorted_categories],
        "category_breakdown": [
            {"category": c, "amount": v} for c, v in sorted_categories
        ],
    }


def get_goals_summary(user_id: int) -> dict[str, Any]:
    """Return enriched savings goals and overall goal progress percentage."""
    rows = query_all(
        "SELECT id, title, target_amount, saved_amount, deadline FROM goals WHERE user_id = ? ORDER BY deadline ASC, id DESC",
        (user_id,),
    )
    goals = [compute_goal_metrics(dict(r)) for r in rows]
    total_target = round(sum(g["target_amount"] for g in goals), 2)
    total_saved = round(sum(g["saved_amount"] for g in goals), 2)
    overall_pct = min(100.0, round((total_saved / total_target) * 100, 1)) if total_target > 0 else 0.0

    return {
        "goals": goals,
        "total_target": total_target,
        "total_saved": total_saved,
        "overall_progress_pct": overall_pct,
    }


def generate_risk_and_report(user_id: int) -> dict[str, Any]:
    """Run rule-based portfolio diversification and expense-to-savings risk checks."""
    portfolio = get_portfolio_summary(user_id)
    expense_stats = get_expense_analytics(user_id)
    goals_stats = get_goals_summary(user_id)

    holdings = portfolio["holdings"]
    holdings_val = portfolio["total_holdings_value"]
    total_port_val = portfolio["total_portfolio_value"]

    # Sector & single-stock concentration analysis
    sector_map: dict[str, float] = {}
    max_stock_weight = 0.0
    max_stock_symbol = None
    for h in holdings:
        weight = (h["current_value"] / holdings_val * 100) if holdings_val > 0 else 0.0
        if weight > max_stock_weight:
            max_stock_weight = round(weight, 1)
            max_stock_symbol = h["symbol"]
        sec = h["sector"]
        sector_map[sec] = round(sector_map.get(sec, 0.0) + h["current_value"], 2)

    sector_breakdown = []
    max_sector_weight = 0.0
    max_sector_name = None
    for sec, val in sorted(sector_map.items(), key=lambda x: x[1], reverse=True):
        pct = round((val / holdings_val) * 100, 1) if holdings_val > 0 else 0.0
        if pct > max_sector_weight:
            max_sector_weight = pct
            max_sector_name = sec
        sector_breakdown.append({"sector": sec, "value": val, "weight_pct": pct})

    cash_pct = round((portfolio["virtual_balance"] / total_port_val) * 100, 1) if total_port_val > 0 else 100.0
    equity_pct = round(100.0 - cash_pct, 1)

    # Rule-based diversification score (0 - 100)
    findings: list[dict[str, str]] = []
    score = 100

    if len(holdings) == 0:
        score = 40
        findings.append({
            "level": "info",
            "title": "No Active Equity Positions",
            "detail": "100% of paper capital is in virtual cash. Consider deploying capital across 4+ sectors in Live Market.",
        })
    else:
        if len(holdings) < 3:
            score -= 20
            findings.append({
                "level": "warning",
                "title": "Low Position Count",
                "detail": f"You hold only {len(holdings)} symbol(s). Aim for at least 4-6 uncorrelated stocks.",
            })
        if max_stock_weight > 40.0:
            score -= 25
            findings.append({
                "level": "danger",
                "title": "High Single-Stock Concentration",
                "detail": f"{max_stock_symbol} accounts for {max_stock_weight}% of your invested equity (recommended cap: <= 35%).",
            })
        elif max_stock_weight > 30.0:
            score -= 10
            findings.append({
                "level": "warning",
                "title": "Moderate Single-Stock Tilt",
                "detail": f"{max_stock_symbol} represents {max_stock_weight}% of invested equity.",
            })
        if max_sector_weight > 50.0 and len(holdings) >= 2:
            score -= 20
            findings.append({
                "level": "danger",
                "title": "Sector Concentration Risk",
                "detail": f"{max_sector_name} represents {max_sector_weight}% of equity exposure. Diversify into IT, FMCG, Pharma, or Auto.",
            })
        if cash_pct < 10.0:
            score -= 10
            findings.append({
                "level": "warning",
                "title": "Low Cash Buffer",
                "detail": f"Only {cash_pct}% virtual cash remaining. Keep 10-20% reserve for dip opportunities.",
            })

    # Expense-to-Savings ratio
    total_expenses = expense_stats["all_time_total"]
    total_saved = goals_stats["total_saved"]
    denom = total_expenses + total_saved
    expense_ratio = round((total_expenses / denom) * 100, 1) if denom > 0 else 0.0
    savings_ratio = round((total_saved / denom) * 100, 1) if denom > 0 else 0.0

    if denom == 0:
        findings.append({
            "level": "info",
            "title": "Personal Finance Baseline Pending",
            "detail": "Log your expenses and savings goals to unlock your personal expense-to-savings health ratio.",
        })
    elif expense_ratio > 75.0:
        score -= 15
        findings.append({
            "level": "danger",
            "title": "High Expense-to-Savings Ratio",
            "detail": f"Expenses represent {expense_ratio}% of tracked outflows vs {savings_ratio}% saved toward goals.",
        })
    elif savings_ratio >= 30.0:
        findings.append({
            "level": "success",
            "title": "Healthy Savings Discipline",
            "detail": f"You are directing {savings_ratio}% of tracked personal cashflow toward savings goals.",
        })

    if not findings:
        findings.append({
            "level": "success",
            "title": "Well-Balanced Portfolio",
            "detail": "Your holdings and cash buffer follow healthy diversification thresholds.",
        })

    score = max(0, min(100, score))
    risk_grade = (
        "Low Risk / Well Diversified"
        if score >= 80
        else "Moderate Risk"
        if score >= 55
        else "Elevated Concentration Risk"
    )

    return {
        "diversification_score": score,
        "risk_grade": risk_grade,
        "cash_pct": cash_pct,
        "equity_pct": equity_pct,
        "max_stock_symbol": max_stock_symbol,
        "max_stock_weight": max_stock_weight,
        "max_sector_name": max_sector_name,
        "max_sector_weight": max_sector_weight,
        "sector_breakdown": sector_breakdown,
        "expense_ratio": expense_ratio,
        "savings_ratio": savings_ratio,
        "total_expenses": total_expenses,
        "total_saved": total_saved,
        "findings": findings,
        "portfolio": portfolio,
        "expenses": expense_stats,
        "goals": goals_stats,
    }
