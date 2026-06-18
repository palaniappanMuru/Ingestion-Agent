"""embed: attach Voyage AI embeddings to the deduplicated graph nodes.

Each embeddable label (Skill, Course, Project, Accomplishment) gets one vector
per node, stored as an `embedding` property on the node dict so the write node
persists it with the rest of the props. Embedding is the most natural text
representation of the node (name + context), so semantic search later matches on
what the node *means*, not just its identifier.

`--dry-run` still runs this node; if no Voyage key is configured the embeddings
are skipped (nodes simply carry no `embedding`) so extraction can be verified
without external services.
"""

from __future__ import annotations

import logging

from ..config import Settings
from ..embeddings import Embedder
from ..state import IngestionState

log = logging.getLogger(__name__)


def _skill_text(props: dict) -> str:
    parts = [props.get("name", "")]
    if props.get("tags"):
        parts.append("Tags: " + ", ".join(props["tags"]))
    return ". ".join(p for p in parts if p)


def _course_text(props: dict) -> str:
    parts = [props.get("name", "")]
    if props.get("provider"):
        parts.append("Provider: " + props["provider"])
    return ". ".join(p for p in parts if p)


def _project_text(props: dict) -> str:
    parts = [props.get("name", "")]
    if props.get("company"):
        parts.append("Company: " + props["company"])
    return ". ".join(p for p in parts if p)


def _accomplishment_text(props: dict) -> str:
    parts = [props.get("text", "")]
    if props.get("tags"):
        parts.append("Tags: " + ", ".join(props["tags"]))
    return ". ".join(p for p in parts if p)


# Graph bucket -> function producing the text to embed for one node's props.
_EMBED_PLAN = {
    "skills": _skill_text,
    "courses": _course_text,
    "projects": _project_text,
    "accomplishments": _accomplishment_text,
}


def embed_nodes(state: IngestionState) -> IngestionState:
    graph = state["graph"]
    errors: list[str] = list(state.get("errors", []))

    settings = Settings.load(require_secrets=False)
    if not settings.voyage_api_key:
        log.warning("No VOYAGE_API_KEY set; skipping embeddings (nodes will have no vectors).")
        stats = {**state.get("stats", {}), "nodes_embedded": 0}
        return {"graph": graph, "errors": errors, "stats": stats}

    embedder = Embedder(settings)

    # Flatten every embeddable node into one ordered list so we make the
    # fewest possible Voyage calls, then scatter the vectors back by position.
    targets: list[dict] = []  # the props dict to mutate
    texts: list[str] = []
    for bucket, to_text in _EMBED_PLAN.items():
        for props in graph[bucket].values():
            text = to_text(props)
            if not text:
                continue
            targets.append(props)
            texts.append(text)

    if not texts:
        log.info("No embeddable nodes.")
        stats = {**state.get("stats", {}), "nodes_embedded": 0}
        return {"graph": graph, "errors": errors, "stats": stats}

    try:
        vectors = embedder.embed_documents(texts)
        for props, vector in zip(targets, vectors):
            props["embedding"] = vector
        embedded = len(vectors)
    except Exception as exc:
        log.exception("Embedding failed")
        errors.append(f"embedding error: {exc}")
        embedded = 0

    log.info("Embedded %d node(s)", embedded)
    stats = {**state.get("stats", {}), "nodes_embedded": embedded}
    return {"graph": graph, "errors": errors, "stats": stats}
