from fastapi import APIRouter, Depends

from app.dependencies import (
    get_kb_folder_service_dep,
    get_kb_service_dep,
    get_vector_store_service,
)
from app.models.knowledge_base import KnowledgeBase
from app.schemas.kb import (
    KBCreateRequest,
    KBCreateResponse,
    KBDeleteResponse,
    KBInfo,
    KBListResponse,
    KBUpdateRequest,
    KBUpdateResponse,
)
from app.schemas.kb_folder import (
    KBFolderCreateRequest,
    KBFolderResponse,
    KBFolderUpdateRequest,
    KBTreeResponse,
)
from app.services.kb_folder_service import KBFolderService
from app.services.kb_service import KBService
from app.services.vector_store_service import VectorStoreService

router = APIRouter(prefix="/kb", tags=["Knowledge Base"])


def build_kb_info(kb: KnowledgeBase, document_count: int = 0) -> KBInfo:
    return KBInfo(
        knowledge_base_id=kb.knowledge_base_id,
        knowledge_base_name=kb.knowledge_base_name,
        folder_id=kb.folder_id,
        folder_name=kb.folder.folder_name if kb.folder else None,
        parent_folder_id=kb.folder.parent_folder_id if kb.folder else None,
        parent_folder_name=(
            kb.folder.parent.folder_name
            if kb.folder is not None and kb.folder.parent is not None
            else None
        ),
        description=kb.description,
        document_count=document_count,
        created_at=kb.created_at,
    )


@router.post("/create", response_model=KBCreateResponse)
async def create_kb(
    request: KBCreateRequest,
    kb_service: KBService = Depends(get_kb_service_dep),
    vs_service: VectorStoreService = Depends(get_vector_store_service),
):
    """Create a new knowledge base and initialize its Qdrant collection."""
    kb = await kb_service.create(
        request.knowledge_base_name,
        request.description,
        folder_id=request.folder_id,
    )
    await vs_service.create_collection(kb.knowledge_base_id)
    return KBCreateResponse(
        knowledge_base_id=kb.knowledge_base_id,
        knowledge_base_name=kb.knowledge_base_name,
        folder_id=kb.folder_id,
        folder_name=kb.folder.folder_name if kb.folder else None,
        parent_folder_id=kb.folder.parent_folder_id if kb.folder else None,
        parent_folder_name=(
            kb.folder.parent.folder_name
            if kb.folder is not None and kb.folder.parent is not None
            else None
        ),
        description=kb.description,
        created_at=kb.created_at,
    )


@router.get("/list", response_model=KBListResponse)
async def list_kbs(
    kb_service: KBService = Depends(get_kb_service_dep),
):
    """List all knowledge bases."""
    kbs = await kb_service.list_all()
    items = [
        build_kb_info(kb, document_count=await kb_service.get_document_count(kb.knowledge_base_id))
        for kb in kbs
    ]
    return KBListResponse(knowledge_bases=items, total=len(items))


@router.get("/tree", response_model=KBTreeResponse)
async def list_kb_tree(
    kb_service: KBService = Depends(get_kb_service_dep),
):
    """List knowledge bases in a fixed two-level folder tree."""
    folders = await kb_service.list_tree()
    total = sum(child.knowledge_base_count for folder in folders for child in folder.children)
    return KBTreeResponse(folders=folders, total_knowledge_bases=total)


@router.post("/folders", response_model=KBFolderResponse)
async def create_kb_folder(
    request: KBFolderCreateRequest,
    folder_service: KBFolderService = Depends(get_kb_folder_service_dep),
):
    folder = await folder_service.create(
        request.folder_name,
        parent_folder_id=request.parent_folder_id,
    )
    return KBFolderResponse(
        folder_id=folder.folder_id,
        folder_name=folder.folder_name,
        parent_folder_id=folder.parent_folder_id,
        depth=folder.depth,
        created_at=folder.created_at,
    )


@router.patch("/folders/{folder_id}", response_model=KBFolderResponse)
async def update_kb_folder(
    folder_id: str,
    request: KBFolderUpdateRequest,
    folder_service: KBFolderService = Depends(get_kb_folder_service_dep),
):
    folder = await folder_service.update(folder_id, request.folder_name)
    return KBFolderResponse(
        folder_id=folder.folder_id,
        folder_name=folder.folder_name,
        parent_folder_id=folder.parent_folder_id,
        depth=folder.depth,
        created_at=folder.created_at,
    )


@router.delete("/folders/{folder_id}", response_model=KBFolderResponse)
async def delete_kb_folder(
    folder_id: str,
    folder_service: KBFolderService = Depends(get_kb_folder_service_dep),
):
    folder = await folder_service.get_by_id(folder_id)
    response = KBFolderResponse(
        folder_id=folder.folder_id,
        folder_name=folder.folder_name,
        parent_folder_id=folder.parent_folder_id,
        depth=folder.depth,
        created_at=folder.created_at,
    )
    await folder_service.delete(folder_id)
    return response


@router.patch("/{kb_id}", response_model=KBUpdateResponse)
async def update_kb(
    kb_id: str,
    request: KBUpdateRequest,
    kb_service: KBService = Depends(get_kb_service_dep),
):
    """Update a knowledge base's name, description, and/or folder."""
    kb = await kb_service.update(
        kb_id,
        name=request.knowledge_base_name,
        description=request.description,
        folder_id=request.folder_id,
    )
    return KBUpdateResponse(
        knowledge_base_id=kb.knowledge_base_id,
        knowledge_base_name=kb.knowledge_base_name,
        folder_id=kb.folder_id,
        folder_name=kb.folder.folder_name if kb.folder else None,
        parent_folder_id=kb.folder.parent_folder_id if kb.folder else None,
        parent_folder_name=(
            kb.folder.parent.folder_name
            if kb.folder is not None and kb.folder.parent is not None
            else None
        ),
        description=kb.description,
        created_at=kb.created_at,
    )


@router.delete("/{kb_id}", response_model=KBDeleteResponse)
async def delete_kb(
    kb_id: str,
    kb_service: KBService = Depends(get_kb_service_dep),
    vs_service: VectorStoreService = Depends(get_vector_store_service),
):
    """Delete a knowledge base and its Qdrant collection."""
    await kb_service.delete(kb_id)
    try:
        await vs_service.delete_collection(kb_id)
    except Exception:
        pass  # Collection may not exist
    return KBDeleteResponse(knowledge_base_id=kb_id, deleted=True)
