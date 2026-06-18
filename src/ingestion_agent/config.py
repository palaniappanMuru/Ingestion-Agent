"""Configuration loaded from environment / .env.

All secrets and locations (Neo4j connection, API keys, CV folder, model names)
live here so nothing sensitive is hard-coded. See `.env.example`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load the project-root .env once on import. Explicit path so it works no matter
# which directory the process is launched from.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Required environment variable {name!r} is not set. "
            f"Copy .env.example to .env and fill it in."
        )
    return value


@dataclass(frozen=True)
class Settings:
    # CV source
    cv_folder: Path

    # Claude / extraction
    anthropic_api_key: str
    extraction_model: str
    extraction_max_tokens: int

    # Voyage / embeddings
    voyage_api_key: str
    embedding_model: str
    embedding_dim: int

    # Neo4j
    neo4j_uri: str
    neo4j_username: str
    neo4j_password: str
    neo4j_database: str

    @classmethod
    def load(cls, *, require_secrets: bool = True) -> "Settings":
        """Build settings from the environment.

        `require_secrets=False` lets `--dry-run` proceed without Neo4j/API keys
        configured (the nodes that need them simply won't run, or will be given
        placeholder values that are never used).
        """
        getter = _require if require_secrets else (lambda n: os.getenv(n, ""))

        cv_folder = Path(os.getenv("CV_FOLDER", "./data/cvs"))
        if not cv_folder.is_absolute():
            cv_folder = (_PROJECT_ROOT / cv_folder).resolve()

        return cls(
            cv_folder=cv_folder,
            anthropic_api_key=getter("ANTHROPIC_API_KEY"),
            extraction_model=os.getenv("EXTRACTION_MODEL", "claude-opus-4-8"),
            extraction_max_tokens=int(os.getenv("EXTRACTION_MAX_TOKENS", "8000")),
            voyage_api_key=getter("VOYAGE_API_KEY"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "voyage-3.5"),
            embedding_dim=int(os.getenv("EMBEDDING_DIM", "1024")),
            neo4j_uri=getter("NEO4J_URI"),
            neo4j_username=getter("NEO4J_USERNAME"),
            neo4j_password=getter("NEO4J_PASSWORD"),
            neo4j_database=os.getenv("NEO4J_DATABASE", "neo4j"),
        )
