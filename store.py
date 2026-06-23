"""SQLite store of seen/notified listings. Never notify twice."""
from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
    id TEXT PRIMARY KEY,
    slug TEXT,
    price REAL,
    score INTEGER,
    verdict TEXT,
    notified INTEGER DEFAULT 0,
    first_seen TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS runs (
    started TEXT DEFAULT CURRENT_TIMESTAMP,
    listings INTEGER,
    buys INTEGER,
    notified INTEGER,
    tokens INTEGER
);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def is_seen(conn: sqlite3.Connection, listing_id: str) -> bool:
    return conn.execute("SELECT 1 FROM seen WHERE id=?", (listing_id,)).fetchone() is not None


def mark(conn: sqlite3.Connection, listing: dict, score: int, verdict: str, notified: bool) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO seen (id, slug, price, score, verdict, notified) VALUES (?,?,?,?,?,?)",
        (listing["id"], listing["slug"], listing["price"], score, verdict, int(notified)),
    )
    conn.commit()


def log_run(conn: sqlite3.Connection, listings: int, buys: int, notified: int, tokens: int) -> None:
    conn.execute(
        "INSERT INTO runs (listings, buys, notified, tokens) VALUES (?,?,?,?)",
        (listings, buys, notified, tokens),
    )
    conn.commit()
