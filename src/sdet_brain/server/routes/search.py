"""Dense-vector search endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field
from qdrant_client.models import FieldCondition, Filter, MatchValue

from sdet_brain.embeddings.protocol import IEmbedder
from sdet_brain.server.dependencies import require_embedder, require_storage
from sdet_brain.storage.collections import COLLECTION_NAME
from sdet_brain.storage.qdrant_client import QdrantStorage

router = APIRouter()


class SearchRequest(BaseModel):
    query: Annotated[str, Field(min_length=1)]
    limit: Annotated[int, Field(ge=1, le=50)] = 10
    source_type_filter: str | None = None
    score_threshold: float | None = None


class SearchResultItem(BaseModel):
    id: str
    score: float
    source_path: str
    source_type: str | None
    heading_path: str | None
    text: str
    chunk_index: int | None
    total_chunks: int | None


class SearchResponse(BaseModel):
    query: str
    count: int
    results: list[SearchResultItem]


def _build_filter(source_type_filter: str | None) -> Filter | None:
    if not source_type_filter:
        return None
    return Filter(
        must=[
            FieldCondition(key="source_type", match=MatchValue(value=source_type_filter))
        ]
    )


@router.post("/search", response_model=SearchResponse, tags=["search"])
def post_search(
    body: Annotated[SearchRequest, Body()],
    storage: QdrantStorage = Depends(require_storage),
    embedder: IEmbedder = Depends(require_embedder),
) -> SearchResponse:
    vectors = embedder.embed([body.query])
    if not vectors:
        return SearchResponse(query=body.query, count=0, results=[])
    points = storage.search(
        collection=COLLECTION_NAME,
        query_vector=vectors[0],
        limit=body.limit,
        query_filter=_build_filter(body.source_type_filter),
        score_threshold=body.score_threshold,
    )

    items: list[SearchResultItem] = []
    for point in points:
        payload = point.payload or {}
        items.append(
            SearchResultItem(
                id=str(point.id),
                score=float(point.score),
                source_path=str(payload.get("source_path", "")),
                source_type=payload.get("source_type") if isinstance(payload.get("source_type"), str) else None,
                heading_path=payload.get("heading_path") if isinstance(payload.get("heading_path"), str) else None,
                text=str(payload.get("text", "")),
                chunk_index=payload.get("chunk_index") if isinstance(payload.get("chunk_index"), int) else None,
                total_chunks=payload.get("total_chunks") if isinstance(payload.get("total_chunks"), int) else None,
            )
        )
    return SearchResponse(query=body.query, count=len(items), results=items)
