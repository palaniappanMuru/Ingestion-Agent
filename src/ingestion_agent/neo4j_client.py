"""Neo4j writer.

Everything is MERGE-based and therefore idempotent: re-running on the same
folder updates nodes/edges in place instead of duplicating them. On first use it
also creates uniqueness constraints and vector indexes.

Graph shape written:

    (Candidate)-[:HAS_SKILL]->(Skill)
    (Candidate)-[:COMPLETED]->(Course)
    (Candidate)-[:WORKED_ON]->(Project)
    (Candidate)-[:ACHIEVED]->(Accomplishment)
    (Skill)-[:LEARNED_IN]->(Course)
    (Accomplishment)-[:USING]->(Skill)
    (Accomplishment)-[:GAINED_IN]->(Project)
"""

from __future__ import annotations

from typing import Any

from neo4j import GraphDatabase

from .config import Settings

# Node labels that carry an `embedding` property + a `uid` identity.
_EMBEDDED_LABELS = ["Skill", "Course", "Project", "Accomplishment"]


class Neo4jWriter:
    def __init__(self, settings: Settings) -> None:
        self._database = settings.neo4j_database
        self._embedding_dim = settings.embedding_dim
        self._driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password),
        )

    def close(self) -> None:
        self._driver.close()

    def __enter__(self) -> "Neo4jWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- schema -------------------------------------------------------------
    def ensure_schema(self) -> None:
        """Create uniqueness constraints and vector indexes (idempotent)."""
        with self._driver.session(database=self._database) as session:
            session.run(
                "CREATE CONSTRAINT candidate_id IF NOT EXISTS "
                "FOR (c:Candidate) REQUIRE c.candidate_id IS UNIQUE"
            )
            for label in _EMBEDDED_LABELS:
                session.run(
                    f"CREATE CONSTRAINT {label.lower()}_uid IF NOT EXISTS "
                    f"FOR (n:{label}) REQUIRE n.uid IS UNIQUE"
                )
                session.run(
                    f"CREATE VECTOR INDEX {label.lower()}_embedding IF NOT EXISTS "
                    f"FOR (n:{label}) ON (n.embedding) "
                    "OPTIONS {indexConfig: {"
                    "`vector.dimensions`: $dim, "
                    "`vector.similarity_function`: 'cosine'}}",
                    dim=self._embedding_dim,
                )

    # -- read (cross-batch dedup) --------------------------------------------
    def fetch_existing(self) -> dict[str, Any]:
        """Existing Skill/Course nodes (global) and Project/Accomplishment
        nodes (per candidate), full properties included, so a new batch can
        fuzzy-match against what's already in the graph instead of only
        deduping within itself, and seed a matched node's props when reused.
        """
        with self._driver.session(database=self._database) as session:
            skills = session.run("MATCH (s:Skill) RETURN properties(s) AS props").data()
            courses = session.run("MATCH (c:Course) RETURN properties(c) AS props").data()
            projects = session.run(
                "MATCH (c:Candidate)-[:WORKED_ON]->(p:Project) "
                "RETURN c.candidate_id AS cid, properties(p) AS props"
            ).data()
            accomplishments = session.run(
                "MATCH (c:Candidate)-[:ACHIEVED]->(a:Accomplishment) "
                "RETURN c.candidate_id AS cid, properties(a) AS props"
            ).data()

        projects_by_candidate: dict[str, dict[str, dict]] = {}
        for row in projects:
            projects_by_candidate.setdefault(row["cid"], {})[row["props"]["uid"]] = row["props"]

        accomplishments_by_candidate: dict[str, dict[str, dict]] = {}
        for row in accomplishments:
            accomplishments_by_candidate.setdefault(row["cid"], {})[row["props"]["uid"]] = row["props"]

        return {
            "skills": {row["props"]["uid"]: row["props"] for row in skills},
            "courses": {row["props"]["uid"]: row["props"] for row in courses},
            "projects_by_candidate": projects_by_candidate,
            "accomplishments_by_candidate": accomplishments_by_candidate,
        }

    # -- write --------------------------------------------------------------
    def write_graph(self, graph: dict[str, Any]) -> dict[str, int]:
        """Write the deduplicated batch graph. Returns counts written."""
        with self._driver.session(database=self._database) as session:
            session.execute_write(self._write_nodes_and_edges, graph)

        return {
            "candidates": len(graph["candidates"]),
            "skills": len(graph["skills"]),
            "courses": len(graph["courses"]),
            "projects": len(graph["projects"]),
            "accomplishments": len(graph["accomplishments"]),
        }

    @staticmethod
    def _write_nodes_and_edges(tx, graph: dict[str, Any]) -> None:
        # --- Nodes (UNWIND batches; SET embeds only when present) ----------
        tx.run(
            """
            UNWIND $rows AS row
            MERGE (c:Candidate {candidate_id: row.candidate_id})
            SET c += row.props
            """,
            rows=[{"candidate_id": cid, "props": props} for cid, props in graph["candidates"].items()],
        )

        tx.run(
            """
            UNWIND $rows AS row
            MERGE (s:Skill {uid: row.uid})
            SET s += row.props
            """,
            rows=[{"uid": uid, "props": props} for uid, props in graph["skills"].items()],
        )

        tx.run(
            """
            UNWIND $rows AS row
            MERGE (c:Course {uid: row.uid})
            SET c += row.props
            """,
            rows=[{"uid": p["uid"], "props": p} for p in graph["courses"].values()],
        )

        tx.run(
            """
            UNWIND $rows AS row
            MERGE (p:Project {uid: row.uid})
            SET p += row.props
            """,
            rows=[{"uid": p["uid"], "props": p} for p in graph["projects"].values()],
        )

        tx.run(
            """
            UNWIND $rows AS row
            MERGE (a:Accomplishment {uid: row.uid})
            SET a += row.props
            """,
            rows=[{"uid": p["uid"], "props": p} for p in graph["accomplishments"].values()],
        )

        # --- Relationships -------------------------------------------------
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (s:Skill {uid: row.from}), (c:Course {uid: row.to})
            MERGE (s)-[:LEARNED_IN]->(c)
            """,
            rows=graph["rel_skill_learned_in"],
        )
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (a:Accomplishment {uid: row.from}), (s:Skill {uid: row.to})
            MERGE (a)-[:USING]->(s)
            """,
            rows=graph["rel_acc_using_skill"],
        )
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (a:Accomplishment {uid: row.from}), (p:Project {uid: row.to})
            MERGE (a)-[:GAINED_IN]->(p)
            """,
            rows=graph["rel_acc_gained_in"],
        )

        # --- Candidate anchor relationships (schema extension) -------------
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (c:Candidate {candidate_id: row.from}), (s:Skill {uid: row.to})
            MERGE (c)-[:HAS_SKILL]->(s)
            """,
            rows=graph["rel_candidate_skill"],
        )
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (c:Candidate {candidate_id: row.from}), (n:Course {uid: row.to})
            MERGE (c)-[:COMPLETED]->(n)
            """,
            rows=graph["rel_candidate_course"],
        )
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (c:Candidate {candidate_id: row.from}), (n:Project {uid: row.to})
            MERGE (c)-[:WORKED_ON]->(n)
            """,
            rows=graph["rel_candidate_project"],
        )
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (c:Candidate {candidate_id: row.from}), (n:Accomplishment {uid: row.to})
            MERGE (c)-[:ACHIEVED]->(n)
            """,
            rows=graph["rel_candidate_acc"],
        )
