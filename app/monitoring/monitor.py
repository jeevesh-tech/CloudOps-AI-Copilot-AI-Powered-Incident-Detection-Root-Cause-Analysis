"""
Monitoring & Alert Engine.

Locally replaces CloudWatch Metrics + CloudWatch Alarms + EventBridge alarm triggering
for Phase 1. Evaluates incoming telemetry events against configurable threshold rules,
tracks per-alarm OK/ALARM state, and emits alert events only on meaningful transitions.

Future AWS mapping: rules.json -> CloudWatch Alarms; state tracking -> CloudWatch Alarm
state machine; alert emission -> EventBridge rule triggering a Lambda (incident processor).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = _ROOT / "config" / "rules.json"
DB_PATH = _ROOT / "data" / "cloudops.db"
_LOG_DIR = _ROOT / "data" / "logs"

_OPERATORS = {
    ">=": lambda v, t: v >= t,
    "<=": lambda v, t: v <= t,
    ">": lambda v, t: v > t,
    "<": lambda v, t: v < t,
    "==": lambda v, t: v == t,
}


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

def load_rules(path: Path = CONFIG_PATH) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("rules", [])


def _compare(value: float, operator: str, threshold: float) -> bool:
    try:
        fn = _OPERATORS[operator]
    except KeyError:
        raise ValueError(f"Unsupported operator: {operator}")
    return fn(value, threshold)


# --------------------------------------------------------------------------
# Local state store (SQLite) - operational cache, not the system of record.
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
        CREATE TABLE IF NOT EXISTS alarm_state (
            alarm_name TEXT NOT NULL,
            service TEXT NOT NULL,
            environment TEXT NOT NULL,
            state TEXT NOT NULL,
            last_value REAL,
            last_evaluated TEXT,
            PRIMARY KEY (alarm_name, service, environment)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS metrics_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            service TEXT NOT NULL,
            environment TEXT NOT NULL,
            metric TEXT NOT NULL,
            value REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            alarm_name TEXT NOT NULL,
            service TEXT NOT NULL,
            environment TEXT NOT NULL,
            metric TEXT NOT NULL,
            value REAL NOT NULL,
            threshold REAL NOT NULL,
            operator TEXT NOT NULL,
            incident_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            reason TEXT NOT NULL,
            transition TEXT NOT NULL,
            trigger_incident INTEGER NOT NULL
        )
        """
    )
    conn.commit()


def _get_state(conn: sqlite3.Connection, alarm_name: str, service: str, environment: str) -> str:
    row = conn.execute(
        "SELECT state FROM alarm_state WHERE alarm_name=? AND service=? AND environment=?",
        (alarm_name, service, environment),
    ).fetchone()
    return row[0] if row else "OK"


def _set_state(
    conn: sqlite3.Connection,
    alarm_name: str,
    service: str,
    environment: str,
    state: str,
    value: float,
    timestamp: str,
) -> None:
    conn.execute(
        """
        INSERT INTO alarm_state (alarm_name, service, environment, state, last_value, last_evaluated)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(alarm_name, service, environment)
        DO UPDATE SET state=excluded.state, last_value=excluded.last_value, last_evaluated=excluded.last_evaluated
        """,
        (alarm_name, service, environment, state, value, timestamp),
    )
    conn.commit()


def _record_metric(conn: sqlite3.Connection, timestamp: str, service: str, environment: str, metric: str, value: float) -> None:
    conn.execute(
        "INSERT INTO metrics_log (timestamp, service, environment, metric, value) VALUES (?, ?, ?, ?, ?)",
        (timestamp, service, environment, metric, value),
    )
    conn.commit()


def _record_alert(conn: sqlite3.Connection, alert: dict) -> None:
    conn.execute(
        """
        INSERT INTO alerts (
            timestamp, alarm_name, service, environment, metric, value, threshold,
            operator, incident_type, severity, reason, transition, trigger_incident
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            alert["timestamp"], alert["alarm_name"], alert["service"], alert["environment"],
            alert["metric"], alert["value"], alert["threshold"], alert["operator"],
            alert["incident_type"], alert["severity"], alert["reason"], alert["transition"],
            1 if alert["trigger_incident"] else 0,
        ),
    )
    conn.commit()


# --------------------------------------------------------------------------
# Structured logging
# --------------------------------------------------------------------------

def _get_logger() -> logging.Logger:
    logger = logging.getLogger("cloudops.monitor")
    if logger.handlers:
        return logger
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(_LOG_DIR / "monitor.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def _log_alert(alert: dict) -> None:
    record = {
        "timestamp": alert["timestamp"],
        "level": "INFO",
        "component": "monitor",
        "message": f"{alert['alarm_name']} transition {alert['transition']}",
        "alarm_name": alert["alarm_name"],
        "incident_type": alert["incident_type"],
        "severity": alert["severity"],
        "metric": alert["metric"],
        "value": alert["value"],
        "threshold": alert["threshold"],
        "service": alert["service"],
        "environment": alert["environment"],
        "transition": alert["transition"],
        "trigger_incident": alert["trigger_incident"],
    }
    _get_logger().info(json.dumps(record))


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------

def evaluate_event(event: dict, rules: Optional[list[dict]] = None, conn: Optional[sqlite3.Connection] = None) -> list[dict]:
    """
    Evaluate a telemetry event (as produced by the simulator) against threshold rules.

    Returns a list of alert dicts, one per rule whose metric is present in the event.
    Each alert records the OK/ALARM transition. Only alerts with trigger_incident=True
    (an OK -> ALARM transition) should be passed on to the Incident Processor; other
    transitions (ALARM -> ALARM, ALARM -> OK) are recorded but must not create new
    incidents, preventing duplicate incidents for a sustained breach.
    """
    rules = rules if rules is not None else load_rules()
    owns_conn = conn is None
    conn = conn or get_connection()

    service = event["service"]
    environment = event["environment"]
    timestamp = event.get("timestamp") or datetime.now(timezone.utc).isoformat()
    metrics = event["metrics"]

    alerts = []
    try:
        # Record each metric exactly once per event, independent of how many rules
        # reference it (e.g. AppLatency has both a high- and low-threshold rule).
        for metric, value in metrics.items():
            _record_metric(conn, timestamp, service, environment, metric, value)

        for rule in rules:
            metric = rule["metric"]
            if metric not in metrics:
                continue
            value = metrics[metric]

            alarm_name = rule["alarm_name"]
            breach = _compare(value, rule["operator"], rule["threshold"])
            previous_state = _get_state(conn, alarm_name, service, environment)
            new_state = "ALARM" if breach else "OK"

            if previous_state == "OK" and new_state == "ALARM":
                transition = "OK_TO_ALARM"
            elif previous_state == "ALARM" and new_state == "ALARM":
                transition = "ALARM_TO_ALARM"
            elif previous_state == "ALARM" and new_state == "OK":
                transition = "ALARM_TO_OK"
            else:
                transition = "OK_TO_OK"

            _set_state(conn, alarm_name, service, environment, new_state, value, timestamp)

            if transition == "OK_TO_OK":
                # Nothing alarm-worthy happened; skip emitting/recording an alert.
                continue

            alert = {
                "timestamp": timestamp,
                "alarm_name": alarm_name,
                "service": service,
                "environment": environment,
                "metric": metric,
                "value": value,
                "threshold": rule["threshold"],
                "operator": rule["operator"],
                "incident_type": rule["incident_type"],
                "severity": rule["severity"],
                "reason": rule["reason"],
                "transition": transition,
                "trigger_incident": transition == "OK_TO_ALARM",
            }
            _record_alert(conn, alert)
            _log_alert(alert)
            alerts.append(alert)
    finally:
        if owns_conn:
            conn.close()

    return alerts
