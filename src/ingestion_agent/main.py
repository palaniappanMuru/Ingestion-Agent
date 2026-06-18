"""CLI entrypoint for the CV ingestion agent.

    python -m ingestion_agent.main                       # use CV_FOLDER from .env
    python -m ingestion_agent.main --folder /path/to/cvs
    python -m ingestion_agent.main --dry-run             # skip the Neo4j write

`--dry-run` runs discover -> parse -> extract -> deduplicate -> embed but does
not write to Neo4j, which is handy for verifying extraction without a database.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import Settings
from .graph import build_graph
from .state import IngestionState


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ingestion_agent",
        description="Ingest a folder of CVs into a Neo4j talent graph.",
    )
    parser.add_argument(
        "--folder",
        default=None,
        help="Folder of CVs to ingest. Defaults to CV_FOLDER from .env.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the full pipeline but skip the Neo4j write.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO).",
    )
    return parser.parse_args(argv)


def _summarize(state: IngestionState) -> None:
    stats = state.get("stats", {})
    errors = state.get("errors", [])

    print("\n=== Ingestion summary ===")
    for key in (
        "files_discovered",
        "documents_parsed",
        "cvs_extracted",
        "unique_skills",
        "unique_courses",
        "unique_projects",
        "unique_accomplishments",
        "nodes_embedded",
    ):
        if key in stats:
            print(f"  {key.replace('_', ' '):>24}: {stats[key]}")

    if stats.get("written"):
        print(f"  {'written to neo4j':>24}: yes")
    elif "written" in stats:
        print(f"  {'written to neo4j':>24}: no (dry-run or write skipped)")

    if errors:
        print(f"\n  {len(errors)} error(s):")
        for err in errors:
            print(f"    - {err}")
    else:
        print("\n  No errors.")


def run(folder: str | None = None, dry_run: bool = False) -> IngestionState:
    """Run the pipeline programmatically. Returns the final state."""
    # Resolve the CV folder: explicit arg wins, else the configured default.
    # require_secrets=False so a dry-run works without API keys / Neo4j set.
    settings = Settings.load(require_secrets=False)
    cv_folder = folder or str(settings.cv_folder)

    app = build_graph()
    initial: IngestionState = {"cv_folder": cv_folder, "dry_run": dry_run}
    return app.invoke(initial)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    try:
        final_state = run(folder=args.folder, dry_run=args.dry_run)
    except Exception as exc:
        logging.getLogger(__name__).exception("Ingestion failed")
        print(f"\nIngestion failed: {exc}", file=sys.stderr)
        return 1

    _summarize(final_state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
