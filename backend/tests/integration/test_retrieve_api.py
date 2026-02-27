

class TestRetrieveAPI:
    async def test_retrieve_json_mode_missing_kb(self, app_client):
        """Retrieve against non-existent collection should fail gracefully."""
        response = await app_client.post(
            "/api/v1/retrieve",
            json={
                "user_id": "test_user",
                "knowledge_base_id": "nonexistent_kb",
                "query": "test query",
                "top_k": 5,
                "top_n": 2,
                "stream": False,
            },
        )
        # Should return 500 or 502 since the collection doesn't exist
        assert response.status_code in [500, 502]

    async def test_retrieve_validation_empty_query(self, app_client):
        response = await app_client.post(
            "/api/v1/retrieve",
            json={
                "user_id": "u1",
                "knowledge_base_id": "kb1",
                "query": "",
                "stream": False,
            },
        )
        assert response.status_code == 422

    async def test_retrieve_validation_missing_fields(self, app_client):
        response = await app_client.post(
            "/api/v1/retrieve",
            json={"query": "test"},
        )
        assert response.status_code == 422
