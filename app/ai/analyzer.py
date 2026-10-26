"""
AI Analyzer.

Orchestrates AI analysis of an incident: takes the evidence package (from the
Investigation Engine, including retrieved RAG runbook context), constructs a request,
calls the AWS Bedrock Agent adapter, and parses the response into a structured
analysis: root_cause, confidence, severity, recommendations, next_steps.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from app.ai.bedrock_agent import invoke_agent, BedrockAgentError

_ROOT = Path(__file__).resolve().parents[2]
_LOG_DIR = _ROOT / "data" / "logs"

_REQUIRED_FIELDS = ["root_cause", "confidence", "severity", "recommendations", "next_steps"]


def _get_logger() -> logging.Logger:
    logger = logging.getLogger("cloudops.ai")
    if logger.handlers:
        return logger
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(_LOG_DIR / "ai.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


def build_request_text(evidence: dict) -> str:
    """Construct the natural-language + structured request sent to the Bedrock Agent."""
    runbook_text = "\n\n".join(
        f"## {rb['title']}\n{rb['content']}" for rb in evidence.get("runbooks", [])
    ) or "No relevant runbook found."

    return (
        "You are a CloudOps incident analysis assistant. Analyze the following incident "
        "evidence and respond with ONLY a JSON object containing exactly these fields: "
        "root_cause (string), confidence (number 0-1), severity (string), "
        "recommendations (list of strings), next_steps (list of strings).\n\n"
        f"Incident: {evidence['incident_id']} ({evidence['incident_type']})\n"
        f"Service: {evidence['service']} | Environment: {evidence['environment']}\n"
        f"Reason: {evidence['reason']}\n\n"
        f"Current metrics: {json.dumps(evidence['metrics'])}\n\n"
        f"Recent metric history: {json.dumps(evidence['metric_history'])}\n\n"
        f"Application logs: {json.dumps(evidence['logs'])}\n\n"
        f"Deployment info: {json.dumps(evidence['deployment'])}\n\n"
        f"Previous incidents for this service: {json.dumps(evidence['previous_incidents'])}\n\n"
        f"Relevant runbooks:\n{runbook_text}"
    )


def _strip_code_fence(text: str) -> str:
    """Strip a Markdown code fence (```json ... ``` or ``` ... ```) if present.
    Some models (e.g. Gemini) wrap JSON responses in one even when asked for raw JSON."""
    if not isinstance(text, str):
        return text
    stripped = text.strip()
    match = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", stripped, re.DOTALL)
    return match.group(1) if match else stripped


def _parse_response(raw_text: str) -> dict:
    """Parse the agent's raw text response into the required structured analysis."""
    try:
        data = json.loads(_strip_code_fence(raw_text))
    except (json.JSONDecodeError, TypeError):
        return {
            "root_cause": "Unable to parse AI response as JSON.",
            "confidence": 0.0,
            "severity": "UNKNOWN",
            "recommendations": [],
            "next_steps": [],
            "raw_response": raw_text,
        }

    result = {field: data.get(field) for field in _REQUIRED_FIELDS}
    result["recommendations"] = result["recommendations"] or []
    result["next_steps"] = result["next_steps"] or []
    result["confidence"] = float(result["confidence"]) if result["confidence"] is not None else 0.0
    result["root_cause"] = result["root_cause"] or "No root cause provided."
    result["severity"] = result["severity"] or "UNKNOWN"
    return result


def analyze(evidence: dict) -> dict:
    """Run AI analysis on an evidence package, returning structured analysis."""
    request_text = build_request_text(evidence)
    try:
        raw_response = invoke_agent(request_text, session_id=evidence["incident_id"])
    except BedrockAgentError as exc:
        raw_response = json.dumps({
            "root_cause": f"AI analysis temporarily unavailable: {exc}",
            "confidence": 0.0,
            "severity": "UNKNOWN",
            "recommendations": [],
            "next_steps": ["Retry once an AI provider (Gemini, Anthropic, or Bedrock) is configured and available."],
        })
    analysis = _parse_response(raw_response)
    analysis["incident_id"] = evidence["incident_id"]

    _get_logger().info(json.dumps({
        "level": "INFO",
        "component": "ai_analyzer",
        "incident_id": evidence["incident_id"],
        "message": f"Analysis complete for {evidence['incident_id']}",
        "root_cause": analysis["root_cause"],
        "confidence": analysis["confidence"],
        "severity": analysis["severity"],
    }))

    return analysis
