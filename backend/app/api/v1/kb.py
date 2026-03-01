from fastapi import APIRouter, Depends

from app.dependencies import get_kb_service_dep, get_vector_store_service
from app.schemas.kb import (
    KBCreateRequest,
    KBCreateResponse,
    KBDeleteResponse,
    KBInfo,
    KBListResponse,
    KBUpdateRequest,
    KBUpdateResponse,
)
from app.services.kb_service import KBService
from app.services.vector_store_service import VectorStoreService

router = APIRouter(prefix="/kb", tags=["Knowledge Base"])


@router.post("/create", response_model=KBCreateResponse)
async def create_kb(
    request: KBCreateRequest,
    kb_service: KBService = Depends(get_kb_service_dep),
    vs_service: VectorStoreService = Depends(get_vector_store_service),
):
    """Create a new knowledge base and initialize its Qdrant collection."""
    kb = await kb_service.create(request.knowledge_base_name, request.description)
    await vs_service.create_collection(kb.knowledge_base_id)
    return KBCreateResponse(
        knowledge_base_id=kb.knowledge_base_id,
        knowledge_base_name=kb.knowledge_base_name,
        description=kb.description,
        created_at=kb.created_at,
    )


@router.get("/list", response_model=KBListResponse)
async def list_kbs(
    kb_service: KBService = Depends(get_kb_service_dep),
):
    """List all knowledge bases."""
    kbs = await kb_service.list_all()
    items = []
    for kb in kbs:
        doc_count = await kb_service.get_document_count(kb.knowledge_base_id)
        items.append(
            KBInfo(
                knowledge_base_id=kb.knowledge_base_id,
                knowledge_base_name=kb.knowledge_base_name,
                description=kb.description,
                document_count=doc_count,
                created_at=kb.created_at,
            )
        )
    return KBListResponse(knowledge_bases=items, total=len(items))


@router.patch("/{kb_id}", response_model=KBUpdateResponse)
async def update_kb(
    kb_id: str,
    request: KBUpdateRequest,
    kb_service: KBService = Depends(get_kb_service_dep),
):
    """Update a knowledge base's name and/or description."""
    kb = await kb_service.update(
        kb_id,
        name=request.knowledge_base_name,
        description=request.description,
    )
    return KBUpdateResponse(
        knowledge_base_id=kb.knowledge_base_id,
        knowledge_base_name=kb.knowledge_base_name,
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
