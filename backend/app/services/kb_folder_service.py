from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import (
    KBFolderAlreadyExistsError,
    KBFolderNotEmptyError,
    KBFolderNotFoundError,
    KBFolderValidationError,
)
from app.models.kb_folder import KBFolder
from app.models.knowledge_base import KnowledgeBase
from app.utils.id_gen import generate_folder_id

DEFAULT_ROOT_FOLDER_NAME = "未分组"
DEFAULT_LEAF_FOLDER_NAME = "默认分组"
MAX_FOLDER_DEPTH = 2


class KBFolderService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def ensure_default_hierarchy(self) -> KBFolder:
        root = await self._get_by_name(DEFAULT_ROOT_FOLDER_NAME, parent_folder_id=None)
        if root is None:
            root = await self._create_folder(
                folder_name=DEFAULT_ROOT_FOLDER_NAME,
                parent_folder_id=None,
                depth=1,
            )

        leaf = await self._get_by_name(DEFAULT_LEAF_FOLDER_NAME, parent_folder_id=root.folder_id)
        if leaf is None:
            leaf = await self._create_folder(
                folder_name=DEFAULT_LEAF_FOLDER_NAME,
                parent_folder_id=root.folder_id,
                depth=2,
            )

        return leaf

    async def get_by_id(self, folder_id: str) -> KBFolder:
        result = await self.session.execute(
            select(KBFolder).where(KBFolder.folder_id == folder_id)
        )
        folder = result.scalar_one_or_none()
        if folder is None:
            raise KBFolderNotFoundError(folder_id)
        return folder

    async def list_all(self) -> list[KBFolder]:
        result = await self.session.execute(
            select(KBFolder).order_by(KBFolder.depth.asc(), KBFolder.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_second_level_folders(self) -> list[KBFolder]:
        result = await self.session.execute(
            select(KBFolder)
            .where(KBFolder.depth == 2)
            .order_by(KBFolder.created_at.desc())
        )
        return list(result.scalars().all())

    async def create(self, folder_name: str, parent_folder_id: str | None = None) -> KBFolder:
        normalized_name = folder_name.strip()
        if not normalized_name:
            raise KBFolderValidationError("Folder name cannot be empty")

        if parent_folder_id is None:
            depth = 1
        else:
            parent = await self.get_by_id(parent_folder_id)
            if parent.depth >= MAX_FOLDER_DEPTH:
                raise KBFolderValidationError("Cannot create folders deeper than level 2")
            depth = parent.depth + 1

        await self._ensure_name_available(normalized_name, parent_folder_id)
        return await self._create_folder(normalized_name, parent_folder_id, depth)

    async def update(self, folder_id: str, folder_name: str) -> KBFolder:
        folder = await self.get_by_id(folder_id)
        normalized_name = folder_name.strip()
        if not normalized_name:
            raise KBFolderValidationError("Folder name cannot be empty")

        await self._ensure_name_available(
            normalized_name,
            folder.parent_folder_id,
            exclude_folder_id=folder_id,
        )
        folder.folder_name = normalized_name
        await self.session.commit()
        await self.session.refresh(folder)
        return folder

    async def delete(self, folder_id: str) -> None:
        folder = await self.get_by_id(folder_id)
        child_folder_count = await self._count_child_folders(folder.folder_id)
        kb_count = await self._count_knowledge_bases(folder.folder_id)
        if child_folder_count > 0 or kb_count > 0:
            raise KBFolderNotEmptyError(folder.folder_id)

        await self.session.delete(folder)
        await self.session.commit()

    async def resolve_leaf_folder(self, folder_id: str | None) -> KBFolder:
        if folder_id is None:
            return await self.ensure_default_hierarchy()

        folder = await self.get_by_id(folder_id)
        if folder.depth != 2:
            raise KBFolderValidationError("Knowledge bases must belong to a level-2 folder")
        return folder

    async def _count_child_folders(self, folder_id: str) -> int:
        result = await self.session.execute(
            select(func.count(KBFolder.id)).where(KBFolder.parent_folder_id == folder_id)
        )
        return result.scalar() or 0

    async def _count_knowledge_bases(self, folder_id: str) -> int:
        result = await self.session.execute(
            select(func.count(KnowledgeBase.id)).where(KnowledgeBase.folder_id == folder_id)
        )
        return result.scalar() or 0

    async def _ensure_name_available(
        self,
        folder_name: str,
        parent_folder_id: str | None,
        exclude_folder_id: str | None = None,
    ) -> None:
        query = select(KBFolder).where(KBFolder.folder_name == folder_name)
        if parent_folder_id is None:
            query = query.where(KBFolder.parent_folder_id.is_(None))
        else:
            query = query.where(KBFolder.parent_folder_id == parent_folder_id)
        if exclude_folder_id is not None:
            query = query.where(KBFolder.folder_id != exclude_folder_id)

        existing = await self.session.execute(query)
        if existing.scalar_one_or_none() is not None:
            raise KBFolderAlreadyExistsError(folder_name)

    async def _get_by_name(
        self, folder_name: str, parent_folder_id: str | None
    ) -> KBFolder | None:
        query = select(KBFolder).where(KBFolder.folder_name == folder_name)
        if parent_folder_id is None:
            query = query.where(KBFolder.parent_folder_id.is_(None))
        else:
            query = query.where(KBFolder.parent_folder_id == parent_folder_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def _create_folder(
        self,
        folder_name: str,
        parent_folder_id: str | None,
        depth: int,
    ) -> KBFolder:
        folder = KBFolder(
            folder_id=generate_folder_id(),
            folder_name=folder_name,
            parent_folder_id=parent_folder_id,
            depth=depth,
        )
        self.session.add(folder)
        await self.session.commit()
        await self.session.refresh(folder)
        return folder
