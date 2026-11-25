from typing import Any

from config import Config, NSE_INSTRUMENTS
from database import atomic_transaction, get_db, query_all, query_one
from market_service import market_service


class TradeValidationError(ValueError):
    """Raised when an order fails business validation."""


def ensure_paper_account(user_id: int) -> float:
    """Ensure the user has a paper trading account and return its virtual balance."""
    row = query_one(
        "SELECT virtual_balance FROM paper_accounts WHERE user_id = ?",
        (user_id,),
    )
    if row is not None:
        return round(float(row["virtual_balance"]), 2)

    with atomic_transaction() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO paper_accounts (user_id, virtual_balance) VALUES (?, ?)",
            (user_id, Config.DEFAULT_VIRTUAL_BALANCE),
        )
    row = query_one(
        "SELECT virtual_balance FROM paper_accounts WHERE user_id = ?",
        (user_id,),
    )
    return round(float(row["virtual_balance"]), 2) if row else Config.DEFAULT_VIRTUAL_BALANCE


def execute_paper_order(user_id: int, raw_symbol: str, side: str, raw_quantity: Any) -> dict[str, Any]:
    """Execute a BUY or SELL paper trade inside a single ACID SQLite transaction."""
    symbol = market_service.normalize_symbol(raw_symbol)
    if not symbol or symbol not in NSE_INSTRUMENTS:
        raise TradeValidationError("Invalid or unsupported NSE instrument symbol.")

    side_clean = (side or "").strip().upper()
    if side_clean not in ("BUY", "SELL"):
        raise TradeValidationError("Order side must be BUY or SELL.")

    try:
        quantity = int(raw_quantity)
    except (TypeError, ValueError):
        raise TradeValidationError("Quantity must be a positive whole number.")

    if quantity <= 0:
        raise TradeValidationError("Quantity must be greater than zero.")
    if quantity > 100000:
        raise TradeValidationError("Maximum single order quantity is 1,00,000 units.")

    quote = market_service.get_quote(symbol)
    if not quote or float(quote["ltp"]) <= 0:
        raise TradeValidationError("Live market price unavailable for this symbol.")

    execution_price = round(float(quote["ltp"]), 2)
    order_value = round(execution_price * quantity, 2)
    ensure_paper_account(user_id)

    conn = get_db()
    realized_pnl = 0.0

    with atomic_transaction(conn) as tx:
        acct = query_one(
            "SELECT virtual_balance FROM paper_accounts WHERE user_id = ?",
            (user_id,),
            conn=tx,
        )
        if acct is None:
            raise TradeValidationError("Paper trading account not found.")

        balance = float(acct["virtual_balance"])

        if side_clean == "BUY":
            if balance + 1e-6 < order_value:
                raise TradeValidationError(
                    f"Insufficient virtual balance. Required ₹{order_value:,.2f}, available ₹{balance:,.2f}."
                )

            new_balance = round(balance - order_value, 2)
            tx.execute(
                "UPDATE paper_accounts SET virtual_balance = ? WHERE user_id = ?",
                (new_balance, user_id),
            )

            holding = query_one(
                "SELECT id, quantity, avg_buy_price FROM paper_holdings WHERE user_id = ? AND symbol = ?",
                (user_id, symbol),
                conn=tx,
            )
            if holding is None:
                tx.execute(
                    "INSERT INTO paper_holdings (user_id, symbol, quantity, avg_buy_price) VALUES (?, ?, ?, ?)",
                    (user_id, symbol, quantity, execution_price),
                )
            else:
                old_qty = int(holding["quantity"])
                old_avg = float(holding["avg_buy_price"])
                new_qty = old_qty + quantity
                new_avg = round(((old_qty * old_avg) + order_value) / new_qty, 2)
                tx.execute(
                    "UPDATE paper_holdings SET quantity = ?, avg_buy_price = ? WHERE id = ? AND user_id = ?",
                    (new_qty, new_avg, holding["id"], user_id),
                )

            tx.execute(
                """
                INSERT INTO paper_trade_history (user_id, symbol, side, quantity, execution_price, realized_pnl)
                VALUES (?, ?, 'BUY', ?, ?, 0.0)
                """,
                (user_id, symbol, quantity, execution_price),
            )

            notif_msg = (
                f"BUY executed: {quantity} {symbol} @ ₹{execution_price:,.2f} "
                f"(Total ₹{order_value:,.2f}). Remaining cash: ₹{new_balance:,.2f}."
            )
            tx.execute(
                "INSERT INTO notifications (user_id, message) VALUES (?, ?)",
                (user_id, notif_msg),
            )

        else:  # SELL
            holding = query_one(
                "SELECT id, quantity, avg_buy_price FROM paper_holdings WHERE user_id = ? AND symbol = ?",
                (user_id, symbol),
                conn=tx,
            )
            if holding is None or int(holding["quantity"]) < quantity:
                owned = int(holding["quantity"]) if holding else 0
                raise TradeValidationError(
                    f"Insufficient {symbol} holdings. Requested {quantity}, owned {owned}."
                )

            old_qty = int(holding["quantity"])
            avg_buy = float(holding["avg_buy_price"])
            realized_pnl = round((execution_price - avg_buy) * quantity, 2)
            new_balance = round(balance + order_value, 2)

            tx.execute(
                "UPDATE paper_accounts SET virtual_balance = ? WHERE user_id = ?",
                (new_balance, user_id),
            )

            remaining_qty = old_qty - quantity
            if remaining_qty == 0:
                tx.execute(
                    "DELETE FROM paper_holdings WHERE id = ? AND user_id = ?",
                    (holding["id"], user_id),
                )
            else:
                tx.execute(
                    "UPDATE paper_holdings SET quantity = ? WHERE id = ? AND user_id = ?",
                    (remaining_qty, holding["id"], user_id),
                )

            tx.execute(
                """
                INSERT INTO paper_trade_history (user_id, symbol, side, quantity, execution_price, realized_pnl)
                VALUES (?, ?, 'SELL', ?, ?, ?)
                """,
                (user_id, symbol, quantity, execution_price, realized_pnl),
            )

            pnl_sign = "+" if realized_pnl >= 0 else "-"
            notif_msg = (
                f"SELL executed: {quantity} {symbol} @ ₹{execution_price:,.2f} "
                f"(Realized P&L: {pnl_sign}₹{abs(realized_pnl):,.2f}). Cash: ₹{new_balance:,.2f}."
            )
            tx.execute(
                "INSERT INTO notifications (user_id, message) VALUES (?, ?)",
                (user_id, notif_msg),
            )

    return {
        "symbol": symbol,
        "side": side_clean,
        "quantity": quantity,
        "execution_price": execution_price,
        "order_value": order_value,
        "realized_pnl": realized_pnl,
        "virtual_balance": new_balance,
        "message": notif_msg,
    }


def get_portfolio_summary(user_id: int) -> dict[str, Any]:
    """Compute real-time paper portfolio valuation, unrealized P&L, and realized P&L."""
    virtual_balance = ensure_paper_account(user_id)
    rows = query_all(
        "SELECT id, symbol, quantity, avg_buy_price FROM paper_holdings WHERE user_id = ? ORDER BY symbol ASC",
        (user_id,),
    )
    pnl_row = query_one(
        "SELECT COALESCE(SUM(realized_pnl), 0.0) AS total_realized FROM paper_trade_history WHERE user_id = ? AND side = 'SELL'",
        (user_id,),
    )
    total_realized_pnl = round(float(pnl_row["total_realized"]) if pnl_row else 0.0, 2)

    quotes = market_service.get_quotes()
    holdings = []
    total_invested = 0.0
    total_current_value = 0.0

    for r in rows:
        sym = r["symbol"]
        qty = int(r["quantity"])
        avg_buy = round(float(r["avg_buy_price"]), 2)
        q = quotes.get(sym, {})
        ltp = round(float(q.get("ltp") or avg_buy), 2)
        invested = round(avg_buy * qty, 2)
        current_val = round(ltp * qty, 2)
        unrealized_pnl = round((ltp - avg_buy) * qty, 2)
        unrealized_pct = round((unrealized_pnl / invested) * 100, 2) if invested > 0 else 0.0
        meta = NSE_INSTRUMENTS.get(sym, {})

        total_invested += invested
        total_current_value += current_val
        holdings.append(
            {
                "id": r["id"],
                "symbol": sym,
                "name": meta.get("name", sym),
                "sector": meta.get("sector", "Equity"),
                "quantity": qty,
                "avg_buy_price": avg_buy,
                "ltp": ltp,
                "day_change_pct": float(q.get("change_pct") or 0.0),
                "invested_value": invested,
                "current_value": current_val,
                "unrealized_pnl": unrealized_pnl,
                "unrealized_pct": unrealized_pct,
            }
        )

    total_invested = round(total_invested, 2)
    total_current_value = round(total_current_value, 2)
    total_unrealized_pnl = round(total_current_value - total_invested, 2)
    total_portfolio_value = round(virtual_balance + total_current_value, 2)
    total_pnl = round(total_unrealized_pnl + total_realized_pnl, 2)

    return {
        "virtual_balance": virtual_balance,
        "total_invested": total_invested,
        "total_holdings_value": total_current_value,
        "total_portfolio_value": total_portfolio_value,
        "total_unrealized_pnl": total_unrealized_pnl,
        "total_realized_pnl": total_realized_pnl,
        "total_pnl": total_pnl,
        "holdings": holdings,
    }


def get_trade_history(user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    """Return user's paper trade history ordered most recent first."""
    rows = query_all(
        """
        SELECT id, symbol, side, quantity, execution_price, realized_pnl, timestamp
        FROM paper_trade_history
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (user_id, limit),
    )
    return [dict(r) for r in rows]
