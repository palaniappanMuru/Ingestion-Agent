"""LLM-backed CV extraction using structured outputs.

One call per CV: the raw text goes in, a schema-validated `ExtractedCV` comes
out. We use LangChain's `init_chat_model(...).with_structured_output(ExtractedCV)`
so the model is constrained to our Pydantic schema and we never hand-parse JSON.

The provider is whatever `Settings.extraction_model` says (e.g.
"google_genai:gemini-2.5-flash" or "anthropic:claude-opus-4-8") — switching
providers is a one-line config change, not a code change.
"""

from __future__ import annotations

from langchain.chat_models import init_chat_model

from .config import Settings
from .models import ExtractedCV

_PROVIDER_API_KEYS = {
    "anthropic": "anthropic_api_key",
    "google_genai": "google_api_key",
}

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
        provider = settings.extraction_model.split(":", 1)[0]
        api_key_field = _PROVIDER_API_KEYS.get(provider)
        api_key = getattr(settings, api_key_field) if api_key_field else None
        base_llm = init_chat_model(
            settings.extraction_model,
            max_tokens=settings.extraction_max_tokens,
            api_key=api_key,
        )

        # with_structured_output must be applied to the chat model before with_retry,
        # since RunnableRetry (the wrapper with_retry returns) has no with_structured_output.
        self._structured_llm = base_llm.with_structured_output(ExtractedCV).with_retry(
            retry_if_exception_type=(Exception,),
            stop_after_attempt=5,
            wait_exponential_jitter=True,
        )

    def extract(self, cv_text: str) -> ExtractedCV:
        result = self._structured_llm.invoke(
            [
                ("system", _SYSTEM_PROMPT),
                ("user", _USER_TEMPLATE.format(cv_text=cv_text)),
            ]
        )
        if not isinstance(result, ExtractedCV):
            raise RuntimeError(f"Extraction returned unexpected type: {type(result)!r}")
        return result
