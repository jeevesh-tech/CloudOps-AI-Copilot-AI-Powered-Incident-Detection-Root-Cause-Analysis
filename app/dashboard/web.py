"""
Local web dashboard (Flask).

Reuses the same data-gathering function as the CLI dashboard (app.dashboard.dashboard),
so incident/investigation/AI-analysis logic is never duplicated between the two UIs.
Runs entirely locally - no external services beyond what the rest of the pipeline
already talks to (Snowflake, optionally AWS Bedrock).
"""

from __future__ import annotations

import markdown
from flask import Flask, render_template, abort, request, redirect, url_for

from app.incidents.processor import list_incidents
from app.dashboard.dashboard import gather_dashboard_data
from app.ai.chat import ask_about_incident, answer_general_question

# In-memory only (per Flask process); not persisted. Good enough for local dev use -
# a future iteration could persist this to SQLite/Snowflake if history needs to survive
# a restart.
_chat_history: dict = {}
_global_chat_history: list = []


def _sparkline_points(values: list, width: int = 280, height: int = 60, pad: int = 6) -> str:
    if not values:
        return ""
    vmin, vmax = min(values), max(values)
    if vmax == vmin:
        vmax = vmin + 1
    n = len(values)
    step = (width - 2 * pad) / max(n - 1, 1)
    points = []
    for i, v in enumerate(values):
        x = pad + i * step
        y = height - pad - ((v - vmin) / (vmax - vmin)) * (height - 2 * pad)
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)


def _render_markdown(text: str) -> str:
    return markdown.markdown(text, extensions=["fenced_code", "nl2br", "sane_lists"])


def _with_rendered_answers(history: list) -> list:
    return [{**turn, "answer_html": _render_markdown(turn["answer"])} for turn in history]


def _build_metric_charts(metric_history: list) -> dict:
    chronological = list(reversed(metric_history))
    series: dict = {}
    for entry in chronological:
        series.setdefault(entry["metric"], []).append(entry["value"])

    charts = {}
    for metric, values in series.items():
        charts[metric] = {
            "points": _sparkline_points(values),
            "latest": values[-1],
            "min": min(values),
            "max": max(values),
        }
    return charts


def create_app() -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def incidents_view():
        incidents = list_incidents()
        high = sum(1 for i in incidents if i["severity"] == "HIGH")
        medium = sum(1 for i in incidents if i["severity"] == "MEDIUM")
        low = sum(1 for i in incidents if i["severity"] == "LOW")
        return render_template(
            "incidents.html",
            incidents=incidents,
            counts={"HIGH": high, "MEDIUM": medium, "LOW": low, "TOTAL": len(incidents)},
        )

    @app.route("/incident/<incident_id>")
    def incident_detail_view(incident_id: str):
        data = gather_dashboard_data(incident_id)
        if not data:
            abort(404, description=f"No incident found with id {incident_id}")
        return render_template(
            "incident_detail.html",
            incident=data["incident"],
            evidence=data["evidence"],
            analysis=data["analysis"],
            metric_charts=_build_metric_charts(data["evidence"]["metric_history"]),
            chat_history=_with_rendered_answers(_chat_history.get(incident_id, [])),
        )

    @app.route("/incident/<incident_id>/chat", methods=["POST"])
    def incident_chat(incident_id: str):
        question = request.form.get("question", "").strip()
        if question:
            data = gather_dashboard_data(incident_id)
            if data:
                history = _chat_history.setdefault(incident_id, [])
                answer = ask_about_incident(data["evidence"], question, history)
                history.append({"question": question, "answer": answer})
        return redirect(url_for("incident_detail_view", incident_id=incident_id))

    @app.route("/chat", methods=["GET", "POST"])
    def chat_view():
        if request.method == "POST":
            question = request.form.get("question", "").strip()
            if question:
                answer, incident_id = answer_general_question(question, _global_chat_history)
                _global_chat_history.append({"question": question, "answer": answer, "incident_id": incident_id})
            return redirect(url_for("chat_view"))
        return render_template(
            "chat.html",
            chat_history=_with_rendered_answers(_global_chat_history),
            incidents=list_incidents(),
        )

    return app


def run(host: str = "127.0.0.1", port: int = 5000) -> None:
    app = create_app()
    app.run(host=host, port=port, debug=False)
