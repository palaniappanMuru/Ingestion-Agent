"""discover: scan the CV folder for supported files."""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import SUPPORTED_EXTENSIONS
from ..state import IngestionState

log = logging.getLogger(__name__)


def discover_files(state: IngestionState) -> IngestionState:
    folder = Path(state["cv_folder"])
    if not folder.is_dir():
        raise FileNotFoundError(f"CV folder does not exist: {folder}")

    files = sorted(
        str(p)
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )
    skipped = [p.name for p in folder.iterdir() if p.is_file() and p.suffix.lower() not in SUPPORTED_EXTENSIONS]
    if skipped:
        log.info("Skipping %d unsupported file(s): %s", len(skipped), ", ".join(skipped))

    log.info("Discovered %d CV file(s) in %s", len(files), folder)
    return {"files": files, "stats": {"files_discovered": len(files)}, "errors": []}
