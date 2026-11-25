import sqlite3
from contextlib import contextmanager
from flask import current_app, g
from config import Config


def open_connection(db_path: str | None = None) -> sqlite3.Connection:
    """Open a SQLite connection configured for explicit ACID transactions and FK enforcement."""
    target_path = db_path or Config.DATABASE_PATH
    conn = sqlite3.connect(target_path, timeout=30.0, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def get_db() -> sqlite3.Connection:
    """Return a request-scoped SQLite connection."""
    if "db" not in g:
        db_path = current_app.config.get("DATABASE_PATH", Config.DATABASE_PATH)
        g.db = open_connection(db_path)
    return g.db


def close_db(exception=None) -> None:
    """Close the request-scoped database connection if open."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


@contextmanager
def atomic_transaction(conn: sqlite3.Connection | None = None):
    """Execute a block inside an explicit BEGIN IMMEDIATE ... COMMIT/ROLLBACK SQLite transaction."""
    own_conn = conn is None
    connection = conn or get_db()
    try:
        connection.execute("BEGIN IMMEDIATE;")
        yield connection
        connection.execute("COMMIT;")
    except Exception:
        try:
            connection.execute("ROLLBACK;")
        except sqlite3.Error:
            pass
        raise
    finally:
        if own_conn and conn is None:
            # Request-scoped connection will be closed on teardown.
            pass


def query_all(sql: str, params: tuple = (), conn: sqlite3.Connection | None = None) -> list[sqlite3.Row]:
    """Run a parameterized SELECT query and return all rows."""
    connection = conn or get_db()
    return connection.execute(sql, params).fetchall()


def query_one(sql: str, params: tuple = (), conn: sqlite3.Connection | None = None) -> sqlite3.Row | None:
    """Run a parameterized SELECT query and return the first row or None."""
    connection = conn or get_db()
    return connection.execute(sql, params).fetchone()
