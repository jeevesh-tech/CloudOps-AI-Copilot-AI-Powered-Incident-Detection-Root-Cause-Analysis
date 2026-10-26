"""Metric evidence collection for the Investigation Engine."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = _ROOT / "data" / "cloudops.db"


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    db_path = db_path or DB_PATH  # resolved at call time so tests can monkeypatch module DB_PATH
    return sqlite3.connect(db_path)


def current_metrics(service: str, environment: str, conn: Optional[sqlite3.Connection] = None) -> dict:
    """Latest recorded value per metric for the given service/environment."""
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        cur = conn.execute(
            """
            SELECT metric, value FROM metrics_log
            WHERE service=? AND environment=? AND id IN (
                SELECT MAX(id) FROM metrics_log WHERE service=? AND environment=? GROUP BY metric
            )
            """,
            (service, environment, service, environment),
        )
        return {metric: value for metric, value in cur.fetchall()}
    finally:
        if owns_conn:
            conn.close()


def metrics_at_timestamp(service: str, environment: str, timestamp: str, conn: Optional[sqlite3.Connection] = None) -> dict:
    """
    Metric values recorded at the exact timestamp of a specific telemetry event (e.g.
    an incident's detected_at). Use this instead of current_metrics() when building
    evidence for a specific incident - current_metrics() reflects whatever is newest
    *right now*, which drifts away from "what this incident actually looked like" as
    soon as later, unrelated incidents occur for the same service.
    """
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        cur = conn.execute(
            "SELECT metric, value FROM metrics_log WHERE service=? AND environment=? AND timestamp=?",
            (service, environment, timestamp),
        )
        return {metric: value for metric, value in cur.fetchall()}
    finally:
        if owns_conn:
            conn.close()


def metric_history(service: str, environment: str, limit: int = 20, conn: Optional[sqlite3.Connection] = None) -> list[dict]:
    """Most recent metric_log rows for the given service/environment, newest first."""
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        cur = conn.execute(
            """
            SELECT timestamp, metric, value FROM metrics_log
            WHERE service=? AND environment=?
            ORDER BY id DESC LIMIT ?
            """,
            (service, environment, limit),
        )
        return [{"timestamp": ts, "metric": m, "value": v} for ts, m, v in cur.fetchall()]
    finally:
        if owns_conn:
            conn.close()
