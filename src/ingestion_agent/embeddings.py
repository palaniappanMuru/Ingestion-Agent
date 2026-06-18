"""Voyage AI embedding client.

Anthropic has no embeddings endpoint and recommends Voyage AI. The model and
dimension are configurable; `document` input type is used since we embed stored
nodes (use `query` at search time).
"""

from __future__ import annotations

import voyageai

from .config import Settings

# Voyage caps batch size; chunk to stay well under it.
_BATCH_SIZE = 128


class Embedder:
    def __init__(self, settings: Settings) -> None:
        self._model = settings.embedding_model
        self._client = voyageai.Client(api_key=settings.voyage_api_key)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts, preserving order. Returns one vector per text."""
        if not texts:
            return []

        vectors: list[list[float]] = []
        for start in range(0, len(texts), _BATCH_SIZE):
            batch = texts[start : start + _BATCH_SIZE]
            result = self._client.embed(batch, model=self._model, input_type="document")
            vectors.extend(result.embeddings)
        return vectors
