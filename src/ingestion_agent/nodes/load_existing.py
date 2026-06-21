"""load_existing: read what's already in Neo4j so `deduplicate` can fuzzy-match
new extractions against it instead of only deduping within the current batch.

Honors `dry_run` the same way `write_neo4j` does: no Neo4j connection needed,
the pipeline just falls back to batch-only dedup.
"""

from __future__ import annotations

import logging

from ..config import Settings
from ..neo4j_client import Neo4jWriter
from ..state import IngestionState, empty_existing

log = logging.getLogger(__name__)


def load_existing(state: IngestionState) -> IngestionState:
    if state.get("dry_run"):
        return {"existing": empty_existing()}

    settings = Settings.load()
    try:
        with Neo4jWriter(settings) as writer:
            existing = writer.fetch_existing()
    except Exception as exc:
        log.warning("Could not load existing graph for cross-batch dedup: %s", exc)
        existing = empty_existing()

    return {"existing": existing}
