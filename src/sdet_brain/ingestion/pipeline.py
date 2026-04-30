"""End-to-end ingestion pipeline.

`ingest_path` walks a file or directory, runs each ``.md`` file through
the parser/chunker/embedder/storage layers, and reports
:class:`IngestStats`. Re-ingestion is idempotent: an unchanged
``content_hash`` short-circuits the file unless ``force_reindex`` is
set.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final

from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
)

from sdet_brain.ingestion.document_parser import parse_markdown
from sdet_brain.ingestion.models import Chunk, ParsedDocument
from sdet_brain.ingestion.source_classifier import SourceConfig, classify_source
from sdet_brain.storage.collections import COLLECTION_NAME, utc_now_iso

if TYPE_CHECKING:
    from sdet_brain.embeddings.protocol import IEmbedder
    from sdet_brain.storage.qdrant_client import QdrantStorage

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE: Final[int] = 32
CHUNK_NAMESPACE: Final[uuid.UUID] = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://sdet-brain/chunks"
)


@dataclass
class IngestStats:
    """Aggregate counters returned by `ingest_path`."""

    files_processed: int = 0
    files_skipped: int = 0
    chunks_created: int = 0
    chunks_replaced: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"Processed {self.files_processed} files, "
            f"created {self.chunks_created} chunks, "
            f"skipped {self.files_skipped} files (cache), "
            f"replaced {self.chunks_replaced} chunks"
            + (f", {len(self.errors)} errors" if self.errors else "")
        )


def _iter_markdown_files(root: Path) -> Iterator[Path]:
    """Yield ``.md`` files under ``root`` (or just ``root`` itself)."""
    if root.is_file():
        if root.suffix.lower() == ".md":
            yield root
        return
    for path in sorted(root.rglob("*.md")):
        if any(part.startswith(".") for part in path.parts):
            continue
        yield path


def _chunk_point_id(source_path: str, chunk_index: int) -> str:
    return str(uuid.uuid5(CHUNK_NAMESPACE, f"{source_path}#{chunk_index}"))


def _existing_hash(
    storage: QdrantStorage, collection: str, source_path: str
) -> str | None:
    """Return the ``content_hash`` of any chunk currently stored for ``source_path``."""
    points, _ = storage.client.scroll(
        collection_name=collection,
        scroll_filter=Filter(
            must=[FieldCondition(key="source_path", match=MatchValue(value=source_path))]
        ),
        limit=1,
        with_payload=True,
        with_vectors=False,
    )
    if not points:
        return None
    payload = points[0].payload or {}
    value = payload.get("content_hash")
    return value if isinstance(value, str) else None


def _delete_existing_chunks(
    storage: QdrantStorage, collection: str, source_path: str
) -> None:
    storage.delete_by_filter(
        collection,
        Filter(
            must=[FieldCondition(key="source_path", match=MatchValue(value=source_path))]
        ),
    )


def _build_payload(
    document: ParsedDocument,
    chunk: Chunk,
    source_type: str,
    created_at: str,
) -> dict[str, object]:
    return {
        "source_path": document.source_path,
        "source_type": source_type,
        "chunk_index": chunk.chunk_index,
        "total_chunks": chunk.total_chunks,
        "heading_path": chunk.heading_path,
        "has_code": chunk.has_code,
        "char_count": chunk.char_count,
        "token_estimate": chunk.token_estimate,
        "frontmatter": dict(document.frontmatter),
        "content_hash": document.content_hash,
        "created_at": created_at,
    }


def _embed_in_batches(
    embedder: IEmbedder,
    chunks: tuple[Chunk, ...],
    batch_size: int,
) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        vectors.extend(embedder.embed([chunk.text for chunk in batch]))
    return vectors


def _ingest_document(
    document: ParsedDocument,
    storage: QdrantStorage,
    embedder: IEmbedder,
    collection: str,
    source_type: str,
    batch_size: int,
    *,
    force_reindex: bool,
    stats: IngestStats,
) -> None:
    if not document.chunks:
        stats.files_skipped += 1
        return

    existing = _existing_hash(storage, collection, document.source_path)
    if not force_reindex and existing == document.content_hash:
        stats.files_skipped += 1
        return

    if existing is not None:
        _delete_existing_chunks(storage, collection, document.source_path)
        stats.chunks_replaced += 1

    vectors = _embed_in_batches(embedder, document.chunks, batch_size)
    if len(vectors) != len(document.chunks):
        raise RuntimeError(
            f"Embedder returned {len(vectors)} vectors for "
            f"{len(document.chunks)} chunks - aborting upsert."
        )

    created_at = utc_now_iso()
    points = [
        PointStruct(
            id=_chunk_point_id(document.source_path, chunk.chunk_index),
            vector=vectors[idx],
            payload=_build_payload(document, chunk, source_type, created_at),
        )
        for idx, chunk in enumerate(document.chunks)
    ]
    storage.upsert_points(collection, points)
    stats.chunks_created += len(points)
    stats.files_processed += 1


def ingest_path(
    path: Path,
    storage: QdrantStorage,
    embedder: IEmbedder,
    *,
    source_config: SourceConfig | None = None,
    collection: str = COLLECTION_NAME,
    batch_size: int = DEFAULT_BATCH_SIZE,
    force_reindex: bool = False,
    progress: Iterator[Path] | None = None,
) -> IngestStats:
    """Walk ``path`` and ingest every Markdown file beneath it.

    Parameters
    ----------
    path:
        File or directory.
    storage:
        Configured `QdrantStorage`.
    embedder:
        Provider compatible with `IEmbedder`.
    source_config:
        Optional path heuristics for `classify_source`. Files outside
        all registered roots are tagged ``unknown``.
    collection:
        Target collection name.
    batch_size:
        Number of chunks per embedding call.
    force_reindex:
        When True, ignore the cached `content_hash` and re-embed every
        file regardless.
    progress:
        Optional iterable wrapper (e.g. `tqdm`) used for visible
        progress reporting. The CLI passes `tqdm` here; tests pass
        ``None``.
    """
    config = source_config or SourceConfig()
    files = list(_iter_markdown_files(path))
    iterator: Iterator[Path] = progress if progress is not None else iter(files)

    stats = IngestStats()
    for file_path in iterator:
        try:
            document = parse_markdown(file_path)
            source_type = classify_source(file_path, config)
            _ingest_document(
                document,
                storage,
                embedder,
                collection,
                source_type,
                batch_size,
                force_reindex=force_reindex,
                stats=stats,
            )
        except Exception as exc:
            # Per-file failures must not abort the whole walk - record
            # the error and keep going so a single malformed file does
            # not freeze a long ingest.
            logger.exception("Failed to ingest %s", file_path)
            stats.errors.append((str(file_path), str(exc)))
    return stats
