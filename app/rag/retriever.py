"""
Local RAG / Knowledge Base retriever.

Lightweight, dependency-free retrieval over Markdown runbooks in data/knowledge/.
Each runbook has a small YAML-like frontmatter block (incident_type, title, tags)
followed by Markdown content. Retrieval scores runbooks by:
  1. Exact incident_type match (highest priority)
  2. Tag/keyword overlap with the incident's type and reason text

This keeps Phase 1 free of ChromaDB/embedding dependencies while exposing a stable
`retrieve_runbooks(incident, top_k)` interface. Future upgrade path: swap the internal
`_score` and `_load_index` functions for embedding-based similarity search (ChromaDB or
an AWS-hosted vector store) without changing this function's signature or callers.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = _ROOT / "data" / "knowledge"

_index_cache: Optional[list] = None


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse a simple '---\\nkey: value\\n---\\n<body>' frontmatter block."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not match:
        return {}, text

    raw_meta, body = match.group(1), match.group(2)
    meta = {}
    for line in raw_meta.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            items = [v.strip() for v in value[1:-1].split(",") if v.strip()]
            meta[key] = items
        else:
            meta[key] = value
    return meta, body


def _load_index(force_reload: bool = False) -> list:
    global _index_cache
    if _index_cache is not None and not force_reload:
        return _index_cache

    runbooks = []
    if KNOWLEDGE_DIR.exists():
        for path in sorted(KNOWLEDGE_DIR.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            meta, body = _parse_frontmatter(text)
            runbooks.append(
                {
                    "path": str(path.relative_to(_ROOT)),
                    "incident_type": meta.get("incident_type", ""),
                    "title": meta.get("title", path.stem),
                    "tags": meta.get("tags", []),
                    "content": body.strip(),
                }
            )
    _index_cache = runbooks
    return runbooks


def _keywords_for(incident: dict) -> set:
    text = " ".join(
        str(incident.get(field, "")) for field in ("incident_type", "reason", "metric")
    ).lower()
    return set(re.findall(r"[a-z0-9]+", text))


def _score(runbook: dict, incident: dict, keywords: set) -> float:
    if runbook["incident_type"] and runbook["incident_type"] == incident.get("incident_type"):
        return 100.0  # exact incident_type match dominates

    runbook_keywords = set(t.lower() for t in runbook["tags"])
    runbook_keywords |= set(re.findall(r"[a-z0-9]+", runbook["title"].lower()))
    return float(len(keywords & runbook_keywords))


def retrieve_runbooks(incident: dict, top_k: int = 2) -> list:
    """
    Return up to top_k runbooks most relevant to the given incident, ranked by
    incident_type match first, then keyword/tag overlap. Returns [] if no runbook
    scores above zero relevance.
    """
    runbooks = _load_index()
    keywords = _keywords_for(incident)

    scored = [(r, _score(r, incident, keywords)) for r in runbooks]
    scored = [(r, s) for r, s in scored if s > 0]
    scored.sort(key=lambda pair: pair[1], reverse=True)

    return [r for r, _ in scored[:top_k]]
