"""deduplicate: merge entities within the current batch AND against whatever
the candidate already has in Neo4j (see `load_existing`), so re-ingesting a
different CV for the same person doesn't create duplicate Skill/Course/
Project/Accomplishment nodes just because the wording differs slightly.

Dedup keys (see ASSUMPTIONS.md):
  - Skill   : global, by normalized name           -> uid `skill::<slug>`
  - Course  : global, by normalized name           -> uid `course::<slug>`
  - Project : per candidate, by name               -> uid `proj::<cand>::<slug>`
  - Accomp. : per candidate, by sha1(text)         -> uid `acc::<cand>::<hash>`

For each, an exact normalized match (within the batch or in `existing`) is
preferred; if neither exists, a fuzzy match against the same pools (ratio >=
`Settings.dedup_fuzzy_threshold`) is used to catch near-identical wording
across CV versions (e.g. "PMP" vs "PMP - Project Management Professional").
Only entities actually touched by this batch get pulled into the graph (and
therefore re-embedded/re-written) — we never bulk-import the whole existing
graph.

Name-based cross references from extraction (skills_used, project_name,
skills_learned) are resolved to uids here; references that don't resolve are
dropped rather than creating orphans.
"""

from __future__ import annotations

import hashlib
import logging
import re
from difflib import SequenceMatcher

from ..config import Settings
from ..state import IngestionState, empty_existing, empty_graph

log = logging.getLogger(__name__)

_EXPERTISE_RANK = {"Basic": 1, "Intermediate": 2, "Expert": 3}


def _norm(text: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation for matching."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"


def _skill_uid(name: str) -> str:
    return f"skill::{_slug(_norm(name))}"


def _course_uid(name: str) -> str:
    return f"course::{_slug(_norm(name))}"


def _project_uid(candidate_id: str, name: str) -> str:
    return f"proj::{candidate_id}::{_slug(_norm(name))}"


def _candidate_id(email: str) -> str:
    digest = hashlib.sha1(email.strip().lower().encode("utf-8")).hexdigest()[:12]
    return f"cand::{digest}"


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


def _similarity(a: str, b: str) -> float:
    """How alike two already-normalized strings are.

    Plain character-ratio (SequenceMatcher) badly underscores cases like
    "PMP" vs "PMP - Project Management Professional" or "Engineering Program
    Manager" vs "...- ADNOC Gas" — one name is a near-superset of the other,
    but they differ wildly in length, so the char ratio alone stays low. We
    also check: (1) one is a substring of the other, (2) what fraction of
    the shorter name's words are covered by the longer one's.
    """
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    tokens_a, tokens_b = set(a.split()), set(b.split())
    shorter, longer = (tokens_a, tokens_b) if len(tokens_a) <= len(tokens_b) else (tokens_b, tokens_a)
    containment = len(shorter & longer) / len(shorter) if shorter else 0.0
    return max(SequenceMatcher(None, a, b).ratio(), containment)


def _fuzzy_match(name: str, names_by_uid: dict[str, str], threshold: float) -> str | None:
    """uid of the closest name in `names_by_uid`, if its similarity clears `threshold`."""
    norm_name = _norm(name)
    if not norm_name:
        return None
    best_uid, best_score = None, 0.0
    for uid, other_name in names_by_uid.items():
        score = _similarity(norm_name, _norm(other_name))
        if score > best_score:
            best_score, best_uid = score, uid
    return best_uid if best_score >= threshold else None


def _resolve_uid(
    name: str,
    exact_uid: str,
    batch_bucket: dict[str, dict],
    existing_bucket: dict[str, dict],
    threshold: float,
    name_key: str = "name",
) -> tuple[str, dict | None]:
    """Pick the uid this entity should use, preferring an exact match (in the
    current batch, then in `existing`) and falling back to fuzzy matching
    against both pools. Returns (uid, props_to_seed_into_the_batch_or_None) —
    `props_to_seed` is only set when the match came purely from `existing`
    and hasn't been pulled into the batch graph yet.
    """
    if exact_uid in batch_bucket:
        return exact_uid, None
    if exact_uid in existing_bucket:
        return exact_uid, existing_bucket[exact_uid]

    pool = {uid: props.get(name_key, "") for uid, props in existing_bucket.items()}
    pool.update({uid: props.get(name_key, "") for uid, props in batch_bucket.items()})
    fuzzy_uid = _fuzzy_match(name, pool, threshold)
    if fuzzy_uid is None:
        return exact_uid, None
    if fuzzy_uid in batch_bucket:
        return fuzzy_uid, None
    return fuzzy_uid, existing_bucket.get(fuzzy_uid)


def deduplicate(state: IngestionState) -> IngestionState:
    graph = empty_graph()
    edges_seen: set[tuple] = set()
    errors: list[str] = list(state.get("errors", []))
    existing = state.get("existing") or empty_existing()
    threshold = Settings.load(require_secrets=False).dedup_fuzzy_threshold

    existing_skills = existing.get("skills", {})
    existing_courses = existing.get("courses", {})
    existing_projects_by_cid = existing.get("projects_by_candidate", {})
    existing_accs_by_cid = existing.get("accomplishments_by_candidate", {})

    def add_edge(bucket: str, src: str, dst: str) -> None:
        key = (bucket, src, dst)
        if src and dst and key not in edges_seen:
            edges_seen.add(key)
            graph[bucket].append({"from": src, "to": dst})

    for item in state.get("extracted", []):
        cv = item["cv"]
        email = (cv.get("email") or "").strip().lower()
        if not email:
            msg = f"{item.get('filename', item.get('path', 'unknown'))}: missing email — candidate skipped (email is required)"
            log.warning(msg)
            errors.append(msg)
            continue
        cid = _candidate_id(email)
        existing_projects = existing_projects_by_cid.get(cid, {})
        existing_accs = existing_accs_by_cid.get(cid, {})

        new_props = {
            "candidate_id": cid,
            "name": cv.get("candidate_name", ""),
            "email": email,
            "phone": cv.get("phone", ""),
            "location": cv.get("location", ""),
            "headline": cv.get("headline", ""),
            "source_file": item.get("filename", ""),
        }
        existing_candidate = graph["candidates"].get(cid)
        if existing_candidate is None:
            graph["candidates"][cid] = new_props
        else:
            for key in ("name", "phone", "location", "headline"):
                if not existing_candidate.get(key) and new_props.get(key):
                    existing_candidate[key] = new_props[key]
            if new_props["source_file"] and new_props["source_file"] not in existing_candidate["source_file"]:
                existing_candidate["source_file"] += f"; {new_props['source_file']}"

        # --- Skills (global dedup, exact then fuzzy, batch + existing DB) --
        skill_name_to_uid: dict[str, str] = {}
        for skill in cv.get("skills", []):
            exact_uid = _skill_uid(skill["name"])
            uid, seed = _resolve_uid(skill["name"], exact_uid, graph["skills"], existing_skills, threshold)
            if seed is not None:
                graph["skills"][uid] = dict(seed)
            skill_name_to_uid[_norm(skill["name"])] = uid

            existing_entry = graph["skills"].get(uid)
            if existing_entry is None:
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
                    existing_entry.get("expertise_level", "Basic"), 0
                ):
                    existing_entry["expertise_level"] = skill["expertise_level"]
                existing_entry["tags"] = _union(existing_entry.get("tags", []), skill.get("tags", []))
                existing_entry["is_missing"] = "No"
            add_edge("rel_candidate_skill", cid, uid)

        # --- Courses (global dedup, exact then fuzzy, batch + existing DB) -
        for course in cv.get("courses", []):
            exact_uid = _course_uid(course["name"])
            uid, seed = _resolve_uid(course["name"], exact_uid, graph["courses"], existing_courses, threshold)
            if seed is not None:
                graph["courses"][uid] = dict(seed)

            existing_entry = graph["courses"].get(uid)
            if existing_entry is None:
                graph["courses"][uid] = {
                    "uid": uid,
                    "name": course["name"],
                    "is_certification": "Yes" if course.get("is_certification") else "No",
                    "provider": course.get("provider", ""),
                    "validity": course.get("validity", ""),
                }
            else:
                if not existing_entry.get("provider") and course.get("provider"):
                    existing_entry["provider"] = course["provider"]
                if not existing_entry.get("validity") and course.get("validity"):
                    existing_entry["validity"] = course["validity"]
                if course.get("is_certification"):
                    existing_entry["is_certification"] = "Yes"
            add_edge("rel_candidate_course", cid, uid)

            # Skill -[:LEARNED_IN]-> Course
            for skill_name in course.get("skills_learned", []):
                skill_uid = skill_name_to_uid.get(_norm(skill_name))
                add_edge("rel_skill_learned_in", skill_uid, uid)

        # --- Projects (per-candidate dedup, exact then fuzzy) -------------
        project_name_to_uid: dict[str, str] = {}
        for project in cv.get("projects", []):
            exact_uid = _project_uid(cid, project["name"])
            uid, seed = _resolve_uid(project["name"], exact_uid, graph["projects"], existing_projects, threshold)
            if seed is not None:
                graph["projects"][uid] = dict(seed)
            project_name_to_uid[_norm(project["name"])] = uid

            existing_entry = graph["projects"].get(uid)
            if existing_entry is None:
                graph["projects"][uid] = {
                    "uid": uid,
                    "name": project["name"],
                    "company": project.get("company", ""),
                    "start_date": project.get("start_date", ""),
                    "end_date": project.get("end_date", ""),
                }
            else:
                for key in ("company", "start_date", "end_date"):
                    if not existing_entry.get(key) and project.get(key):
                        existing_entry[key] = project[key]
            add_edge("rel_candidate_project", cid, uid)

        # --- Accomplishments (per-candidate dedup, exact then fuzzy) ------
        for acc in cv.get("accomplishments", []):
            text = acc.get("text", "").strip()
            if not text:
                continue
            exact_uid = _acc_uid(cid, text)
            uid, seed = _resolve_uid(
                text, exact_uid, graph["accomplishments"], existing_accs, threshold, name_key="text"
            )
            if seed is not None:
                graph["accomplishments"][uid] = dict(seed)

            existing_entry = graph["accomplishments"].get(uid)
            if existing_entry is None:
                graph["accomplishments"][uid] = {
                    "uid": uid,
                    "text": text,
                    "tags": acc.get("tags", []),
                    "quantitative_achievement": acc.get("quantitative_achievement", ""),
                }
            else:
                existing_entry["tags"] = _union(existing_entry.get("tags", []), acc.get("tags", []))
                if not existing_entry.get("quantitative_achievement") and acc.get("quantitative_achievement"):
                    existing_entry["quantitative_achievement"] = acc["quantitative_achievement"]
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
    return {"graph": graph, "stats": stats, "errors": errors}
