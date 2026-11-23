"""All the SQL lives here. Every query uses ? placeholders (parameterized)."""

import sqlite3
from datetime import datetime

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# A check never needs more than this many recent runs of one pipeline.
HISTORY_LIMIT = 60

# Two tables. The unique index on alerts means the database itself refuses a second
# OPEN alert for the same pipeline and check. Closed alerts stay as history, so the
# same pair may appear many times once closed.
SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY,
    pipeline TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('success', 'failed')),
    rows_in INTEGER NOT NULL,
    rows_out INTEGER NOT NULL,
    rows_rejected INTEGER NOT NULL,
    columns_seen TEXT NOT NULL,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_pipeline_end ON runs(pipeline, end_time);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id INTEGER PRIMARY KEY,
    pipeline TEXT NOT NULL,
    check_name TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    message TEXT NOT NULL,
    runbook TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    times_seen INTEGER NOT NULL,
    closed_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_alert
    ON alerts(pipeline, check_name) WHERE closed_at IS NULL;
"""


# A datetime as text like 2026-11-22 03:15:00. Text in this format sorts in time order.
def to_text(moment):
    return moment.strftime(TIME_FORMAT)


# Text like 2026-11-22 03:15:00 back into a datetime.
def to_time(text):
    return datetime.strptime(text, TIME_FORMAT)


# Open the database file (or ":memory:") and make sure the tables exist.
# Rows come back as dict-like objects.
def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


# Delete every run and every alert. The seed command uses this to start fresh.
def clear_all(conn):
    with conn:
        conn.execute("DELETE FROM runs")
        conn.execute("DELETE FROM alerts")


# Save a list of run dicts. The columns list is stored as one comma-separated text.
def add_runs(conn, runs):
    with conn:
        conn.executemany(
            "INSERT INTO runs (pipeline, start_time, end_time, status, rows_in, rows_out,"
            " rows_rejected, columns_seen, error_message) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(r["pipeline"], to_text(r["start"]), to_text(r["end"]), r["status"], r["rows_in"],
              r["rows_out"], r["rows_rejected"], ",".join(r["columns"]), r["error"])
             for r in runs],
        )


# Turn a database row into the run dict that every check works with.
def row_to_run(row):
    return {
        "pipeline": row["pipeline"],
        "start": to_time(row["start_time"]),
        "end": to_time(row["end_time"]),
        "status": row["status"],
        "rows_in": row["rows_in"],
        "rows_out": row["rows_out"],
        "rows_rejected": row["rows_rejected"],
        "columns": [c for c in row["columns_seen"].split(",") if c],
        "error": row["error_message"],
    }


# The latest runs of one pipeline that had finished by `as_of`, oldest first.
# A run is written to the log when it ends, so a run still going is not seen yet.
# This is also what makes "replay" work: we just look at the log as of an earlier time.
def load_runs(conn, pipeline, as_of):
    rows = conn.execute(
        "SELECT * FROM runs WHERE pipeline = ? AND end_time <= ?"
        " ORDER BY end_time DESC, run_id DESC LIMIT ?",
        (pipeline, to_text(as_of), HISTORY_LIMIT),
    ).fetchall()
    return [row_to_run(row) for row in reversed(rows)]


# The time the most recent run in the whole log ended, or None for an empty log.
def latest_end(conn):
    text = conn.execute("SELECT MAX(end_time) FROM runs").fetchone()[0]
    return to_time(text) if text else None
