import logging
import os
from importlib.util import find_spec
from flask import Flask, session
from flask_socketio import SocketIO

from config import Config
from database import close_db
from init_db import init_db
from market_service import market_service
from routes.auth import auth_bp
from routes.finance import finance_bp
from routes.main import main_bp
from routes.market import market_bp
from routes.trading import trading_bp

SOCKETIO_ASYNC_MODE = "gevent" if find_spec("gevent") else "threading"
socketio = SocketIO(cors_allowed_origins="*", async_mode=SOCKETIO_ASYNC_MODE)
logger = logging.getLogger(__name__)


def _market_price_emitter() -> None:
    """Broadcast market prices continuously using the active Socket.IO async model."""
    while True:
        try:
            socketio.emit(
                "market_tick",
                market_service.step_ticks_and_candles(),
                namespace="/",
            )
        except Exception:
            logger.exception("Market price emitter failed")
        socketio.sleep(1.5)


def format_inr(value: float | int | None) -> str:
    """Format numeric amounts cleanly with Indian Rupee grouping (e.g., ₹1,00,000.00)."""
    if value is None:
        return "₹0.00"
    num = float(value)
    neg = num < 0
    num = abs(num)
    whole, dec = f"{num:.2f}".split(".")
    if len(whole) > 3:
        last3 = whole[-3:]
        rest = whole[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        formatted_whole = ",".join(groups) + "," + last3
    else:
        formatted_whole = whole
    prefix = "-₹" if neg else "₹"
    return f"{prefix}{formatted_whole}.{dec}"


def create_app(test_config: dict | None = None, start_stream: bool = True) -> Flask:
    """Create and configure the FinTrack Flask + SocketIO application."""
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    init_db(app.config["DATABASE_PATH"])
    app.teardown_appcontext(close_db)

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(market_bp)
    app.register_blueprint(trading_bp)
    app.register_blueprint(finance_bp)

    app.jinja_env.filters["inr"] = format_inr

    @app.context_processor
    def inject_globals():
        return {
            "current_user_name": session.get("user_name"),
            "current_user_email": session.get("user_email"),
        }

    socketio.init_app(
        app,
        cors_allowed_origins="*",
        async_mode=SOCKETIO_ASYNC_MODE,
    )

    @socketio.on("connect")
    def handle_ws_connect():
        socketio.emit(
            "market_tick",
            {
                "status": market_service.get_status(),
                "quotes": market_service.get_quotes(),
                "latest_candles": {},
            },
        )

    if start_stream and market_service.start_background_hydration():
        socketio.start_background_task(_market_price_emitter)

    return app


app = create_app(start_stream=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="127.0.0.1", port=port, debug=False, allow_unsafe_werkzeug=True)
