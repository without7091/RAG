import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import KnowledgeBaseAlreadyExistsError, KnowledgeBaseNotFoundError
from app.services.kb_folder_service import KBFolderService
from app.services.kb_service import KBService


class TestKBService:
    async def test_create_kb(self, db_session: AsyncSession):
        svc = KBService(db_session)
        kb = await svc.create("Test KB", "A test knowledge base")
        assert kb.knowledge_base_name == "Test KB"
        assert kb.description == "A test knowledge base"
        assert kb.knowledge_base_id.startswith("kb_")
        assert kb.folder_id is not None

    async def test_create_duplicate_raises(self, db_session: AsyncSession):
        svc = KBService(db_session)
        await svc.create("Duplicate KB")
        with pytest.raises(KnowledgeBaseAlreadyExistsError):
            await svc.create("Duplicate KB")

    async def test_get_by_id(self, db_session: AsyncSession):
        svc = KBService(db_session)
        kb = await svc.create("Get KB")
        found = await svc.get_by_id(kb.knowledge_base_id)
        assert found.knowledge_base_name == "Get KB"

    async def test_get_by_id_not_found(self, db_session: AsyncSession):
        svc = KBService(db_session)
        with pytest.raises(KnowledgeBaseNotFoundError):
            await svc.get_by_id("nonexistent_id")

    async def test_list_all(self, db_session: AsyncSession):
        svc = KBService(db_session)
        await svc.create("KB One")
        await svc.create("KB Two")
        kbs = await svc.list_all()
        assert len(kbs) == 2

    async def test_delete(self, db_session: AsyncSession):
        svc = KBService(db_session)
        kb = await svc.create("To Delete")
        await svc.delete(kb.knowledge_base_id)
        with pytest.raises(KnowledgeBaseNotFoundError):
            await svc.get_by_id(kb.knowledge_base_id)

    async def test_get_document_count_empty(self, db_session: AsyncSession):
        svc = KBService(db_session)
        kb = await svc.create("Empty KB")
        count = await svc.get_document_count(kb.knowledge_base_id)
        assert count == 0

    async def test_create_same_name_in_different_folders(self, db_session: AsyncSession):
        folder_service = KBFolderService(db_session)
        svc = KBService(db_session, folder_service=folder_service)
        root = await folder_service.create("项目A")
        child_one = await folder_service.create("子项目A", parent_folder_id=root.folder_id)
        child_two = await folder_service.create("子项目B", parent_folder_id=root.folder_id)

        first = await svc.create("Shared Name", folder_id=child_one.folder_id)
        second = await svc.create("Shared Name", folder_id=child_two.folder_id)

        assert first.folder_id == child_one.folder_id
        assert second.folder_id == child_two.folder_id

    async def test_update_moves_kb_to_another_folder(self, db_session: AsyncSession):
        folder_service = KBFolderService(db_session)
        svc = KBService(db_session, folder_service=folder_service)
        root = await folder_service.create("项目A")
        child_one = await folder_service.create("子项目A", parent_folder_id=root.folder_id)
        child_two = await folder_service.create("子项目B", parent_folder_id=root.folder_id)
        kb = await svc.create("Move KB", folder_id=child_one.folder_id)

        moved = await svc.update(kb.knowledge_base_id, folder_id=child_two.folder_id)

        assert moved.folder_id == child_two.folder_id
