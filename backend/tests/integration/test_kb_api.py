

class TestKBAPI:
    async def test_create_kb(self, app_client):
        response = await app_client.post(
            "/api/v1/kb/create",
            json={
                "knowledge_base_name": "Integration Test KB",
                "description": "A KB for testing",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["knowledge_base_name"] == "Integration Test KB"
        assert data["knowledge_base_id"].startswith("kb_")
        assert "created_at" in data

    async def test_create_duplicate_kb(self, app_client):
        await app_client.post(
            "/api/v1/kb/create",
            json={"knowledge_base_name": "Dup KB"},
        )
        response = await app_client.post(
            "/api/v1/kb/create",
            json={"knowledge_base_name": "Dup KB"},
        )
        assert response.status_code == 409

    async def test_list_kbs(self, app_client):
        await app_client.post(
            "/api/v1/kb/create",
            json={"knowledge_base_name": "List KB 1"},
        )
        await app_client.post(
            "/api/v1/kb/create",
            json={"knowledge_base_name": "List KB 2"},
        )
        response = await app_client.get("/api/v1/kb/list")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= 2

    async def test_delete_kb(self, app_client):
        create_resp = await app_client.post(
            "/api/v1/kb/create",
            json={"knowledge_base_name": "Delete KB"},
        )
        kb_id = create_resp.json()["knowledge_base_id"]

        del_resp = await app_client.delete(f"/api/v1/kb/{kb_id}")
        assert del_resp.status_code == 200
        assert del_resp.json()["deleted"] is True

        # Verify it's gone
        list_resp = await app_client.get("/api/v1/kb/list")
        kb_ids = [kb["knowledge_base_id"] for kb in list_resp.json()["knowledge_bases"]]
        assert kb_id not in kb_ids

    async def test_delete_nonexistent_kb(self, app_client):
        response = await app_client.delete("/api/v1/kb/nonexistent_123")
        assert response.status_code == 404

    async def test_create_kb_empty_name(self, app_client):
        response = await app_client.post(
            "/api/v1/kb/create",
            json={"knowledge_base_name": ""},
        )
        assert response.status_code == 422
