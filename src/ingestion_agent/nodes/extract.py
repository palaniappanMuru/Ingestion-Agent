"""extract: Claude turns each CV's raw text into a structured ExtractedCV."""

from __future__ import annotations

import logging

from ..config import Settings
from ..llm import CVExtractor
from ..state import IngestionState

log = logging.getLogger(__name__)


def extract_entities(state: IngestionState) -> IngestionState:
    settings = Settings.load()
    extractor = CVExtractor(settings)

    extracted: list[dict] = []
    errors: list[str] = list(state.get("errors", []))

    for doc in state["documents"]:
        try:
            cv = extractor.extract(doc["text"])
            extracted.append(
                {
                    "path": doc["path"],
                    "candidate_id": doc["candidate_id"],
                    "filename": doc["filename"],
                    "cv": cv.model_dump(),
                }
            )
            log.info(
                "Extracted %s: %d skills, %d courses, %d projects, %d accomplishments",
                doc["filename"],
                len(cv.skills),
                len(cv.courses),
                len(cv.projects),
                len(cv.accomplishments),
            )
        except Exception as exc:
            log.exception("Extraction failed for %s", doc["filename"])
            errors.append(f"{doc['filename']}: extraction error: {exc}")

    stats = {**state.get("stats", {}), "cvs_extracted": len(extracted)}
    return {"extracted": extracted, "errors": errors, "stats": stats}
