import io

from qdrant_client import models as qmodels

from app.models.document import DocumentStatus as ModelStatus


class TestDocumentChunksAPI:
    """Tests for GET /api/v1/document/{kb_id}/{doc_id}/chunks"""

    async def _create_kb(self, client) -> str:
        resp = await client.post(
            "/api/v1/kb/create",
            json={"knowledge_base_name": "Chunks Test KB"},
        )
        return resp.json()["knowledge_base_id"]

    async def _upload_doc(self, client, kb_id: str, filename: str = "test.md", content: bytes = b"# Test\n\nSome content."):
        return await client.post(
            f"/api/v1/document/upload?knowledge_base_id={kb_id}",
            files={"file": (filename, io.BytesIO(content), "text/markdown")},
        )

    async def _set_doc_completed(self, kb_id: str, doc_id: str, chunk_count: int):
        """Set doc to completed via DB."""
        from app.db.session import get_session_factory
        from sqlalchemy import update
        from app.models.document import Document

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                update(Document)
                .where(Document.doc_id == doc_id, Document.knowledge_base_id == kb_id)
                .values(status=ModelStatus.COMPLETED, chunk_count=chunk_count)
            )
            await session.commit()

    async def _insert_fake_chunks(self, kb_id: str, doc_id: str, num_chunks: int):
        """Insert fake chunk points into Qdrant for testing."""
        import uuid
        from app.dependencies import get_vector_store_service

        vs = await get_vector_store_service()
        dim = vs.dense_dimension
        points = []
        for i in range(num_chunks):
            points.append(
                qmodels.PointStruct(
                    id=str(uuid.uuid4()),
                    vector={"dense": [0.1] * dim},
                    payload={
                        "text": f"Chunk {i} content for testing.",
                        "doc_id": doc_id,
                        "file_name": "test.md",
                        "knowledge_base_id": kb_id,
                        "chunk_index": i,
                        "header_path": f"# Section {i}",
                    },
                )
            )
        await vs.client.upsert(collection_name=kb_id, points=points)

    async def test_get_chunks_completed_doc(self, app_client):
        """Completed doc with chunks should return chunk data."""
        kb_id = await self._create_kb(app_client)
        upload_resp = await self._upload_doc(app_client, kb_id)
        assert upload_resp.status_code == 200
        doc_id = upload_resp.json()["doc_id"]

        # Manually set doc to completed and insert fake chunks
        import asyncio
        await asyncio.sleep(0.1)  # let pipeline start
        await self._set_doc_completed(kb_id, doc_id, 3)
        await self._insert_fake_chunks(kb_id, doc_id, 3)

        resp = await app_client.get(f"/api/v1/document/{kb_id}/{doc_id}/chunks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == doc_id
        assert data["file_name"] == "test.md"
        assert data["knowledge_base_id"] == kb_id
        assert data["status"] == "completed"
        assert data["chunk_count"] == 3
        assert len(data["chunks"]) == 3
        # Verify chunk structure
        chunk = data["chunks"][0]
        assert "chunk_index" in chunk
        assert "text" in chunk
        assert "header_path" in chunk
        assert len(chunk["text"]) > 0

    async def test_get_chunks_pending_doc(self, app_client):
        """Pending/processing doc should return empty chunks list."""
        kb_id = await self._create_kb(app_client)
        upload_resp = await self._upload_doc(app_client, kb_id)
        doc_id = upload_resp.json()["doc_id"]

        resp = await app_client.get(f"/api/v1/document/{kb_id}/{doc_id}/chunks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == doc_id
        assert isinstance(data["chunks"], list)

    async def test_get_chunks_nonexistent_doc(self, app_client):
        """Non-existent doc_id should return 404."""
        kb_id = await self._create_kb(app_client)
        resp = await app_client.get(f"/api/v1/document/{kb_id}/nonexistent_doc/chunks")
        assert resp.status_code == 404

    async def test_get_chunks_sorted_by_index(self, app_client):
        """Chunks should be sorted by chunk_index ascending."""
        kb_id = await self._create_kb(app_client)
        upload_resp = await self._upload_doc(app_client, kb_id, "multi.md", b"# Multi\n\nContent")
        doc_id = upload_resp.json()["doc_id"]

        import asyncio
        await asyncio.sleep(0.1)
        await self._set_doc_completed(kb_id, doc_id, 5)
        # Insert chunks in reverse order to test sorting
        await self._insert_fake_chunks(kb_id, doc_id, 5)

        resp = await app_client.get(f"/api/v1/document/{kb_id}/{doc_id}/chunks")
        data = resp.json()
        assert len(data["chunks"]) == 5
        indices = [c["chunk_index"] for c in data["chunks"]]
        assert indices == sorted(indices), "Chunks should be sorted by chunk_index"

    async def test_get_chunks_empty_completed_doc(self, app_client):
        """Completed doc with 0 chunks should return empty list."""
        kb_id = await self._create_kb(app_client)
        upload_resp = await self._upload_doc(app_client, kb_id, "empty.md", b"")
        doc_id = upload_resp.json()["doc_id"]

        import asyncio
        await asyncio.sleep(0.1)
        await self._set_doc_completed(kb_id, doc_id, 0)

        resp = await app_client.get(f"/api/v1/document/{kb_id}/{doc_id}/chunks")
        data = resp.json()
        assert data["chunk_count"] == 0
        assert data["chunks"] == []


class TestDocumentRetryAPI:
    """Tests for POST /api/v1/document/{kb_id}/{doc_id}/retry"""

    async def _create_kb(self, client) -> str:
        resp = await client.post(
            "/api/v1/kb/create",
            json={"knowledge_base_name": "Retry Test KB"},
        )
        return resp.json()["knowledge_base_id"]

    async def _upload_and_get_doc(self, client, kb_id: str):
        content = b"# Retry Test\n\nContent for retry testing."
        upload_resp = await client.post(
            f"/api/v1/document/upload?knowledge_base_id={kb_id}",
            files={"file": ("retry.md", io.BytesIO(content), "text/markdown")},
        )
        return upload_resp.json()

    async def _set_doc_status(self, kb_id: str, doc_id: str, status: ModelStatus, error: str | None = None):
        from app.db.session import get_session_factory
        from sqlalchemy import update
        from app.models.document import Document

        factory = get_session_factory()
        async with factory() as session:
            values = {"status": status}
            if error:
                values["error_message"] = error
            await session.execute(
                update(Document)
                .where(Document.doc_id == doc_id, Document.knowledge_base_id == kb_id)
                .values(**values)
            )
            await session.commit()

    async def test_retry_non_retryable_doc_returns_400(self, app_client):
        """Retrying a pending doc should return 400."""
        kb_id = await self._create_kb(app_client)
        data = await self._upload_and_get_doc(app_client, kb_id)
        doc_id = data["doc_id"]

        # Set doc to pending (not retryable — only uploaded/failed/completed are)
        import asyncio
        await asyncio.sleep(0.1)
        await self._set_doc_status(kb_id, doc_id, ModelStatus.PENDING)

        resp = await app_client.post(f"/api/v1/document/{kb_id}/{doc_id}/retry")
        assert resp.status_code == 400

    async def test_retry_completed_doc_succeeds(self, app_client):
        """Retrying a completed doc should succeed (re-vectorization)."""
        kb_id = await self._create_kb(app_client)
        data = await self._upload_and_get_doc(app_client, kb_id)
        doc_id = data["doc_id"]

        import asyncio
        await asyncio.sleep(0.1)
        await self._set_doc_status(kb_id, doc_id, ModelStatus.COMPLETED)

        resp = await app_client.post(f"/api/v1/document/{kb_id}/{doc_id}/retry")
        assert resp.status_code == 200
        retry_data = resp.json()
        assert retry_data["doc_id"] == doc_id
        assert retry_data["status"] == "pending"

    async def test_retry_nonexistent_doc_returns_404(self, app_client):
        """Retrying a non-existent doc should return 404."""
        kb_id = await self._create_kb(app_client)
        resp = await app_client.post(f"/api/v1/document/{kb_id}/nonexistent/retry")
        assert resp.status_code == 404

    async def test_retry_failed_doc(self, app_client):
        """Retrying a failed doc should reset status to pending."""
        kb_id = await self._create_kb(app_client)
        data = await self._upload_and_get_doc(app_client, kb_id)
        doc_id = data["doc_id"]

        import asyncio
        await asyncio.sleep(0.1)
        await self._set_doc_status(kb_id, doc_id, ModelStatus.FAILED, "Simulated failure")

        # Verify it's failed
        list_resp = await app_client.get(f"/api/v1/document/list/{kb_id}")
        docs = list_resp.json()["documents"]
        doc = next(d for d in docs if d["doc_id"] == doc_id)
        assert doc["status"] == "failed"

        # Retry
        resp = await app_client.post(f"/api/v1/document/{kb_id}/{doc_id}/retry")
        assert resp.status_code == 200
        retry_data = resp.json()
        assert retry_data["doc_id"] == doc_id
        assert retry_data["status"] == "pending"
        assert "task_id" not in retry_data

    async def test_retry_failed_doc_missing_file(self, app_client):
        """Retrying when original file was deleted from disk should return 404."""
        kb_id = await self._create_kb(app_client)
        data = await self._upload_and_get_doc(app_client, kb_id)
        doc_id = data["doc_id"]

        import asyncio
        await asyncio.sleep(0.1)
        await self._set_doc_status(kb_id, doc_id, ModelStatus.FAILED, "Original failure")

        # Delete the physical file
        from app.config import get_settings
        settings = get_settings()
        file_path = settings.upload_path / kb_id / "retry.md"
        if file_path.exists():
            file_path.unlink()

        resp = await app_client.post(f"/api/v1/document/{kb_id}/{doc_id}/retry")
        assert resp.status_code == 404
        assert "file" in resp.json()["detail"].lower()


class TestDocumentDownloadAPI:
    """Tests for GET /api/v1/document/{kb_id}/{doc_id}/download"""

    async def _create_kb(self, client) -> str:
        resp = await client.post(
            "/api/v1/kb/create",
            json={"knowledge_base_name": "Download Test KB"},
        )
        return resp.json()["knowledge_base_id"]

    async def test_download_existing_file(self, app_client):
        """Download should return the original file content."""
        kb_id = await self._create_kb(app_client)
        original_content = b"# Download Test\n\nOriginal content for download."
        upload_resp = await app_client.post(
            f"/api/v1/document/upload?knowledge_base_id={kb_id}",
            files={"file": ("download.md", io.BytesIO(original_content), "text/markdown")},
        )
        assert upload_resp.status_code == 200
        doc_id = upload_resp.json()["doc_id"]

        resp = await app_client.get(f"/api/v1/document/{kb_id}/{doc_id}/download")
        assert resp.status_code == 200
        assert resp.content == original_content
        assert "download.md" in resp.headers.get("content-disposition", "")

    async def test_download_nonexistent_doc(self, app_client):
        """Download for non-existent doc should return 404."""
        kb_id = await self._create_kb(app_client)
        resp = await app_client.get(f"/api/v1/document/{kb_id}/nonexistent/download")
        assert resp.status_code == 404

    async def test_download_missing_file_on_disk(self, app_client):
        """Download when file was deleted from disk should return 404."""
        kb_id = await self._create_kb(app_client)
        content = b"# Temp File\n\nWill be deleted."
        upload_resp = await app_client.post(
            f"/api/v1/document/upload?knowledge_base_id={kb_id}",
            files={"file": ("temp.md", io.BytesIO(content), "text/markdown")},
        )
        doc_id = upload_resp.json()["doc_id"]

        from app.config import get_settings
        settings = get_settings()
        file_path = settings.upload_path / kb_id / "temp.md"
        if file_path.exists():
            file_path.unlink()

        resp = await app_client.get(f"/api/v1/document/{kb_id}/{doc_id}/download")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    async def test_download_preserves_filename(self, app_client):
        """Download should set the correct filename in Content-Disposition."""
        kb_id = await self._create_kb(app_client)
        upload_resp = await app_client.post(
            f"/api/v1/document/upload?knowledge_base_id={kb_id}",
            files={"file": ("report_2024.pdf", io.BytesIO(b"fake pdf"), "application/pdf")},
        )
        doc_id = upload_resp.json()["doc_id"]

        resp = await app_client.get(f"/api/v1/document/{kb_id}/{doc_id}/download")
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        assert "report_2024.pdf" in cd
