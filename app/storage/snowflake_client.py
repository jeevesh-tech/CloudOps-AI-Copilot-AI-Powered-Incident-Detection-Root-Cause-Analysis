"""
Snowflake adapter - the persistent data platform for CloudOps AI Copilot.

Connection details come exclusively from environment variables - never hardcoded.
Required: SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER, SNOWFLAKE_WAREHOUSE, SNOWFLAKE_DATABASE,
SNOWFLAKE_SCHEMA. Authentication: either SNOWFLAKE_PASSWORD, or key-pair auth via
SNOWFLAKE_PRIVATE_KEY_PATH (+ optional SNOWFLAKE_PRIVATE_KEY_PASSPHRASE).
Optional: SNOWFLAKE_ROLE.

If Snowflake is not configured (env vars missing), functions here log a warning and
no-op rather than raising, so the rest of the pipeline (and unit tests) can run without
a live Snowflake connection - consistent with how the Bedrock Agent adapter falls back
to a stub when unconfigured.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = _ROOT / "snowflake" / "schema.sql"
_LOG_DIR = _ROOT / "data" / "logs"

_REQUIRED_ENV = ["SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_DATABASE", "SNOWFLAKE_SCHEMA"]


def _get_logger() -> logging.Logger:
    logger = logging.getLogger("cloudops.snowflake")
    if logger.handlers:
        return logger
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(_LOG_DIR / "snowflake.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def is_configured() -> bool:
    return all(os.environ.get(key) for key in _REQUIRED_ENV) and bool(
        os.environ.get("SNOWFLAKE_PASSWORD") or os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH")
    )


def get_connection():
    """Open a new Snowflake connection using environment-variable configuration only."""
    import snowflake.connector  # imported lazily so it's only required when actually used

    kwargs = {
        "account": os.environ["SNOWFLAKE_ACCOUNT"],
        "user": os.environ["SNOWFLAKE_USER"],
        "warehouse": os.environ["SNOWFLAKE_WAREHOUSE"],
        "database": os.environ["SNOWFLAKE_DATABASE"],
        "schema": os.environ["SNOWFLAKE_SCHEMA"],
    }
    role = os.environ.get("SNOWFLAKE_ROLE")
    if role:
        kwargs["role"] = role

    private_key_path = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PATH")
    if private_key_path:
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives import serialization

        passphrase = os.environ.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE")
        with open(private_key_path, "rb") as key_file:
            p_key = serialization.load_pem_private_key(
                key_file.read(),
                password=passphrase.encode() if passphrase else None,
                backend=default_backend(),
            )
        kwargs["private_key"] = p_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    else:
        kwargs["password"] = os.environ["SNOWFLAKE_PASSWORD"]

    return snowflake.connector.connect(**kwargs)


def ensure_schema(conn=None) -> None:
    """Apply snowflake/schema.sql (idempotent CREATE TABLE IF NOT EXISTS statements)."""
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        sql_text = SCHEMA_PATH.read_text(encoding="utf-8")
        cur = conn.cursor()
        try:
            for statement in sql_text.split(";"):
                statement = statement.strip()
                if statement:
                    cur.execute(statement)
        finally:
            cur.close()
    finally:
        if owns_conn:
            conn.close()


def _guarded(action_name: str):
    """Decorator: skip the call (log a warning) if Snowflake isn't configured."""
    def decorator(fn):
        def wrapper(*args, **kwargs):
            if not is_configured():
                _get_logger().info(json.dumps({
                    "level": "WARNING",
                    "component": "snowflake",
                    "message": f"Skipping {action_name}: Snowflake not configured (missing env vars).",
                }))
                return None
            return fn(*args, **kwargs)
        return wrapper
    return decorator


@_guarded("insert_incident")
def insert_incident(incident: dict, conn=None) -> None:
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        conn.cursor().execute(
            """
            INSERT INTO INCIDENTS (
                incident_id, alarm_name, incident_type, severity, state, reason,
                service, environment, metric, value, threshold, detected_at
            ) VALUES (%(incident_id)s, %(alarm_name)s, %(incident_type)s, %(severity)s, %(state)s,
                      %(reason)s, %(service)s, %(environment)s, %(metric)s, %(value)s, %(threshold)s,
                      %(detected_at)s)
            """,
            incident,
        )
        conn.commit()
        _get_logger().info(json.dumps({
            "level": "INFO", "component": "snowflake",
            "message": f"Inserted incident {incident['incident_id']} into Snowflake.",
        }))
    finally:
        if owns_conn:
            conn.close()


@_guarded("insert_metrics")
def insert_metrics(event: dict, conn=None) -> None:
    """Insert every metric in a telemetry event (as produced by the simulator) into METRICS."""
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        cur = conn.cursor()
        rows = [
            (event["timestamp"], event["service"], event["environment"], metric, value)
            for metric, value in event["metrics"].items()
        ]
        cur.executemany(
            "INSERT INTO METRICS (recorded_at, service, environment, metric, value) VALUES (%s, %s, %s, %s, %s)",
            rows,
        )
        conn.commit()
    finally:
        if owns_conn:
            conn.close()


@_guarded("insert_ai_analysis")
def insert_ai_analysis(analysis: dict, conn=None) -> None:
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        conn.cursor().execute(
            """
            INSERT INTO AI_ANALYSIS (incident_id, root_cause, confidence, severity, recommendations, next_steps)
            SELECT %(incident_id)s, %(root_cause)s, %(confidence)s, %(severity)s,
                   PARSE_JSON(%(recommendations)s), PARSE_JSON(%(next_steps)s)
            """,
            {
                "incident_id": analysis["incident_id"],
                "root_cause": analysis["root_cause"],
                "confidence": analysis["confidence"],
                "severity": analysis["severity"],
                "recommendations": json.dumps(analysis["recommendations"]),
                "next_steps": json.dumps(analysis["next_steps"]),
            },
        )
        conn.commit()
        _get_logger().info(json.dumps({
            "level": "INFO", "component": "snowflake",
            "message": f"Inserted AI analysis for {analysis['incident_id']} into Snowflake.",
        }))
    finally:
        if owns_conn:
            conn.close()


@_guarded("insert_knowledge")
def insert_knowledge(runbooks: list, conn=None) -> None:
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        cur = conn.cursor()
        # Individual execute() calls using INSERT ... SELECT, not executemany() with
        # VALUES: Snowflake does not support a semi-structured function like
        # PARSE_JSON(...) inside a plain VALUES clause at all (regardless of
        # batching) - SELECT is required. executemany's bulk-insert rewrite also
        # cannot handle the SELECT form, so each row is inserted individually.
        for rb in runbooks:
            cur.execute(
                """
                INSERT INTO KNOWLEDGE (incident_type, title, tags, content, path)
                SELECT %s, %s, PARSE_JSON(%s), %s, %s
                """,
                (rb.get("incident_type"), rb["title"], json.dumps(rb.get("tags", [])), rb["content"], rb.get("path")),
            )
        conn.commit()
    finally:
        if owns_conn:
            conn.close()


def get_incident(incident_id: str, conn=None) -> Optional[dict]:
    """Fetch a single incident by id from Snowflake - fallback for incidents no longer
    in local storage (e.g. local DB was reset)."""
    if not is_configured():
        return None
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM INCIDENTS WHERE incident_id = %s", (incident_id,))
        row = cur.fetchone()
        if not row:
            return None
        columns = [c[0].lower() for c in cur.description]
        return dict(zip(columns, row))
    finally:
        if owns_conn:
            conn.close()


def get_previous_incidents(service: str, limit: int = 5, conn=None) -> Optional[list]:
    if not is_configured():
        return None
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM INCIDENTS WHERE service = %s ORDER BY detected_at DESC LIMIT %s",
            (service, limit),
        )
        columns = [c[0].lower() for c in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        if owns_conn:
            conn.close()


def get_metric_history(service: str, environment: str, limit: int = 20, conn=None) -> Optional[list]:
    if not is_configured():
        return None
    owns_conn = conn is None
    conn = conn or get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT recorded_at, metric, value FROM METRICS
            WHERE service = %s AND environment = %s
            ORDER BY recorded_at DESC LIMIT %s
            """,
            (service, environment, limit),
        )
        return [{"timestamp": ts, "metric": m, "value": v} for ts, m, v in cur.fetchall()]
    finally:
        if owns_conn:
            conn.close()
