"""deduplicate: merge entities within and across all CVs into one batch graph.

Dedup keys (see ASSUMPTIONS.md):
  - Skill   : global, by normalized name           -> uid `skill::<slug>`
  - Course  : global, by (name, provider)          -> uid `course::<slug>`
  - Project : per candidate, by name               -> uid `proj::<cand>::<slug>`
  - Accomp. : per candidate, by sha1(text)         -> uid `acc::<cand>::<hash>`

Name-based cross references from extraction (skills_used, project_name,
skills_learned) are resolved to uids here; references that don't resolve are
dropped rather than creating orphans.
"""

from __future__ import annotations

import hashlib
import logging
import re

from ..state import IngestionState, empty_graph

log = logging.getLogger(__name__)

_EXPERTISE_RANK = {"Basic": 1, "Intermediate": 2, "Expert": 3}


def _norm(text: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation for matching."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"


def _skill_uid(name: str) -> str:
    return f"skill::{_slug(_norm(name))}"


def _course_uid(name: str, provider: str) -> str:
    return f"course::{_slug(_norm(name))}::{_slug(_norm(provider))}"


def _project_uid(candidate_id: str, name: str) -> str:
    return f"proj::{candidate_id}::{_slug(_norm(name))}"


def _acc_uid(candidate_id: str, text: str) -> str:
    digest = hashlib.sha1(_norm(text).encode("utf-8")).hexdigest()[:12]
    return f"acc::{candidate_id}::{digest}"


def _union(a: list[str], b: list[str]) -> list[str]:
    seen, out = set(), []
    for item in [*a, *b]:
        key = item.lower()
        if item and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def deduplicate(state: IngestionState) -> IngestionState:
    graph = empty_graph()
    edges_seen: set[tuple] = set()

    def add_edge(bucket: str, src: str, dst: str) -> None:
        key = (bucket, src, dst)
        if src and dst and key not in edges_seen:
            edges_seen.add(key)
            graph[bucket].append({"from": src, "to": dst})

    for item in state.get("extracted", []):
        cid = item["candidate_id"]
        cv = item["cv"]

        graph["candidates"][cid] = {
            "candidate_id": cid,
            "name": cv.get("candidate_name", ""),
            "email": cv.get("email", ""),
            "phone": cv.get("phone", ""),
            "location": cv.get("location", ""),
            "headline": cv.get("headline", ""),
            "source_file": item.get("filename", ""),
        }

        # --- Skills (global dedup) -------------------------------------
        skill_name_to_uid: dict[str, str] = {}
        for skill in cv.get("skills", []):
            uid = _skill_uid(skill["name"])
            skill_name_to_uid[_norm(skill["name"])] = uid
            existing = graph["skills"].get(uid)
            if existing is None:
                graph["skills"][uid] = {
                    "uid": uid,
                    "name": skill["name"],
                    "type": skill.get("type", "Tech"),
                    "expertise_level": skill.get("expertise_level", "Intermediate"),
                    "tags": skill.get("tags", []),
                    "is_missing": "No",  # found in a CV -> present
                }
            else:
                # Keep the higher expertise level; union tags.
                if _EXPERTISE_RANK.get(skill.get("expertise_level", "Basic"), 0) > _EXPERTISE_RANK.get(
                    existing["expertise_level"], 0
                ):
                    existing["expertise_level"] = skill["expertise_level"]
                existing["tags"] = _union(existing["tags"], skill.get("tags", []))
            add_edge("rel_candidate_skill", cid, uid)

        # --- Courses (global dedup) ------------------------------------
        for course in cv.get("courses", []):
            uid = _course_uid(course["name"], course.get("provider", ""))
            existing = graph["courses"].get(uid)
            if existing is None:
                graph["courses"][uid] = {
                    "uid": uid,
                    "name": course["name"],
                    "is_certification": "Yes" if course.get("is_certification") else "No",
                    "provider": course.get("provider", ""),
                    "validity": course.get("validity", ""),
                }
            add_edge("rel_candidate_course", cid, uid)

            # Skill -[:LEARNED_IN]-> Course
            for skill_name in course.get("skills_learned", []):
                skill_uid = skill_name_to_uid.get(_norm(skill_name))
                add_edge("rel_skill_learned_in", skill_uid, uid)

        # --- Projects (per-candidate dedup) ----------------------------
        project_name_to_uid: dict[str, str] = {}
        for project in cv.get("projects", []):
            uid = _project_uid(cid, project["name"])
            project_name_to_uid[_norm(project["name"])] = uid
            if uid not in graph["projects"]:
                graph["projects"][uid] = {
                    "uid": uid,
                    "name": project["name"],
                    "company": project.get("company", ""),
                    "start_date": project.get("start_date", ""),
                    "end_date": project.get("end_date", ""),
                }
            add_edge("rel_candidate_project", cid, uid)

        # --- Accomplishments (per-candidate dedup) ---------------------
        for acc in cv.get("accomplishments", []):
            text = acc.get("text", "").strip()
            if not text:
                continue
            uid = _acc_uid(cid, text)
            if uid not in graph["accomplishments"]:
                graph["accomplishments"][uid] = {
                    "uid": uid,
                    "text": text,
                    "tags": acc.get("tags", []),
                    "quantitative_achievement": acc.get("quantitative_achievement", ""),
                }
            add_edge("rel_candidate_acc", cid, uid)

            # Accomplishment -[:USING]-> Skill
            for skill_name in acc.get("skills_used", []):
                add_edge("rel_acc_using_skill", uid, skill_name_to_uid.get(_norm(skill_name)))

            # Accomplishment -[:GAINED_IN]-> Project
            proj_uid = project_name_to_uid.get(_norm(acc.get("project_name", "")))
            add_edge("rel_acc_gained_in", uid, proj_uid)

    stats = {
        **state.get("stats", {}),
        "unique_skills": len(graph["skills"]),
        "unique_courses": len(graph["courses"]),
        "unique_projects": len(graph["projects"]),
        "unique_accomplishments": len(graph["accomplishments"]),
    }
    log.info(
        "Deduplicated graph: %d skills, %d courses, %d projects, %d accomplishments",
        len(graph["skills"]),
        len(graph["courses"]),
        len(graph["projects"]),
        len(graph["accomplishments"]),
    )
    return {"graph": graph, "stats": stats}
