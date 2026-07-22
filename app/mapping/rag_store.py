"""ChromaDB-backed memory for field mapping.

Two collections:
  - "canonical_schema": one entry per canonical field, embedding its
    human-readable description. This is the RAG context the LLM is grounded
    in when guessing a mapping.
  - "field_mappings": one entry per (source, field_name) the mapper has
    already resolved, so repeat batches from the same source reuse a past
    decision instead of re-asking the LLM every time -- this is how mapping
    "improves over time" as required by the brief.

Embeddings are produced by the local Ollama `nomic-embed-text` model. If
Ollama isn't running, we transparently fall back to Chroma's bundled
default embedding function so schema profiling still works end-to-end
without any external service.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Callable, TypeVar

import chromadb
from chromadb.errors import InvalidDimensionException
from chromadb.utils import embedding_functions

from app.mapping.llm_client import OllamaUnavailable, embed
from app.schema.canonical import CANONICAL_FIELD_DESCRIPTIONS
from app.utils.config import settings

T = TypeVar("T")

# Sentinel stored in the mapping cache for a field the mapper resolved to "no
# canonical target" (e.g. a "Company" column the schema has no home for). We
# cache this exactly like a real hit so a column with no mapping isn't sent to
# the LLM on every future upload -- the single biggest repeat-upload latency
# win. lookup returns it verbatim; the mapper translates it back to None.
UNKNOWN_MAPPING = "__unknown__"


class OllamaEmbeddingFunction(embedding_functions.EmbeddingFunction):
    """Chroma embedding function backed by Ollama, falling back to Chroma's
    local default (ONNX MiniLM) model if Ollama can't be reached."""

    def __init__(self) -> None:
        self._fallback = embedding_functions.DefaultEmbeddingFunction()

    def __call__(self, input: list[str]) -> list[list[float]]:
        try:
            # embed()'s 15s default is tuned for an already-warm model --
            # if Ollama's idle timeout unloaded nomic-embed-text since the
            # last call, a cold reload can exceed that (same class of bug
            # fixed for the mapping LLM call in mapper.py, just a smaller
            # model here). A spurious timeout here isn't just slow: it
            # falls through to the ONNX fallback below, which -- if this
            # is a fresh container/volume that's never cached it -- has
            # to download a real model file over the network, and that
            # download blocking the single API worker (confirmed live:
            # stalled at ~30-50KB/s, would have taken 25+ minutes) is far
            # worse than just waiting a bit longer for Ollama.
            return [embed(text, timeout=60.0) for text in input]
        except OllamaUnavailable:
            return self._fallback(input)


@lru_cache(maxsize=1)
def get_client() -> chromadb.ClientAPI:
    if os.getenv("CHROMA_HOST"):
        return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
    return chromadb.PersistentClient(path=settings.chroma_persist_dir)


@lru_cache(maxsize=1)
def get_embedding_fn() -> OllamaEmbeddingFunction:
    return OllamaEmbeddingFunction()


def get_canonical_schema_collection():
    client = get_client()
    collection = client.get_or_create_collection(
        "canonical_schema", embedding_function=get_embedding_fn()
    )
    if collection.count() == 0:
        collection.add(
            ids=list(CANONICAL_FIELD_DESCRIPTIONS.keys()),
            documents=list(CANONICAL_FIELD_DESCRIPTIONS.values()),
            metadatas=[{"field": f} for f in CANONICAL_FIELD_DESCRIPTIONS],
        )
    return collection


def get_field_mappings_collection():
    client = get_client()
    return client.get_or_create_collection(
        "field_mappings", embedding_function=get_embedding_fn()
    )


def _with_dimension_recovery(collection_name: str, operation: Callable[[], T]) -> T:
    """A Chroma collection is permanently bound to whichever embedding
    dimension it saw on its first write -- if Ollama was even momentarily
    unreachable the first time this collection was touched,
    OllamaEmbeddingFunction transparently fell back to Chroma's bundled
    384-dim ONNX model instead of nomic-embed-text's 768-dim, and the
    collection is stuck at 384 from then on. Ollama coming back online
    doesn't fix this -- every real embedding call afterwards raises
    InvalidDimensionException forever, which (confirmed live) silently
    degrades every mapping decision to the heuristic fallback instead of
    the LLM+RAG path, with no visible error.

    Rebuilding the collection from scratch and retrying once is cheap
    (`canonical_schema` reseeds itself; `field_mappings` just loses its
    cached decisions, which get re-learned on the next resolution) and
    turns a permanent, silent quality regression into a one-time retry --
    the same self-healing instinct this whole project is built around,
    just applied to the RAG layer instead of the cleaning layer."""
    try:
        return operation()
    except InvalidDimensionException:
        get_client().delete_collection(collection_name)
        return operation()


def lookup_known_mapping(source: str, field_name: str) -> str | None:
    """Exact-match lookup: has this (source, field_name) pair already been
    mapped before? Returns the canonical field name, or None."""
    result = _with_dimension_recovery(
        "field_mappings",
        lambda: get_field_mappings_collection().get(ids=[f"{source}:{field_name}"]),
    )
    if result["ids"]:
        return result["metadatas"][0]["canonical_field"]
    return None


def remember_mapping(source: str, field_name: str, canonical_field: str, sample_value: str) -> None:
    _with_dimension_recovery(
        "field_mappings",
        lambda: get_field_mappings_collection().upsert(
            ids=[f"{source}:{field_name}"],
            documents=[f"{field_name}: {sample_value}"],
            metadatas=[{"source": source, "field_name": field_name, "canonical_field": canonical_field}],
        ),
    )


def query_similar_canonical_fields(field_name: str, sample_value: str, top_k: int = 3) -> list[dict]:
    result = _with_dimension_recovery(
        "canonical_schema",
        lambda: get_canonical_schema_collection().query(
            query_texts=[f"{field_name}: {sample_value}"],
            n_results=top_k,
        ),
    )
    return [
        {"field": meta["field"], "description": doc}
        for meta, doc in zip(result["metadatas"][0], result["documents"][0])
    ]
