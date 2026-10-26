"""
Incident Processor.

Locally replaces the AWS Lambda incident processor. Consumes alert events from the
Monitoring & Alert Engine (only those with trigger_incident=True, i.e. an OK -> ALARM
transition) and turns them into incident records: assigns a unique incident ID,
records type/severity/reason/service/environment/timestamp, persists the incident,
and returns it so the Investigation Engine can be triggered next.

Future AWS mapping: this module's responsibility moves to a Lambda function invoked
by an EventBridge rule reacting to a CloudWatch Alarm state change.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = _ROOT / "data" / "cloudops.db"
_LOG_DIR = _ROOT / "data" / "logs"


# --------------------------------------------------------------------------
# Local storage (SQLite) - operational cache; Snowflake is system of record (Step 11).
# --------------------------------------------------------------------------

def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    db_path = db_path or DB_PATH  # resolved at call time so tests can monkeypatch module DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    _init_db(conn)
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS incidents (
            incident_id TEXT PRIMARY KEY,
            alarm_name TEXT NOT NULL,
            incident_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            state TEXT NOT NULL,
            reason TEXT NOT NULL,
            service TEXT NOT NULL,
            environment TEXT NOT NULL,
            metric TEXT NOT NULL,
            value REAL NOT NULL,
            threshold REAL NOT NULL,
            detected_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS incident_counter (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            next_seq INTEGER NOT NULL
        )
        """
    )
    conn.execute("INSERT OR IGNORE INTO incident_counter (id, next_seq) VALUES (1, 1)")
    conn.commit()


def _next_incident_id(conn: sqlite3.Connection) -> str:
    cur = conn.execute("UPDATE incident_counter SET next_seq = next_seq + 1 WHERE id = 1 RETURNING next_seq - 1")
    seq = cur.fetchone()[0]
    conn.commit()
    return f"INC-{seq:06d}"


def _save_incident(conn: sqlite3.Connection, incident: dict) -> None:
    conn.execute(
        """
        INSERT INTO incidents (
            incident_id, alarm_name, incident_type, severity, state, reason,
            service, environment, metric, value, threshold, detected_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            incident["incident_id"], incident["alarm_name"], incident["incident_type"],
            incident["severity"], incident["state"], incident["reason"], incident["service"],
            incident["environment"], incident["metric"], incident["value"], incident["threshold"],
            incident["detected_at"],
        ),
    )
    conn.commit()


def get_incident(incident_id: str, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        row = conn.execute("SELECT * FROM incidents WHERE incident_id=?", (incident_id,)).fetchone()
        if not row:
            return None
        columns = [d[0] for d in conn.execute("SELECT * FROM incidents WHERE incident_id=?", (incident_id,)).description]
        return dict(zip(columns, row))
    finally:
        if owns_conn:
            conn.close()


def list_incidents(conn: Optional[sqlite3.Connection] = None) -> list[dict]:
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        cur = conn.execute("SELECT * FROM incidents ORDER BY detected_at DESC")
        columns = [d[0] for d in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        if owns_conn:
            conn.close()


# --------------------------------------------------------------------------
# Structured logging
# --------------------------------------------------------------------------

def _get_logger() -> logging.Logger:
    logger = logging.getLogger("cloudops.incidents")
    if logger.handlers:
        return logger
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(_LOG_DIR / "incidents.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def _log_incident(incident: dict) -> None:
    record = {
        "timestamp": incident["detected_at"],
        "level": "INFO",
        "component": "incident_processor",
        "incident_id": incident["incident_id"],
        "message": f"Created incident {incident['incident_id']} ({incident['incident_type']})",
        "incident_type": incident["incident_type"],
        "severity": incident["severity"],
        "service": incident["service"],
        "environment": incident["environment"],
    }
    _get_logger().info(json.dumps(record))


# --------------------------------------------------------------------------
# Processing
# --------------------------------------------------------------------------

def process_alert(alert: dict, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
    """
    Turn a monitoring alert into an incident record.

    Only alerts with trigger_incident=True (an OK -> ALARM transition) create a new
    incident. Any other alert is ignored here (returns None) to avoid duplicate
    incidents for a sustained breach.
    """
    if not alert.get("trigger_incident"):
        return None

    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        incident_id = _next_incident_id(conn)
        incident = {
            "incident_id": incident_id,
            "alarm_name": alert["alarm_name"],
            "incident_type": alert["incident_type"],
            "severity": alert["severity"],
            "state": "ALARM",
            "reason": alert["reason"],
            "service": alert["service"],
            "environment": alert["environment"],
            "metric": alert["metric"],
            "value": alert["value"],
            "threshold": alert["threshold"],
            "detected_at": alert["timestamp"],
        }
        _save_incident(conn, incident)
        _log_incident(incident)
        return incident
    finally:
        if owns_conn:
            conn.close()


def process_alerts(alerts: list[dict], conn: Optional[sqlite3.Connection] = None) -> list[dict]:
    """Process a batch of alerts (as returned by monitor.evaluate_event), returning created incidents."""
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        incidents = []
        for alert in alerts:
            incident = process_alert(alert, conn)
            if incident:
                incidents.append(incident)
        return incidents
    finally:
        if owns_conn:
            conn.close()
