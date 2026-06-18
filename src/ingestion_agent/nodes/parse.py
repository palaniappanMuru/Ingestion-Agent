"""parse: extract raw text from each discovered document.

A stable `candidate_id` is derived from the filename so re-ingesting the same
file updates the same Candidate node rather than creating a new one.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from ..state import IngestionState

log = logging.getLogger(__name__)


def _candidate_id(path: Path) -> str:
    digest = hashlib.sha1(path.stem.lower().encode("utf-8")).hexdigest()[:12]
    return f"cand::{digest}"


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _read_docx(path: Path) -> str:
    import docx2txt

    return docx2txt.process(str(path)) or ""


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


_READERS = {".pdf": _read_pdf, ".docx": _read_docx, ".txt": _read_text, ".md": _read_text}


def parse_documents(state: IngestionState) -> IngestionState:
    documents: list[dict] = []
    errors: list[str] = list(state.get("errors", []))

    for file_str in state["files"]:
        path = Path(file_str)
        reader = _READERS.get(path.suffix.lower())
        if reader is None:  # defensive; discover already filtered
            continue
        try:
            text = reader(path).strip()
            if not text:
                errors.append(f"{path.name}: no extractable text")
                continue
            documents.append(
                {"path": str(path), "candidate_id": _candidate_id(path), "filename": path.name, "text": text}
            )
        except Exception as exc:  # keep going on a bad file
            log.exception("Failed to parse %s", path.name)
            errors.append(f"{path.name}: parse error: {exc}")

    log.info("Parsed %d document(s)", len(documents))
    stats = {**state.get("stats", {}), "documents_parsed": len(documents)}
    return {"documents": documents, "errors": errors, "stats": stats}
