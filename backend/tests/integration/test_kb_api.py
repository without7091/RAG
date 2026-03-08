

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
        assert data["folder_id"].startswith("folder_")
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

    async def test_list_kb_tree(self, app_client):
        response = await app_client.get("/api/v1/kb/tree")

        assert response.status_code == 200
        data = response.json()
        assert len(data["folders"]) == 1
        assert data["folders"][0]["depth"] == 1
        assert len(data["folders"][0]["children"]) == 1
        assert data["folders"][0]["children"][0]["depth"] == 2

    async def test_folder_crud_and_move_kb(self, app_client):
        root_resp = await app_client.post(
            "/api/v1/kb/folders",
            json={"folder_name": "项目A"},
        )
        assert root_resp.status_code == 200
        root_id = root_resp.json()["folder_id"]

        child_one_resp = await app_client.post(
            "/api/v1/kb/folders",
            json={"folder_name": "子项目A", "parent_folder_id": root_id},
        )
        assert child_one_resp.status_code == 200
        child_one_id = child_one_resp.json()["folder_id"]

        child_two_resp = await app_client.post(
            "/api/v1/kb/folders",
            json={"folder_name": "子项目B", "parent_folder_id": root_id},
        )
        assert child_two_resp.status_code == 200
        child_two_id = child_two_resp.json()["folder_id"]

        kb_resp = await app_client.post(
            "/api/v1/kb/create",
            json={
                "knowledge_base_name": "树形知识库",
                "folder_id": child_one_id,
            },
        )
        assert kb_resp.status_code == 200
        kb_id = kb_resp.json()["knowledge_base_id"]

        move_resp = await app_client.patch(
            f"/api/v1/kb/{kb_id}",
            json={"folder_id": child_two_id},
        )
        assert move_resp.status_code == 200
        assert move_resp.json()["folder_id"] == child_two_id

        tree_resp = await app_client.get("/api/v1/kb/tree")
        assert tree_resp.status_code == 200
        tree = tree_resp.json()
        target_child = next(
            child
            for folder in tree["folders"]
            for child in folder["children"]
            if child["folder_id"] == child_two_id
        )
        assert any(kb["knowledge_base_id"] == kb_id for kb in target_child["knowledge_bases"])

    async def test_delete_non_empty_folder_rejected(self, app_client):
        root_resp = await app_client.post(
            "/api/v1/kb/folders",
            json={"folder_name": "项目A"},
        )
        root_id = root_resp.json()["folder_id"]

        child_resp = await app_client.post(
            "/api/v1/kb/folders",
            json={"folder_name": "子项目A", "parent_folder_id": root_id},
        )
        child_id = child_resp.json()["folder_id"]

        kb_resp = await app_client.post(
            "/api/v1/kb/create",
            json={
                "knowledge_base_name": "不可删知识库",
                "folder_id": child_id,
            },
        )
        assert kb_resp.status_code == 200

        delete_resp = await app_client.delete(f"/api/v1/kb/folders/{child_id}")
        assert delete_resp.status_code == 409
