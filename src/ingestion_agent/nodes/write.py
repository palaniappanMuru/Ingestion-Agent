"""write_neo4j: persist the deduplicated, embedded graph to Neo4j.

Honors `dry_run`: in that mode the node logs what it *would* write and returns
without touching the database, so the full pipeline can be exercised without a
running Neo4j (or any secrets configured).
"""

from __future__ import annotations

import logging

from ..config import Settings
from ..neo4j_client import Neo4jWriter
from ..state import IngestionState

log = logging.getLogger(__name__)


def write_to_neo4j(state: IngestionState) -> IngestionState:
    graph = state["graph"]
    errors: list[str] = list(state.get("errors", []))

    if state.get("dry_run"):
        log.info(
            "[dry-run] Skipping Neo4j write: %d candidates, %d skills, %d courses, "
            "%d projects, %d accomplishments",
            len(graph["candidates"]),
            len(graph["skills"]),
            len(graph["courses"]),
            len(graph["projects"]),
            len(graph["accomplishments"]),
        )
        stats = {**state.get("stats", {}), "written": False}
        return {"errors": errors, "stats": stats}

    settings = Settings.load()  # requires Neo4j connection + secrets
    try:
        with Neo4jWriter(settings) as writer:
            writer.ensure_schema()
            counts = writer.write_graph(graph)
    except Exception as exc:
        log.exception("Neo4j write failed")
        errors.append(f"neo4j write error: {exc}")
        stats = {**state.get("stats", {}), "written": False}
        return {"errors": errors, "stats": stats}

    log.info(
        "Wrote to Neo4j: %d candidates, %d skills, %d courses, %d projects, %d accomplishments",
        counts["candidates"],
        counts["skills"],
        counts["courses"],
        counts["projects"],
        counts["accomplishments"],
    )
    stats = {**state.get("stats", {}), "written": True, "neo4j_counts": counts}
    return {"errors": errors, "stats": stats}
