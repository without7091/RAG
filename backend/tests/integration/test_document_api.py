import io
import json


class TestDocumentAPI:
    async def _create_kb(self, client) -> str:
        resp = await client.post(
            "/api/v1/kb/create",
            json={"knowledge_base_name": "Doc Test KB"},
        )
        return resp.json()["knowledge_base_id"]

    async def test_upload_returns_uploaded(self, app_client):
        kb_id = await self._create_kb(app_client)

        content = b"# Test\n\nSome content for testing upload."
        response = await app_client.post(
            f"/api/v1/document/upload?knowledge_base_id={kb_id}",
            files={"file": ("test.md", io.BytesIO(content), "text/markdown")},
        )
        assert response.status_code == 200
        data = response.json()
        assert "doc_id" in data
        assert data["file_name"] == "test.md"
        assert data["status"] == "uploaded"
        # task_id should no longer be in the response
        assert "task_id" not in data

    async def test_upload_to_nonexistent_kb(self, app_client):
        content = b"# Test"
        response = await app_client.post(
            "/api/v1/document/upload?knowledge_base_id=nonexistent",
            files={"file": ("test.md", io.BytesIO(content), "text/markdown")},
        )
        assert response.status_code == 404

    async def test_upload_rejects_unsafe_filename(self, app_client):
        kb_id = await self._create_kb(app_client)
        content = b"# Unsafe"
        response = await app_client.post(
            f"/api/v1/document/upload?knowledge_base_id={kb_id}",
            files={"file": ("../unsafe.md", io.BytesIO(content), "text/markdown")},
        )
        assert response.status_code == 400

    async def test_upload_chunks_rejects_unsafe_filename(self, app_client):
        kb_id = await self._create_kb(app_client)
        content = json.dumps([{"text": "chunk"}]).encode("utf-8")
        response = await app_client.post(
            f"/api/v1/document/upload-chunks?knowledge_base_id={kb_id}",
            files={"file": ("..\\unsafe.json", io.BytesIO(content), "application/json")},
        )
        assert response.status_code == 400

    async def test_vectorize_returns_docs(self, app_client):
        """Vectorize should return docs (not tasks) with pending status."""
        kb_id = await self._create_kb(app_client)

        content = b"# Upload Task\n\nTest task tracking."
        upload_resp = await app_client.post(
            f"/api/v1/document/upload?knowledge_base_id={kb_id}",
            files={"file": ("task_test.md", io.BytesIO(content), "text/markdown")},
        )
        doc_id = upload_resp.json()["doc_id"]

        # Vectorize the uploaded document
        vec_resp = await app_client.post(
            "/api/v1/document/vectorize",
            json={"knowledge_base_id": kb_id, "doc_ids": [doc_id]},
        )
        assert vec_resp.status_code == 200
        data = vec_resp.json()
        # New response format: "docs" not "tasks"
        assert "docs" in data
        assert "tasks" not in data
        assert len(data["docs"]) == 1
        assert data["docs"][0]["doc_id"] == doc_id
        assert data["docs"][0]["status"] == "pending"
        assert "task_id" not in data["docs"][0]

    async def test_vectorize_sets_pending_status_in_db(self, app_client):
        """After vectorize, doc should be PENDING in the database."""
        kb_id = await self._create_kb(app_client)

        content = b"# Status check\n\nTest pending status."
        upload_resp = await app_client.post(
            f"/api/v1/document/upload?knowledge_base_id={kb_id}",
            files={"file": ("status_test.md", io.BytesIO(content), "text/markdown")},
        )
        doc_id = upload_resp.json()["doc_id"]

        await app_client.post(
            "/api/v1/document/vectorize",
            json={"knowledge_base_id": kb_id, "doc_ids": [doc_id]},
        )

        # Check document status via list endpoint
        list_resp = await app_client.get(f"/api/v1/document/list/{kb_id}")
        docs = list_resp.json()["documents"]
        doc = next(d for d in docs if d["doc_id"] == doc_id)
        assert doc["status"] == "pending"

    async def test_retry_returns_no_task_id(self, app_client):
        """Retry should return response without task_id."""
        kb_id = await self._create_kb(app_client)

        content = b"# Retry test\n\nContent."
        upload_resp = await app_client.post(
            f"/api/v1/document/upload?knowledge_base_id={kb_id}",
            files={"file": ("retry_test.md", io.BytesIO(content), "text/markdown")},
        )
        doc_id = upload_resp.json()["doc_id"]

        retry_resp = await app_client.post(
            f"/api/v1/document/{kb_id}/{doc_id}/retry",
        )
        assert retry_resp.status_code == 200
        data = retry_resp.json()
        assert data["doc_id"] == doc_id
        assert data["status"] == "pending"
        assert "task_id" not in data

    async def test_tasks_endpoint_removed(self, app_client):
        """The /tasks endpoint should no longer exist."""
        response = await app_client.get("/api/v1/tasks/some_task_id")
        assert response.status_code == 404

    async def test_list_documents(self, app_client):
        kb_id = await self._create_kb(app_client)

        content = b"# List Test\n\nDoc for listing."
        await app_client.post(
            f"/api/v1/document/upload?knowledge_base_id={kb_id}",
            files={"file": ("list_test.md", io.BytesIO(content), "text/markdown")},
        )

        response = await app_client.get(f"/api/v1/document/list/{kb_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 1
