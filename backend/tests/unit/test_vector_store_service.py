import pytest
from qdrant_client import AsyncQdrantClient

from app.services.vector_store_service import VectorStoreService


@pytest.fixture
async def qdrant_client():
    client = AsyncQdrantClient(location=":memory:")
    yield client
    await client.close()


@pytest.fixture
async def vs_service(qdrant_client):
    return VectorStoreService(qdrant_client)


DENSE_DIM = 1024


class TestVectorStoreService:
    async def test_create_collection(self, vs_service):
        await vs_service.create_collection("test_col")
        exists = await vs_service.collection_exists("test_col")
        assert exists is True

    async def test_create_collection_idempotent(self, vs_service):
        await vs_service.create_collection("test_col")
        await vs_service.create_collection("test_col")
        exists = await vs_service.collection_exists("test_col")
        assert exists is True

    async def test_delete_collection(self, vs_service):
        await vs_service.create_collection("to_delete")
        await vs_service.delete_collection("to_delete")
        exists = await vs_service.collection_exists("to_delete")
        assert exists is False

    async def test_upsert_and_search(self, vs_service):
        await vs_service.create_collection("search_col")

        dense_vectors = [[0.1] * DENSE_DIM, [0.9] * DENSE_DIM]
        sparse_vectors = [
            {"indices": [1, 5, 10], "values": [0.5, 0.3, 0.8]},
            {"indices": [2, 7, 10], "values": [0.6, 0.2, 0.9]},
        ]
        payloads = [
            {"text": "First document", "doc_id": "doc1"},
            {"text": "Second document", "doc_id": "doc2"},
        ]

        await vs_service.upsert_points("search_col", dense_vectors, sparse_vectors, payloads)

        # Search with dense vector close to second document
        results = await vs_service.hybrid_search(
            "search_col",
            dense_vector=[0.9] * DENSE_DIM,
            sparse_vector={"indices": [2, 7], "values": [0.6, 0.2]},
            top_k=2,
        )

        assert len(results) >= 1
        assert "payload" in results[0]

    async def test_delete_by_doc_id(self, vs_service):
        await vs_service.create_collection("del_col")

        await vs_service.upsert_points(
            "del_col",
            dense_vectors=[[0.1] * DENSE_DIM],
            sparse_vectors=[{"indices": [1], "values": [0.5]}],
            payloads=[{"text": "delete me", "doc_id": "doc_del"}],
        )

        await vs_service.delete_by_doc_id("del_col", "doc_del")

        results = await vs_service.hybrid_search(
            "del_col",
            dense_vector=[0.1] * DENSE_DIM,
            sparse_vector={"indices": [1], "values": [0.5]},
            top_k=10,
        )
        # After deletion, should have no results with doc_id=doc_del
        for r in results:
            assert r["payload"].get("doc_id") != "doc_del"

    async def test_upsert_empty(self, vs_service):
        await vs_service.create_collection("empty_col")
        await vs_service.upsert_points("empty_col", [], [], [])
        # Should not raise

    async def test_delete_before_insert_pattern(self, vs_service):
        """Verify delete-before-insert prevents duplicates."""
        await vs_service.create_collection("dbi_col")

        # First insert
        await vs_service.upsert_points(
            "dbi_col",
            dense_vectors=[[0.1] * DENSE_DIM],
            sparse_vectors=[{"indices": [1], "values": [0.5]}],
            payloads=[{"text": "version 1", "doc_id": "same_doc"}],
        )

        # Delete before re-insert
        await vs_service.delete_by_doc_id("dbi_col", "same_doc")

        # Re-insert with new content
        await vs_service.upsert_points(
            "dbi_col",
            dense_vectors=[[0.2] * DENSE_DIM],
            sparse_vectors=[{"indices": [2], "values": [0.6]}],
            payloads=[{"text": "version 2", "doc_id": "same_doc"}],
        )

        results = await vs_service.hybrid_search(
            "dbi_col",
            dense_vector=[0.2] * DENSE_DIM,
            sparse_vector={"indices": [2], "values": [0.6]},
            top_k=10,
        )

        # Should only find version 2
        doc_texts = [r["payload"]["text"] for r in results if r["payload"].get("doc_id") == "same_doc"]
        assert "version 2" in doc_texts
        assert "version 1" not in doc_texts
