import io


class TestDocumentAPI:
    async def _create_kb(self, client) -> str:
        resp = await client.post(
            "/api/v1/kb/create",
            json={"knowledge_base_name": "Doc Test KB"},
        )
        return resp.json()["knowledge_base_id"]

    async def test_upload_returns_task(self, app_client):
        kb_id = await self._create_kb(app_client)

        content = b"# Test\n\nSome content for testing upload."
        response = await app_client.post(
            f"/api/v1/document/upload?knowledge_base_id={kb_id}",
            files={"file": ("test.md", io.BytesIO(content), "text/markdown")},
        )
        assert response.status_code == 200
        data = response.json()
        assert "task_id" in data
        assert "doc_id" in data
        assert data["file_name"] == "test.md"
        assert data["status"] == "pending"

    async def test_upload_to_nonexistent_kb(self, app_client):
        content = b"# Test"
        response = await app_client.post(
            "/api/v1/document/upload?knowledge_base_id=nonexistent",
            files={"file": ("test.md", io.BytesIO(content), "text/markdown")},
        )
        assert response.status_code == 404

    async def test_get_task_status(self, app_client):
        kb_id = await self._create_kb(app_client)

        content = b"# Upload Task\n\nTest task tracking."
        upload_resp = await app_client.post(
            f"/api/v1/document/upload?knowledge_base_id={kb_id}",
            files={"file": ("task_test.md", io.BytesIO(content), "text/markdown")},
        )
        task_id = upload_resp.json()["task_id"]

        task_resp = await app_client.get(f"/api/v1/tasks/{task_id}")
        assert task_resp.status_code == 200
        data = task_resp.json()
        assert data["task_id"] == task_id
        assert data["status"] in ["pending", "processing", "completed", "failed"]

    async def test_get_nonexistent_task(self, app_client):
        response = await app_client.get("/api/v1/tasks/nonexistent_task")
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
