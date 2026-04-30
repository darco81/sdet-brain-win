"""Collection statistics endpoint."""

from __future__ import annotations

from collections import Counter
from typing import Any, Final

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from sdet_brain.server.dependencies import require_storage
from sdet_brain.storage.collections import COLLECTION_NAME
from sdet_brain.storage.qdrant_client import QdrantStorage

router = APIRouter()
SCROLL_PAGE_SIZE: Final[int] = 256


class StatusResponse(BaseModel):
    collection_name: str
    total_chunks: int
    vector_size: int
    distance: str
    source_type_breakdown: dict[str, int]
    last_ingestion_at: str | None


def _source_type_breakdown(
    storage: QdrantStorage, collection: str
) -> tuple[dict[str, int], str | None]:
    """Walk every payload and count source_type tags + track newest created_at."""
    counter: Counter[str] = Counter()
    latest: str | None = None
    # `qdrant-client` scroll returns the next-page offset typed as
    # ``int | str | UUID | PointId | None``; we round-trip it opaquely.
    offset: Any = None
    while True:
        page, offset = storage.client.scroll(
            collection_name=collection,
            limit=SCROLL_PAGE_SIZE,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in page:
            payload = point.payload or {}
            source_type = payload.get("source_type")
            if isinstance(source_type, str):
                counter[source_type] += 1
            created_at = payload.get("created_at")
            if isinstance(created_at, str) and (latest is None or created_at > latest):
                latest = created_at
        if offset is None:
            break
    return dict(counter), latest


@router.get("/status", response_model=StatusResponse, tags=["meta"])
def get_status(storage: QdrantStorage = Depends(require_storage)) -> StatusResponse:
    if not storage.collection_exists(COLLECTION_NAME):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Collection {COLLECTION_NAME!r} does not exist.",
        )
    snapshot = storage.status(COLLECTION_NAME)
    breakdown, last_ingestion_at = _source_type_breakdown(storage, COLLECTION_NAME)
    return StatusResponse(
        collection_name=snapshot.name,
        total_chunks=snapshot.points_count,
        vector_size=snapshot.vector_size,
        distance=snapshot.distance,
        source_type_breakdown=breakdown,
        last_ingestion_at=last_ingestion_at,
    )
