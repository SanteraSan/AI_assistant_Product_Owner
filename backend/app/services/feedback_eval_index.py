"""Eval collection payload and H0/H1 retrieval for the feedback summary.

The product collection is never the target. Retrieval calls ``QdrantStore.search``
directly and does not use ``RagService``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from app.clients.qdrant_store import QdrantStore
from app.models.chat import SourceChunk
from app.services.feedback_summary_score import RetrievedSource

EVAL_COLLECTION_NAME: str = "feedback_eval_v1"
EVAL_TENANT_ID: str = "feedback_eval"
EVAL_BUCKET_ID: str = "feedback_eval_v1"
EVAL_TOP_K: int = 5
EVAL_TEMPERATURE: float = 0.1
EVAL_TOP_P: float = 0.9
EVAL_REPEATS: int = 5
EVAL_NUM_CTX: int = 16384
EVAL_KEEP_ALIVE: str = "10m"
REQUIRED_CHAT_MODEL: str = "qwen3.8:latest"
REQUIRED_EMBEDDING_MODEL: str = "nomic-embed-text"
EXPECTED_VECTOR_SIZE: int = 768
EXPECTED_CORPUS_ROWS: int = 510


def assert_eval_collection_is_not_product(
    *,
    collection_name: str,
    product_collection: str,
) -> None:
    """Reject an empty name, the product collection, and the name ``documents``."""

    if not collection_name.strip() or collection_name == product_collection or collection_name == "documents":
        raise ValueError(
            f"refusing to recreate collection {collection_name!r}; "
            "the eval collection must not be the product collection"
        )


def build_eval_point_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    """Payload for one cleaned row. ``index_in_rag`` is copied, not recomputed.

    ``content`` is the masked ``index_text``. An empty body becomes ``.`` so the
    embedding call still has text. The raw ``text`` field is not stored.
    """

    corpus_id = row.get("corpus_id")
    rule_class = row.get("rule_class")
    index_in_rag = row.get("index_in_rag")
    if not isinstance(corpus_id, str) or not corpus_id:
        raise ValueError("eval row corpus_id is empty")
    if not isinstance(rule_class, str) or not rule_class:
        raise ValueError(f"{corpus_id} rule_class is empty")
    if not isinstance(index_in_rag, bool):
        raise ValueError(f"{corpus_id} index_in_rag is not a bool")
    index_text = row.get("index_text")
    if index_text is None:
        body = ""
    elif isinstance(index_text, str):
        body = index_text
    else:
        raise ValueError(f"{corpus_id} index_text is not a string")
    if body.strip():
        content = body
        embedded_placeholder = False
    else:
        content = "."
        embedded_placeholder = True
    scenario = row.get("scenario_id")
    if scenario is None:
        scenario_id = ""
    elif isinstance(scenario, str):
        scenario_id = scenario
    else:
        raise ValueError(f"{corpus_id} scenario_id is not a string")
    return {
        "tenant_id": EVAL_TENANT_ID,
        "bucket_id": EVAL_BUCKET_ID,
        "document_id": corpus_id,
        "chunk_id": corpus_id,
        "corpus_id": corpus_id,
        "source_type": "feedback",
        "source_path": f"feedback:{corpus_id}",
        "title": corpus_id,
        "content": content,
        "embedded_placeholder": embedded_placeholder,
        "feature": [],
        "feedback_class": rule_class,
        "scenario_id": scenario_id,
        "index_in_rag": index_in_rag,
        "language": "ru",
        "synthetic": True,
    }


def eval_point_id(corpus_id: str) -> str:
    """Stable point id for one corpus row in the eval collection."""

    return str(uuid5(NAMESPACE_URL, f"feedback-eval-v1:{corpus_id}"))


def arm_index_filter(arm: Literal["H0", "H1"]) -> bool | None:
    """H0 does not filter the flag. H1 keeps points with ``index_in_rag`` true."""

    if arm == "H0":
        return None
    if arm == "H1":
        return True
    raise ValueError(f"unknown eval arm {arm!r}")


def retrieve_arm(
    store: QdrantStore,
    *,
    arm: Literal["H0", "H1"],
    query_vector: list[float],
    tenant_id: str,
    bucket_id: str,
    top_k: int,
) -> list[SourceChunk]:
    """Search one arm. No feature filter, source type, score threshold, or RagService."""

    return store.search(
        query_vector,
        top_k,
        tenant_id,
        [bucket_id],
        index_in_rag=arm_index_filter(arm),
    )


def retrieved_source_from_chunk(chunk: SourceChunk) -> RetrievedSource:
    """Map a hit to a score row. An empty scenario id becomes None."""

    metadata = chunk.metadata
    raw_scenario = metadata.get("scenario_id")
    if not isinstance(raw_scenario, str) or not raw_scenario.strip():
        scenario_id = None
    else:
        scenario_id = raw_scenario
    raw_corpus = metadata.get("corpus_id")
    corpus_id = raw_corpus if isinstance(raw_corpus, str) else ""
    return RetrievedSource(
        corpus_id=corpus_id,
        scenario_id=scenario_id,
        index_in_rag=metadata.get("index_in_rag") is True,
        content=chunk.content,
    )
