"""DuckDB access helpers for the repository layer.

DuckDB lets one process open a database file read-write (or several processes
open it read-only), so the process that stores MQTT events owns a single
shared connection. Each helper call runs on its own short-lived cursor from
that connection, which is DuckDB's supported way to use one database from
several threads. Calls made inside ``with transaction():`` on the same thread
reuse the transaction's cursor and therefore join that transaction.
"""
from __future__ import annotations

import atexit
import threading
from contextlib import contextmanager
from pathlib import Path

import duckdb

from repository.repo_config import duckdb_config

_lock = threading.Lock()
_connection = None
_atexit_registered = False
_thread_state = threading.local()


def database_path():
    """Return the configured database file; ``get_connection()`` creates it if it is missing."""
    return Path(duckdb_config()["database"])


def get_connection():
    """Return the process-wide DuckDB connection, opening it on first use.

    Queries should go through the helpers below (or ``cursor()``) rather than
    this connection directly, since a DuckDB connection is not thread-safe.

    Returns:
        duckdb.DuckDBPyConnection: The shared parent connection.
    """
    global _connection, _atexit_registered
    with _lock:
        if _connection is None:
            settings = duckdb_config()
            database = Path(settings["database"])
            if not settings["read_only"]:
                database.parent.mkdir(parents=True, exist_ok=True)
            connection = duckdb.connect(
                str(database), read_only=settings["read_only"]
            )
            try:
                for extension in settings["extensions"]:
                    connection.install_extension(extension)
                    connection.load_extension(extension)
            except Exception:
                connection.close()
                raise
            _connection = connection
            if not _atexit_registered:
                atexit.register(close_connection)
                _atexit_registered = True
        return _connection


def close_connection():
    """Close the shared connection and release the database file lock."""
    global _connection
    with _lock:
        if _connection is not None:
            _connection.close()
            _connection = None


@contextmanager
def cursor():
    """Yield a cursor for the calling thread.

    Inside ``transaction()`` this is the transaction's cursor; otherwise a
    fresh cursor is opened on the shared connection and closed on exit.
    """
    current = getattr(_thread_state, "transaction_cursor", None)
    if current is not None:
        yield current
        return
    parent = get_connection()
    with _lock:
        cur = parent.cursor()
    try:
        yield cur
    finally:
        cur.close()


@contextmanager
def transaction():
    """Run the enclosed helper calls in one transaction on this thread.

    Commits on normal exit and rolls back if the block raises. Transactions
    cannot be nested.

    Yields:
        duckdb.DuckDBPyConnection: The transaction's cursor.
    """
    if getattr(_thread_state, "transaction_cursor", None) is not None:
        raise RuntimeError("transaction() cannot be nested")
    with cursor() as cur:
        cur.execute("BEGIN TRANSACTION")
        _thread_state.transaction_cursor = cur
        try:
            yield cur
        except BaseException:
            cur.execute("ROLLBACK")
            raise
        else:
            cur.execute("COMMIT")
        finally:
            _thread_state.transaction_cursor = None


def execute(sql, params=None):
    """Execute a statement that returns no rows (DDL, INSERT, UPDATE, ...)."""
    with cursor() as cur:
        cur.execute(sql, params)


def fetch_one(sql, params=None):
    """Return the first row of a query as a tuple, or None if it is empty."""
    with cursor() as cur:
        return cur.execute(sql, params).fetchone()


def fetch_all(sql, params=None):
    """Return every row of a query as a list of tuples."""
    with cursor() as cur:
        return cur.execute(sql, params).fetchall()


def run_sql_file(path):
    """Execute every statement in a SQL script, e.g. an idempotent DDL file."""
    with cursor() as cur:
        cur.execute(Path(path).read_text(encoding="utf-8"))


def table_exists(name):
    """Return True if a table with this name exists in the database."""
    row = fetch_one(
        "SELECT COUNT(*) FROM duckdb_tables() WHERE table_name = ?", [name]
    )
    return row[0] > 0
