"""LangGraph assembly.

Wires the six node functions into the linear pipeline:

    discover -> parse -> extract -> deduplicate -> embed -> write_neo4j

The graph is plain and linear (no branching/conditional edges) because each
stage strictly depends on the one before it. State is the shared `IngestionState`
TypedDict; each node returns a partial dict that LangGraph merges in.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import (
    deduplicate,
    discover_files,
    embed_nodes,
    extract_entities,
    parse_documents,
    write_to_neo4j,
)
from .state import IngestionState


def build_graph():
    """Build and compile the ingestion pipeline."""
    builder = StateGraph(IngestionState)

    builder.add_node("discover", discover_files)
    builder.add_node("parse", parse_documents)
    builder.add_node("extract", extract_entities)
    builder.add_node("deduplicate", deduplicate)
    builder.add_node("embed", embed_nodes)
    builder.add_node("write_neo4j", write_to_neo4j)

    builder.add_edge(START, "discover")
    builder.add_edge("discover", "parse")
    builder.add_edge("parse", "extract")
    builder.add_edge("extract", "deduplicate")
    builder.add_edge("deduplicate", "embed")
    builder.add_edge("embed", "write_neo4j")
    builder.add_edge("write_neo4j", END)

    return builder.compile()
