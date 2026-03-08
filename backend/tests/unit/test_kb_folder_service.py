import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import (
    KBFolderAlreadyExistsError,
    KBFolderNotEmptyError,
    KBFolderValidationError,
)
from app.services.kb_folder_service import (
    DEFAULT_LEAF_FOLDER_NAME,
    DEFAULT_ROOT_FOLDER_NAME,
    KBFolderService,
)
from app.services.kb_service import KBService


class TestKBFolderService:
    async def test_ensure_default_hierarchy_is_idempotent(self, db_session: AsyncSession):
        svc = KBFolderService(db_session)

        leaf_one = await svc.ensure_default_hierarchy()
        leaf_two = await svc.ensure_default_hierarchy()
        folders = await svc.list_all()

        assert leaf_one.folder_id == leaf_two.folder_id
        assert len(folders) == 2
        assert any(folder.folder_name == DEFAULT_ROOT_FOLDER_NAME for folder in folders)
        assert any(folder.folder_name == DEFAULT_LEAF_FOLDER_NAME for folder in folders)

    async def test_create_second_level_folder(self, db_session: AsyncSession):
        svc = KBFolderService(db_session)

        root = await svc.create("项目A")
        child = await svc.create("子项目A", parent_folder_id=root.folder_id)

        assert root.depth == 1
        assert child.depth == 2
        assert child.parent_folder_id == root.folder_id

    async def test_create_third_level_folder_fails(self, db_session: AsyncSession):
        svc = KBFolderService(db_session)
        root = await svc.create("项目A")
        child = await svc.create("子项目A", parent_folder_id=root.folder_id)

        with pytest.raises(KBFolderValidationError):
            await svc.create("三级目录", parent_folder_id=child.folder_id)

    async def test_duplicate_folder_name_under_same_parent_fails(
        self, db_session: AsyncSession
    ):
        svc = KBFolderService(db_session)
        root = await svc.create("项目A")
        await svc.create("子项目A", parent_folder_id=root.folder_id)

        with pytest.raises(KBFolderAlreadyExistsError):
            await svc.create("子项目A", parent_folder_id=root.folder_id)

    async def test_delete_non_empty_folder_fails(self, db_session: AsyncSession):
        folder_service = KBFolderService(db_session)
        kb_service = KBService(db_session, folder_service=folder_service)
        root = await folder_service.create("项目A")
        child = await folder_service.create("子项目A", parent_folder_id=root.folder_id)
        await kb_service.create("测试知识库", folder_id=child.folder_id)

        with pytest.raises(KBFolderNotEmptyError):
            await folder_service.delete(child.folder_id)
