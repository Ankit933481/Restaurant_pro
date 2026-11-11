"""Thin DB layer: SQLite (dev/tests) and PostgreSQL (production) behind one API."""
import os
import sqlite3

from flask import current_app, g

from .util import ApiError

try:  # optional: only needed for PostgreSQL
    import psycopg2
    import psycopg2.extras

    _PG_INTEGRITY = (psycopg2.IntegrityError,)
except ImportError:  # pragma: no cover
    psycopg2 = None
    _PG_INTEGRITY = ()

INTEGRITY = (sqlite3.IntegrityError,) + _PG_INTEGRITY
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def is_pg(url):
    return url.startswith(("postgres://", "postgresql://"))


class Conn:
    def __init__(self, raw, pg):
        self.raw, self.pg = raw, pg

    def _run(self, sql, params, conflict):
        cur = self.raw.cursor()
        if self.pg:
            sql = sql.replace("?", "%s")
        try:
            cur.execute(sql, tuple(params))
        except INTEGRITY:
            raise ApiError(409, "conflict", conflict or "The change conflicts with existing data")
        return cur

    def query(self, sql, params=()):
        return [dict(r) for r in self._run(sql, params, None).fetchall()]

    def one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql, params=(), conflict=None):
        return self._run(sql, params, conflict).rowcount

    def insert(self, sql, params=(), conflict=None):
        cur = self._run(sql + " RETURNING id", params, conflict)
        return cur.fetchone()["id"]

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        self.raw.close()


def open_connection(url):
    if is_pg(url):
        if psycopg2 is None:
            raise RuntimeError("psycopg2 is required for PostgreSQL URLs")
        raw = psycopg2.connect(
            url.replace("postgres://", "postgresql://", 1),
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        return Conn(raw, True)
    path = url[len("sqlite:///"):] if url.startswith("sqlite:///") else url
    raw = sqlite3.connect(path, timeout=15)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys=ON")
    return Conn(raw, False)


def init_schema(url):
    with open(SCHEMA_PATH, encoding="utf-8") as fh:
        sql = fh.read()
    if is_pg(url):
        sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY").replace(
            "REAL", "DOUBLE PRECISION"
        )
    conn = open_connection(url)
    try:
        for stmt in sql.split(";"):
            if stmt.strip():
                conn._run(stmt, (), None)
        conn.commit()
    finally:
        conn.close()


def db():
    if "db" not in g:
        g.db = open_connection(current_app.config["DATABASE_URL"])
    return g.db


def update_row(table, row_id, restaurant_id, values):
    """Update whitelisted columns (keys come from validated specs, never from raw input)."""
    if not values:
        return
    cols = ", ".join(f"{k}=?" for k in values)
    db().execute(
        f"UPDATE {table} SET {cols} WHERE id=? AND restaurant_id=?",
        (*values.values(), row_id, restaurant_id),
    )
