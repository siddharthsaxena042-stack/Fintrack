from functools import wraps
from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config, DEFAULT_WATCHLIST_SYMBOLS, NSE_INSTRUMENTS
from database import atomic_transaction, get_db, query_one

auth_bp = Blueprint("auth", __name__)


def login_required(view):
    """Ensure the request has an authenticated user session."""

    @wraps(view)
    def wrapped_view(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required."}), 401
            return redirect(url_for("auth.login"))

        user = query_one("SELECT id, full_name, email FROM users WHERE id = ?", (user_id,))
        if user is None:
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify({"error": "Session expired. Please log in again."}), 401
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped_view


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if session.get("user_id"):
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm_password = request.form.get("confirm_password") or ""

        if len(full_name) < 2:
            flash("Please enter your full name (at least 2 characters).", "danger")
            return render_template("auth/signup.html")
        if "@" not in email or "." not in email:
            flash("Please enter a valid email address.", "danger")
            return render_template("auth/signup.html")
        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "danger")
            return render_template("auth/signup.html")
        if confirm_password and password != confirm_password:
            flash("Passwords do not match.", "danger")
            return render_template("auth/signup.html")

        existing = query_one("SELECT id FROM users WHERE email = ?", (email,))
        if existing is not None:
            flash("An account with that email already exists. Please log in.", "warning")
            return render_template("auth/signup.html")

        password_hash = generate_password_hash(password)
        conn = get_db()
        with atomic_transaction(conn) as tx:
            cur = tx.execute(
                "INSERT INTO users (full_name, email, password_hash) VALUES (?, ?, ?)",
                (full_name, email, password_hash),
            )
            user_id = cur.lastrowid

            tx.execute(
                "INSERT INTO paper_accounts (user_id, virtual_balance) VALUES (?, ?)",
                (user_id, Config.DEFAULT_VIRTUAL_BALANCE),
            )

            for sym in DEFAULT_WATCHLIST_SYMBOLS:
                meta = NSE_INSTRUMENTS.get(sym)
                if meta:
                    tx.execute(
                        "INSERT OR IGNORE INTO watchlist (user_id, symbol, instrument_key, exchange) VALUES (?, ?, ?, ?)",
                        (user_id, meta["symbol"], meta["instrument_key"], meta["exchange"]),
                    )

            tx.execute(
                "INSERT INTO notifications (user_id, message) VALUES (?, ?)",
                (
                    user_id,
                    f"Welcome to FinTrack, {full_name}! Your paper account is funded with ₹{Config.DEFAULT_VIRTUAL_BALANCE:,.2f}.",
                ),
            )

        session.clear()
        session["user_id"] = user_id
        session["user_name"] = full_name
        session["user_email"] = email
        flash("Account created! ₹1,00,000.00 virtual capital credited.", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("auth/signup.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        user = query_one(
            "SELECT id, full_name, email, password_hash FROM users WHERE email = ?",
            (email,),
        )
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "danger")
            return render_template("auth/login.html")

        session.clear()
        session["user_id"] = user["id"]
        session["user_name"] = user["full_name"]
        session["user_email"] = user["email"]
        flash(f"Welcome back, {user['full_name']}!", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("auth/login.html")


@auth_bp.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    flash("You have been logged out securely.", "info")
    return redirect(url_for("auth.login"))
