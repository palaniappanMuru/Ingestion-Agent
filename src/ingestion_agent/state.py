"""LangGraph state and the deduplicated graph-data containers.

The pipeline is linear (discover → parse → extract → deduplicate → embed →
write), so each node reads the keys produced upstream and adds its own. No
concurrent writes to the same key, so plain dict semantics are fine.
"""

from __future__ import annotations

from typing import Any, TypedDict


class IngestionState(TypedDict, total=False):
    # Inputs / control
    cv_folder: str
    dry_run: bool

    # discover
    files: list[str]

    # parse  -> [{"path", "candidate_id", "text"}]
    documents: list[dict[str, Any]]

    # extract -> [{"path", "candidate_id", "cv": <ExtractedCV dict>}]
    extracted: list[dict[str, Any]]

    # deduplicate -> the unified, batch-wide graph (see GraphData)
    graph: dict[str, Any]

    # bookkeeping
    stats: dict[str, Any]
    errors: list[str]


def empty_graph() -> dict[str, Any]:
    """A fresh, empty deduplicated-graph payload.

    Nodes are keyed dicts so dedup is a dict upsert. Edges are de-duplicated
    tuples. The keys here are the dedup keys described in ASSUMPTIONS.md.
    """
    return {
        # uid -> skill props
        "skills": {},
        # course_key -> course props (incl. its own generated uid)
        "courses": {},
        # project_key -> project props (incl. uid)
        "projects": {},
        # accomplishment_key -> accomplishment props (incl. uid)
        "accomplishments": {},
        # candidate_id -> candidate props
        "candidates": {},
        # relationship edge sets, each a list of dicts with the two endpoint uids
        "rel_skill_learned_in": [],      # skill_uid  -> course_uid
        "rel_acc_using_skill": [],       # acc_uid    -> skill_uid
        "rel_acc_gained_in": [],         # acc_uid    -> project_uid
        "rel_candidate_skill": [],       # candidate  -> skill_uid
        "rel_candidate_course": [],      # candidate  -> course_uid
        "rel_candidate_project": [],     # candidate  -> project_uid
        "rel_candidate_acc": [],         # candidate  -> acc_uid
    }
