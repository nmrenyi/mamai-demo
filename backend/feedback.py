"""SQLite feedback + exchange logging.

Two tables:
  exchanges — one row per model response (query, retrieved context, citations,
              full response) so feedback can be analysed against what was shown.
  feedback  — clinician's structured rating/notes, keyed by message_id.
"""

import json
import sqlite3
import time
from contextlib import contextmanager

from backend import config


@contextmanager
def _conn():
    c = sqlite3.connect(config.FEEDBACK_DB)
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_db() -> None:
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS exchanges (
            message_id TEXT PRIMARY KEY,
            ts         REAL,
            session_id TEXT,
            query      TEXT,
            history    TEXT,
            context    TEXT,
            citations  TEXT,
            response   TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS feedback (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            ts         REAL,
            message_id TEXT,
            session_id TEXT,
            rating     INTEGER,
            helpful    INTEGER,
            issues     TEXT,
            comment    TEXT
        )""")


def save_exchange(message_id, session_id, query, history, context, citations, response) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO exchanges VALUES (?,?,?,?,?,?,?,?)",
            (message_id, time.time(), session_id, query, json.dumps(history),
             context, json.dumps(citations), response),
        )


def save_feedback(message_id, session_id, rating, helpful, issues, comment) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO feedback (ts, message_id, session_id, rating, helpful, issues, comment) "
            "VALUES (?,?,?,?,?,?,?)",
            (time.time(), message_id, session_id, rating,
             None if helpful is None else int(helpful), json.dumps(issues or []), comment),
        )
