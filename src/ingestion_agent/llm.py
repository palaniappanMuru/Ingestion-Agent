"""Claude-backed CV extraction using structured outputs.

One call per CV: the raw text goes in, a schema-validated `ExtractedCV` comes
out. We use `client.messages.parse(..., output_format=ExtractedCV)` so the model
is constrained to our Pydantic schema and we never hand-parse JSON.
"""

from __future__ import annotations

import anthropic

from .config import Settings
from .models import ExtractedCV

_SYSTEM_PROMPT = """\
You are an expert technical recruiter and information-extraction engine. You are \
given the raw text of one candidate's CV / resume. Extract a structured talent \
profile.

Rules:
- Extract skills as distinct, canonical entities. Classify each as 'Tech' \
(technical/tooling) or 'Mgmt' (leadership, people, process, strategy). Infer an \
expertise level from seniority and context; use 'Intermediate' when unsure.
- Treat each role / engagement / position as a Project (name it by role+company \
when there is no explicit project name).
- Extract each bullet-point achievement as one Accomplishment. Capture any \
measurable result in 'quantitative_achievement'.
- Cross-reference by NAME: for every accomplishment, list the skills it \
demonstrates ('skills_used') and the project it occurred in ('project_name'); \
for every course/certification, list the skills it taught ('skills_learned'). \
These names MUST exactly match names you put in the skills/projects lists.
- Do not invent facts. Use empty strings / empty lists when something is absent.
"""

_USER_TEMPLATE = "Extract the structured profile from this CV:\n\n<cv>\n{cv_text}\n</cv>"


class CVExtractor:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def extract(self, cv_text: str) -> ExtractedCV:
        response = self._client.messages.parse(
            model=self._settings.extraction_model,
            max_tokens=self._settings.extraction_max_tokens,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _USER_TEMPLATE.format(cv_text=cv_text)}],
            output_format=ExtractedCV,
        )
        parsed = response.parsed_output
        if parsed is None:
            raise RuntimeError(
                f"Extraction returned no parsed output (stop_reason={response.stop_reason})."
            )
        return parsed
