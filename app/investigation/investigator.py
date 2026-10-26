"""
Investigation Engine.

Given an incident, collects evidence (current metrics, recent metric history,
simulated application logs, simulated deployment info, previous incidents, and
relevant runbooks) and assembles it into a structured evidence package for the
AI Analyzer.

Future AWS mapping: this orchestration moves into a Step Functions workflow /
Lambda invoking real AWS services (CloudWatch, CloudWatch Logs, CodeDeploy, etc.).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from app.incidents.processor import get_incident, list_incidents
from app.investigation.metrics import current_metrics, metrics_at_timestamp, metric_history
from app.investigation.logs import collect_logs
from app.investigation.deployments import get_deployment_info
from app.investigation.evidence import build_evidence_package
from app.rag.retriever import retrieve_runbooks

_ROOT = Path(__file__).resolve().parents[2]
_LOG_DIR = _ROOT / "data" / "logs"


def _get_logger() -> logging.Logger:
    logger = logging.getLogger("cloudops.investigation")
    if logger.handlers:
        return logger
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(_LOG_DIR / "investigation.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def _previous_incidents(incident: dict, limit: int = 5) -> list[dict]:
    all_incidents = list_incidents()
    same_service = [
        inc for inc in all_incidents
        if inc["service"] == incident["service"] and inc["incident_id"] != incident["incident_id"]
    ]
    return same_service[:limit]


def investigate(incident_id: str, incident: Optional[dict] = None) -> Optional[dict]:
    """
    Collect evidence for an incident and return the assembled evidence package.

    If `incident` is not provided, it's looked up in local storage. Callers that
    already have the incident record from elsewhere (e.g. Snowflake, for an incident
    no longer in local storage) can pass it directly so the same evidence-assembly
    logic (logs, deployment, runbooks) still applies.
    """
    incident = incident or get_incident(incident_id)
    if not incident:
        return None

    metrics = metrics_at_timestamp(incident["service"], incident["environment"], incident["detected_at"])
    if not metrics:
        # Fallback for incidents whose exact-timestamp telemetry isn't in local storage
        # (e.g. resolved via Snowflake after a local DB reset) - best-effort snapshot.
        metrics = current_metrics(incident["service"], incident["environment"])
    history = metric_history(incident["service"], incident["environment"])
    logs = collect_logs(incident)
    deployment = get_deployment_info(incident)
    previous_incidents = _previous_incidents(incident)
    runbooks = retrieve_runbooks(incident)

    package = build_evidence_package(
        incident=incident,
        metrics=metrics,
        metric_history=history,
        logs=logs,
        deployment=deployment,
        previous_incidents=previous_incidents,
        runbooks=runbooks,
    )

    _get_logger().info(json.dumps({
        "level": "INFO",
        "component": "investigation",
        "incident_id": incident_id,
        "message": f"Collected evidence for {incident_id}",
        "logs_collected": len(logs),
        "previous_incidents_found": len(previous_incidents),
        "runbooks_found": len(runbooks),
    }))

    return package
