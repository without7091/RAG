from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import KnowledgeBaseAlreadyExistsError, KnowledgeBaseNotFoundError
from app.models.document import Document
from app.models.kb_folder import KBFolder
from app.models.knowledge_base import KnowledgeBase
from app.schemas.kb_folder import (
    KBTreeKnowledgeBaseNode,
    KBTreeLeafFolderNode,
    KBTreeRootFolderNode,
)
from app.services.kb_folder_service import KBFolderService
from app.utils.id_gen import generate_kb_id


class KBService:
    def __init__(
        self,
        session: AsyncSession,
        folder_service: KBFolderService | None = None,
    ):
        self.session = session
        self.folder_service = folder_service or KBFolderService(session)

    async def create(
        self,
        name: str,
        description: str = "",
        folder_id: str | None = None,
    ) -> KnowledgeBase:
        folder = await self.folder_service.resolve_leaf_folder(folder_id)
        normalized_name = name.strip()
        await self._ensure_name_available(normalized_name, folder.folder_id)

        kb = KnowledgeBase(
            knowledge_base_id=generate_kb_id(),
            knowledge_base_name=normalized_name,
            folder_id=folder.folder_id,
            description=description,
        )
        self.session.add(kb)
        await self.session.commit()
        return await self.get_by_id(kb.knowledge_base_id)

    async def get_by_id(self, kb_id: str) -> KnowledgeBase:
        result = await self.session.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.knowledge_base_id == kb_id)
            .options(selectinload(KnowledgeBase.folder).selectinload(KBFolder.parent))
        )
        kb = result.scalar_one_or_none()
        if kb is None:
            raise KnowledgeBaseNotFoundError(kb_id)
        return kb

    async def list_all(self) -> list[KnowledgeBase]:
        await self.assign_default_folder_to_unassigned()
        result = await self.session.execute(
            select(KnowledgeBase)
            .options(selectinload(KnowledgeBase.folder).selectinload(KBFolder.parent))
            .order_by(KnowledgeBase.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_tree(self) -> list[KBTreeRootFolderNode]:
        await self.assign_default_folder_to_unassigned()
        doc_counts = await self._get_document_count_map()

        folders_result = await self.session.execute(
            select(KBFolder).order_by(KBFolder.depth.asc(), KBFolder.created_at.desc())
        )
        folders = list(folders_result.scalars().all())

        kb_result = await self.session.execute(
            select(KnowledgeBase)
            .options(selectinload(KnowledgeBase.folder).selectinload(KBFolder.parent))
            .order_by(KnowledgeBase.created_at.desc())
        )
        knowledge_bases = list(kb_result.scalars().all())

        root_nodes: list[KBTreeRootFolderNode] = []
        root_map: dict[str, KBTreeRootFolderNode] = {}
        leaf_map: dict[str, KBTreeLeafFolderNode] = {}

        for folder in folders:
            if folder.depth == 1:
                root_node = KBTreeRootFolderNode(
                    folder_id=folder.folder_id,
                    folder_name=folder.folder_name,
                    parent_folder_id=folder.parent_folder_id,
                    created_at=folder.created_at,
                    child_folder_count=0,
                    knowledge_base_count=0,
                    children=[],
                )
                root_nodes.append(root_node)
                root_map[folder.folder_id] = root_node

        for folder in folders:
            if folder.depth != 2:
                continue
            leaf_node = KBTreeLeafFolderNode(
                folder_id=folder.folder_id,
                folder_name=folder.folder_name,
                parent_folder_id=folder.parent_folder_id,
                created_at=folder.created_at,
                knowledge_base_count=0,
                knowledge_bases=[],
            )
            leaf_map[folder.folder_id] = leaf_node
            parent = root_map.get(folder.parent_folder_id or "")
            if parent is not None:
                parent.children.append(leaf_node)
                parent.child_folder_count += 1

        for kb in knowledge_bases:
            if kb.folder_id is None:
                continue
            leaf_node = leaf_map.get(kb.folder_id)
            if leaf_node is None:
                continue
            leaf_node.knowledge_bases.append(
                KBTreeKnowledgeBaseNode(
                    knowledge_base_id=kb.knowledge_base_id,
                    knowledge_base_name=kb.knowledge_base_name,
                    description=kb.description,
                    folder_id=kb.folder_id,
                    folder_name=kb.folder.folder_name if kb.folder else "",
                    parent_folder_id=kb.folder.parent_folder_id if kb.folder else None,
                    parent_folder_name=(
                        kb.folder.parent.folder_name
                        if kb.folder is not None and kb.folder.parent is not None
                        else None
                    ),
                    document_count=doc_counts.get(kb.knowledge_base_id, 0),
                    created_at=kb.created_at,
                )
            )
            leaf_node.knowledge_base_count += 1

        for root in root_nodes:
            root.knowledge_base_count = sum(
                child.knowledge_base_count for child in root.children
            )

        return root_nodes

    async def delete(self, kb_id: str) -> None:
        kb = await self.get_by_id(kb_id)
        await self.session.delete(kb)
        await self.session.commit()

    async def update(
        self,
        kb_id: str,
        name: str | None = None,
        description: str | None = None,
        folder_id: str | None = None,
    ) -> KnowledgeBase:
        kb = await self.get_by_id(kb_id)
        target_folder_id = kb.folder_id
        if folder_id is not None:
            target_folder = await self.folder_service.resolve_leaf_folder(folder_id)
            target_folder_id = target_folder.folder_id

        target_name = kb.knowledge_base_name if name is None else name.strip()
        await self._ensure_name_available(
            target_name,
            target_folder_id,
            exclude_kb_id=kb_id,
        )

        if name is not None:
            kb.knowledge_base_name = target_name
        if description is not None:
            kb.description = description
        if folder_id is not None:
            kb.folder_id = target_folder_id

        await self.session.commit()
        return await self.get_by_id(kb_id)

    async def get_document_count(self, kb_id: str) -> int:
        result = await self.session.execute(
            select(func.count(Document.id)).where(Document.knowledge_base_id == kb_id)
        )
        return result.scalar() or 0

    async def assign_default_folder_to_unassigned(self) -> int:
        leaf_folder = await self.folder_service.ensure_default_hierarchy()
        result = await self.session.execute(
            select(KnowledgeBase).where(KnowledgeBase.folder_id.is_(None))
        )
        knowledge_bases = list(result.scalars().all())
        if not knowledge_bases:
            return 0

        for kb in knowledge_bases:
            kb.folder_id = leaf_folder.folder_id

        await self.session.commit()
        return len(knowledge_bases)

    async def _ensure_name_available(
        self,
        name: str,
        folder_id: str | None,
        exclude_kb_id: str | None = None,
    ) -> None:
        query = select(KnowledgeBase).where(KnowledgeBase.knowledge_base_name == name)
        if folder_id is None:
            query = query.where(KnowledgeBase.folder_id.is_(None))
        else:
            query = query.where(KnowledgeBase.folder_id == folder_id)
        if exclude_kb_id is not None:
            query = query.where(KnowledgeBase.knowledge_base_id != exclude_kb_id)

        existing = await self.session.execute(query)
        if existing.scalar_one_or_none() is not None:
            raise KnowledgeBaseAlreadyExistsError(name)

    async def _get_document_count_map(self) -> dict[str, int]:
        result = await self.session.execute(
            select(
                Document.knowledge_base_id,
                func.count(Document.id),
            ).group_by(Document.knowledge_base_id)
        )
        return {kb_id: count for kb_id, count in result.all()}
