import pytest
from qdrant_client import AsyncQdrantClient

from app.exceptions import VectorStoreError
from app.services.vector_store_service import VectorStoreService


@pytest.fixture
async def qdrant_client():
    client = AsyncQdrantClient(location=":memory:")
    yield client
    await client.close()


@pytest.fixture
async def vs_service(qdrant_client):
    return VectorStoreService(qdrant_client)


from app.config import get_settings

DENSE_DIM = get_settings().embedding_dimension


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

    async def test_create_collection_has_bm25_space(self, vs_service, qdrant_client):
        """New collections should have dense + sparse + bm25 vector spaces."""
        await vs_service.create_collection("bm25_col")
        info = await qdrant_client.get_collection("bm25_col")
        # Check sparse vectors config includes both "sparse" and "bm25"
        sparse_names = set(info.config.params.sparse_vectors.keys())
        assert "sparse" in sparse_names
        assert "bm25" in sparse_names
        # Check dense vector config
        assert "dense" in info.config.params.vectors

    async def test_upsert_three_vectors(self, vs_service):
        """Upsert with all three vector types and search."""
        await vs_service.create_collection("three_vec_col")

        dense_vectors = [[0.5] * DENSE_DIM]
        sparse_vectors = [{"indices": [1, 5], "values": [0.5, 0.3]}]
        bm25_vectors = [{"indices": [10, 20], "values": [2.0, 1.0]}]
        payloads = [{"text": "three vector doc", "doc_id": "doc3v"}]

        await vs_service.upsert_points(
            "three_vec_col", dense_vectors, sparse_vectors, payloads,
            bm25_vectors=bm25_vectors,
        )

        results = await vs_service.hybrid_search(
            "three_vec_col",
            dense_vector=[0.5] * DENSE_DIM,
            sparse_vector={"indices": [1, 5], "values": [0.5, 0.3]},
            bm25_vector={"indices": [10, 20], "values": [2.0, 1.0]},
            top_k=5,
        )
        assert len(results) >= 1
        assert results[0]["payload"]["doc_id"] == "doc3v"

    async def test_three_way_hybrid_search(self, vs_service):
        """BM25 path should help recall keyword-matching documents."""
        await vs_service.create_collection("three_way_col")

        # Doc 1: strong on dense, weak on BM25
        # Doc 2: weak on dense, strong on BM25 keyword match
        dense_vectors = [
            [0.9] * DENSE_DIM,
            [0.1] * DENSE_DIM,
        ]
        sparse_vectors = [
            {"indices": [1], "values": [0.5]},
            {"indices": [2], "values": [0.5]},
        ]
        bm25_vectors = [
            {"indices": [100], "values": [1.0]},
            {"indices": [200], "values": [1.0]},
        ]
        payloads = [
            {"text": "dense match doc", "doc_id": "dense_doc"},
            {"text": "keyword match doc", "doc_id": "keyword_doc"},
        ]

        await vs_service.upsert_points(
            "three_way_col", dense_vectors, sparse_vectors, payloads,
            bm25_vectors=bm25_vectors,
        )

        # Query that matches keyword_doc via BM25 but dense_doc via dense
        results = await vs_service.hybrid_search(
            "three_way_col",
            dense_vector=[0.9] * DENSE_DIM,
            sparse_vector={"indices": [2], "values": [0.5]},
            bm25_vector={"indices": [200], "values": [1.0]},
            top_k=5,
        )
        # Both docs should be recalled
        doc_ids = {r["payload"]["doc_id"] for r in results}
        assert "dense_doc" in doc_ids
        assert "keyword_doc" in doc_ids

    async def test_upsert_backward_compat_no_bm25(self, vs_service):
        """Upsert without bm25_vectors should still work."""
        await vs_service.create_collection("compat_col")

        await vs_service.upsert_points(
            "compat_col",
            dense_vectors=[[0.5] * DENSE_DIM],
            sparse_vectors=[{"indices": [1], "values": [0.5]}],
            payloads=[{"text": "no bm25", "doc_id": "doc_compat"}],
        )

        results = await vs_service.hybrid_search(
            "compat_col",
            dense_vector=[0.5] * DENSE_DIM,
            sparse_vector={"indices": [1], "values": [0.5]},
            top_k=5,
        )
        assert len(results) >= 1

    async def test_hybrid_search_backward_compat_no_bm25(self, vs_service):
        """Hybrid search without bm25_vector should still work (two-way)."""
        await vs_service.create_collection("compat_search_col")

        await vs_service.upsert_points(
            "compat_search_col",
            dense_vectors=[[0.5] * DENSE_DIM],
            sparse_vectors=[{"indices": [1], "values": [0.5]}],
            payloads=[{"text": "compat search", "doc_id": "doc_cs"}],
        )

        # No bm25_vector argument
        results = await vs_service.hybrid_search(
            "compat_search_col",
            dense_vector=[0.5] * DENSE_DIM,
            sparse_vector={"indices": [1], "values": [0.5]},
            top_k=5,
        )
        assert len(results) >= 1

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

    async def test_upsert_raises_on_length_mismatch(self, vs_service):
        await vs_service.create_collection("mismatch_col")
        with pytest.raises(VectorStoreError, match="Length mismatch"):
            await vs_service.upsert_points(
                "mismatch_col",
                dense_vectors=[[0.1] * DENSE_DIM, [0.2] * DENSE_DIM],
                sparse_vectors=[{"indices": [1], "values": [0.1]}],
                payloads=[
                    {"text": "a", "doc_id": "doc_a"},
                    {"text": "b", "doc_id": "doc_b"},
                ],
            )

    async def test_upsert_raises_on_bm25_length_mismatch(self, vs_service):
        await vs_service.create_collection("bm25_mismatch_col")
        with pytest.raises(VectorStoreError, match="Length mismatch"):
            await vs_service.upsert_points(
                "bm25_mismatch_col",
                dense_vectors=[[0.1] * DENSE_DIM, [0.2] * DENSE_DIM],
                sparse_vectors=[
                    {"indices": [1], "values": [0.1]},
                    {"indices": [2], "values": [0.2]},
                ],
                payloads=[
                    {"text": "a", "doc_id": "doc_a"},
                    {"text": "b", "doc_id": "doc_b"},
                ],
                bm25_vectors=[{"indices": [10], "values": [1.0]}],
            )
