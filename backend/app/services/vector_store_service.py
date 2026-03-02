import logging
import uuid

from qdrant_client import AsyncQdrantClient, models

from app.config import get_settings
from app.exceptions import VectorStoreError

logger = logging.getLogger(__name__)


class VectorStoreService:
    """Qdrant vector store operations with hybrid (dense + sparse) support."""

    def __init__(self, client: AsyncQdrantClient):
        self.client = client
        settings = get_settings()
        self.dense_dimension = settings.embedding_dimension

    async def create_collection(self, collection_name: str) -> None:
        """Create a Qdrant collection with dual dense + sparse vector config."""
        try:
            exists = await self.client.collection_exists(collection_name)
            if exists:
                logger.info(f"Collection '{collection_name}' already exists, skipping creation")
                return

            await self.client.create_collection(
                collection_name=collection_name,
                vectors_config={
                    "dense": models.VectorParams(
                        size=self.dense_dimension,
                        distance=models.Distance.COSINE,
                    ),
                },
                sparse_vectors_config={
                    "sparse": models.SparseVectorParams(
                        modifier=models.Modifier.IDF,
                    ),
                    "bm25": models.SparseVectorParams(
                        modifier=models.Modifier.IDF,
                    ),
                },
            )
            logger.info(f"Created hybrid collection '{collection_name}'")
        except Exception as e:
            raise VectorStoreError(f"Failed to create collection: {e}") from e

    async def delete_collection(self, collection_name: str) -> None:
        """Delete a Qdrant collection."""
        try:
            await self.client.delete_collection(collection_name)
            logger.info(f"Deleted collection '{collection_name}'")
        except Exception as e:
            raise VectorStoreError(f"Failed to delete collection: {e}") from e

    async def delete_by_doc_id(self, collection_name: str, doc_id: str) -> None:
        """Delete all points belonging to a document (by doc_id filter)."""
        try:
            await self.client.delete(
                collection_name=collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="doc_id",
                                match=models.MatchValue(value=doc_id),
                            )
                        ]
                    )
                ),
            )
            logger.info(f"Deleted vectors for doc_id={doc_id} from '{collection_name}'")
        except Exception as e:
            raise VectorStoreError(f"Failed to delete by doc_id: {e}") from e

    async def upsert_points(
        self,
        collection_name: str,
        dense_vectors: list[list[float]],
        sparse_vectors: list[dict],
        payloads: list[dict],
        bm25_vectors: list[dict] | None = None,
    ) -> None:
        """Upsert points with dense + sparse + optional BM25 vectors and metadata payloads."""
        if not dense_vectors:
            return

        points = []
        for i, (dense, sparse, payload) in enumerate(
            zip(dense_vectors, sparse_vectors, payloads)
        ):
            point_id = str(uuid.uuid4())
            named_vectors = {
                "dense": dense,
            }
            named_sparse = {}
            if sparse.get("indices") and sparse.get("values"):
                named_sparse["sparse"] = models.SparseVector(
                    indices=sparse["indices"],
                    values=sparse["values"],
                )
            if bm25_vectors is not None and i < len(bm25_vectors):
                bm25 = bm25_vectors[i]
                if bm25.get("indices") and bm25.get("values"):
                    named_sparse["bm25"] = models.SparseVector(
                        indices=bm25["indices"],
                        values=bm25["values"],
                    )

            points.append(
                models.PointStruct(
                    id=point_id,
                    vector={**named_vectors, **named_sparse},
                    payload=payload,
                )
            )

        try:
            await self.client.upsert(
                collection_name=collection_name,
                points=points,
            )
            logger.info(f"Upserted {len(points)} points to '{collection_name}'")
        except Exception as e:
            raise VectorStoreError(f"Failed to upsert points: {e}") from e

    async def hybrid_search(
        self,
        collection_name: str,
        dense_vector: list[float],
        sparse_vector: dict,
        top_k: int = 10,
        bm25_vector: dict | None = None,
    ) -> list[dict]:
        """Execute hybrid search using Qdrant prefetch + RRF fusion."""
        try:
            prefetch = [
                models.Prefetch(
                    query=dense_vector,
                    using="dense",
                    limit=top_k,
                ),
            ]

            # Add sparse prefetch only if we have a valid sparse vector
            if sparse_vector.get("indices") and sparse_vector.get("values"):
                prefetch.append(
                    models.Prefetch(
                        query=models.SparseVector(
                            indices=sparse_vector["indices"],
                            values=sparse_vector["values"],
                        ),
                        using="sparse",
                        limit=top_k,
                    ),
                )

            # Add BM25 prefetch if provided
            if bm25_vector and bm25_vector.get("indices") and bm25_vector.get("values"):
                prefetch.append(
                    models.Prefetch(
                        query=models.SparseVector(
                            indices=bm25_vector["indices"],
                            values=bm25_vector["values"],
                        ),
                        using="bm25",
                        limit=top_k,
                    ),
                )

            results = await self.client.query_points(
                collection_name=collection_name,
                prefetch=prefetch,
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=top_k,
            )

            hits = []
            for point in results.points:
                hits.append({
                    "id": point.id,
                    "score": point.score,
                    "payload": point.payload or {},
                })

            return hits
        except Exception as e:
            raise VectorStoreError(f"Hybrid search failed: {e}") from e

    async def get_chunks_by_doc_id(
        self, collection_name: str, doc_id: str, limit: int = 200
    ) -> list[dict]:
        """Retrieve all stored chunks for a given doc_id, sorted by chunk_index."""
        try:
            results = await self.client.scroll(
                collection_name=collection_name,
                scroll_filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="doc_id",
                            match=models.MatchValue(value=doc_id),
                        )
                    ]
                ),
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
            points, _next_offset = results
            chunks = [
                {
                    "chunk_index": p.payload.get("chunk_index", 0),
                    "text": p.payload.get("text", ""),
                    "header_path": p.payload.get("header_path", ""),
                    "header_level": p.payload.get("header_level", 0),
                    "content_type": p.payload.get("content_type", "text"),
                }
                for p in points
            ]
            chunks.sort(key=lambda c: c["chunk_index"])
            return chunks
        except Exception as e:
            raise VectorStoreError(f"Failed to get chunks: {e}") from e

    async def collection_exists(self, collection_name: str) -> bool:
        """Check if a collection exists."""
        return await self.client.collection_exists(collection_name)
