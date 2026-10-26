"""
Conversational Q&A about a specific incident.

Reuses the same evidence package (metrics, logs, deployment, previous incidents, RAG
runbook context) as the structured AI Analyzer (app.ai.analyzer), but answers a
free-text developer question conversationally instead of producing the fixed
root_cause/confidence/severity/recommendations/next_steps structure. Uses the same
Bedrock adapter as the analyzer, so it shares its stub-when-unconfigured behavior -
but degrades to a plain explanatory message here instead of raw stub JSON, since a
JSON blob would be a confusing chat reply.
"""

from __future__ import annotations

import os
import re
from typing import Optional

from app.ai.bedrock_agent import invoke_agent, BedrockAgentError
from app.incidents.processor import get_incident as get_local_incident
from app.investigation.investigator import investigate
from app.storage import snowflake_client

_INCIDENT_ID_RE = re.compile(r"INC-\d+", re.IGNORECASE)


def extract_incident_id(text: str) -> Optional[str]:
    match = _INCIDENT_ID_RE.search(text)
    return match.group(0).upper() if match else None


def resolve_evidence(incident_id: str) -> Optional[dict]:
    """Look up an incident's evidence package - local storage first, falling back to
    Snowflake if it's no longer available locally (e.g. local DB was reset)."""
    incident = get_local_incident(incident_id)
    if incident:
        return investigate(incident_id, incident=incident)

    incident = snowflake_client.get_incident(incident_id)
    if incident:
        return investigate(incident_id, incident=incident)

    return None


def build_chat_prompt(evidence: dict, question: str, history: list) -> str:
    runbook_text = "\n\n".join(
        f"## {rb['title']}\n{rb['content']}" for rb in evidence.get("runbooks", [])
    ) or "No relevant runbook found."

    history_text = "".join(
        f"\nDeveloper: {turn['question']}\nAssistant: {turn['answer']}\n" for turn in history
    )

    return (
        "You are a CloudOps incident assistant helping a developer understand and resolve "
        "an incident. Answer conversationally, reference the evidence below where relevant, "
        "and suggest concrete next steps when appropriate.\n\n"
        f"Incident: {evidence['incident_id']} ({evidence['incident_type']}, severity {evidence['severity']})\n"
        f"Service: {evidence['service']} | Environment: {evidence['environment']}\n"
        f"Reason: {evidence['reason']}\n\n"
        f"Current metrics: {evidence['metrics']}\n\n"
        f"Recent logs: {evidence['logs']}\n\n"
        f"Deployment info: {evidence['deployment']}\n\n"
        f"Relevant runbooks:\n{runbook_text}\n"
        f"{history_text}\n"
        f"Developer: {question}\nAssistant:"
    )


def answer_general_question(question: str, history: list) -> tuple:
    """
    Handle a free-text question that may reference any incident by id (e.g.
    "what happened with INC-000004?"). Returns (answer, incident_id_or_None).
    """
    incident_id = extract_incident_id(question)
    if not incident_id:
        return (
            "Please mention an incident ID in your question, e.g. "
            '"What happened with INC-000004?" or "How do I fix INC-000006?" '
            "- check the incident list for available IDs.",
            None,
        )

    evidence = resolve_evidence(incident_id)
    if not evidence:
        return (f"I couldn't find any incident with id {incident_id} (checked local storage and Snowflake).", incident_id)

    incident_history = [h for h in history if h.get("incident_id") == incident_id]
    answer = ask_about_incident(evidence, question, incident_history)
    return answer, incident_id


def ask_about_incident(evidence: dict, question: str, history: list = None) -> str:
    history = history or []

    has_provider = any(os.environ.get(key) for key in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "BEDROCK_MODEL_ID"))
    if not has_provider:
        return ("AI chat isn't available yet: no AI provider is configured. "
                "Set GEMINI_API_KEY, ANTHROPIC_API_KEY, or BEDROCK_MODEL_ID to enable real answers.")

    prompt = build_chat_prompt(evidence, question, history)
    try:
        return invoke_agent(prompt, session_id=evidence["incident_id"])
    except BedrockAgentError as exc:
        return f"AI chat is temporarily unavailable: {exc}"
