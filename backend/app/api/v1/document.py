import json

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from app.config import get_settings
from app.db.session import get_session_factory
from app.dependencies import (
    get_doc_service_dep,
    get_kb_service_dep,
    get_vector_store_service,
)
from app.models.document import DocumentStatus as ModelDocumentStatus
from app.schemas.document import (
    ChunkInfo,
    DocChunksResponse,
    DocDeleteResponse,
    DocInfo,
    DocListResponse,
    DocRetryResponse,
    DocSettingsRequest,
    DocSettingsResponse,
    DocumentStatus,
    DocUploadResponse,
    UploadChunksResponse,
    VectorizeDocInfo,
    VectorizeRequest,
    VectorizeResponse,
)
from app.services.document_service import DocumentService
from app.services.kb_service import KBService
from app.services.vector_store_service import VectorStoreService
from app.utils.id_gen import generate_doc_id

router = APIRouter(prefix="/document", tags=["Document"])


@router.post("/upload", response_model=DocUploadResponse)
async def upload_document(
    knowledge_base_id: str,
    file: UploadFile,
    chunk_size: int | None = Query(default=None, ge=64, le=8192),
    chunk_overlap: int | None = Query(default=None, ge=0, le=4096),
    kb_service: KBService = Depends(get_kb_service_dep),
):
    """Upload a document to the knowledge base (file save only, no pipeline).

    Use POST /document/vectorize to start the vectorization pipeline.
    """
    # Validate KB exists
    await kb_service.get_by_id(knowledge_base_id)

    settings = get_settings()

    # Read file content
    content = await file.read()

    # Generate content-based doc_id
    doc_id = generate_doc_id(content)

    # Save file to upload directory
    upload_dir = settings.upload_path / knowledge_base_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / file.filename
    async with aiofiles.open(str(file_path), "wb") as f:
        await f.write(content)

    # Create document record in a new session (status=UPLOADED)
    session_factory = get_session_factory()
    async with session_factory() as session:
        doc_service = DocumentService(session)
        await doc_service.create(
            doc_id,
            file.filename,
            knowledge_base_id,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    return DocUploadResponse(
        doc_id=doc_id,
        file_name=file.filename,
        knowledge_base_id=knowledge_base_id,
        status=DocumentStatus.UPLOADED,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )


@router.post("/upload-chunks", response_model=UploadChunksResponse)
async def upload_chunks(
    knowledge_base_id: str,
    file: UploadFile,
    kb_service: KBService = Depends(get_kb_service_dep),
):
    """Upload a pre-chunked JSON file as a document source.

    The JSON file is validated, saved as the source file (same as normal upload),
    and the document is marked as is_pre_chunked=True. The pipeline will skip
    parsing and chunking, going directly to embedding and upsert.

    Use POST /document/vectorize to start the vectorization pipeline.
    """
    # Validate KB exists
    await kb_service.get_by_id(knowledge_base_id)

    # Validate file extension
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="仅支持 .json 文件")

    # Read and validate JSON structure
    content = await file.read()
    try:
        chunks_data = json.loads(content.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(status_code=400, detail=f"JSON 解析失败: {e}")

    if not isinstance(chunks_data, list):
        raise HTTPException(status_code=400, detail="顶层结构必须为数组 []")
    if len(chunks_data) == 0:
        raise HTTPException(status_code=400, detail="切片数组不能为空")

    for i, item in enumerate(chunks_data):
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail=f"第 {i + 1} 项不是有效对象")
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise HTTPException(status_code=400, detail=f"第 {i + 1} 项缺少非空 text 字段")
        hl = item.get("header_level")
        if hl is not None:
            if not isinstance(hl, int) or hl < 0 or hl > 6:
                raise HTTPException(
                    status_code=400,
                    detail=f"第 {i + 1} 项 header_level 必须为 0-6 整数",
                )

    settings = get_settings()

    # Generate doc_id from file content
    doc_id = generate_doc_id(content)

    # Save JSON file as source (same pattern as normal upload)
    upload_dir = settings.upload_path / knowledge_base_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_path = upload_dir / file.filename
    async with aiofiles.open(str(file_path), "wb") as f:
        await f.write(content)

    # Create document record (status=UPLOADED, is_pre_chunked=True)
    session_factory = get_session_factory()
    async with session_factory() as session:
        doc_service = DocumentService(session)
        await doc_service.create(
            doc_id,
            file.filename,
            knowledge_base_id,
            is_pre_chunked=True,
        )

    return UploadChunksResponse(
        doc_id=doc_id,
        file_name=file.filename,
        knowledge_base_id=knowledge_base_id,
        status=DocumentStatus.UPLOADED,
        chunk_count=len(chunks_data),
        is_pre_chunked=True,
    )


@router.get("/list/{kb_id}", response_model=DocListResponse)
async def list_documents(
    kb_id: str,
    doc_service: DocumentService = Depends(get_doc_service_dep),
):
    """List all documents in a knowledge base."""
    docs = await doc_service.list_by_kb(kb_id)
    items = [
        DocInfo(
            doc_id=d.doc_id,
            file_name=d.file_name,
            knowledge_base_id=d.knowledge_base_id,
            status=DocumentStatus(d.status.value),
            chunk_count=d.chunk_count,
            chunk_size=d.chunk_size,
            chunk_overlap=d.chunk_overlap,
            is_pre_chunked=d.is_pre_chunked,
            error_message=d.error_message,
            progress_message=d.progress_message,
            upload_timestamp=d.upload_timestamp,
            updated_at=d.updated_at,
        )
        for d in docs
    ]
    return DocListResponse(documents=items, total=len(items))


@router.delete("/{kb_id}/{doc_id}", response_model=DocDeleteResponse)
async def delete_document(
    kb_id: str,
    doc_id: str,
    doc_service: DocumentService = Depends(get_doc_service_dep),
    vs_service: VectorStoreService = Depends(get_vector_store_service),
):
    """Delete a single document and its vectors from the knowledge base."""
    await doc_service.delete(doc_id, kb_id)
    try:
        await vs_service.delete_by_doc_id(kb_id, doc_id)
    except Exception:
        pass  # Vectors may not exist
    return DocDeleteResponse(doc_id=doc_id, deleted=True)


@router.get("/{kb_id}/{doc_id}/chunks", response_model=DocChunksResponse)
async def get_document_chunks(
    kb_id: str,
    doc_id: str,
    doc_service: DocumentService = Depends(get_doc_service_dep),
    vs_service: VectorStoreService = Depends(get_vector_store_service),
):
    """Get document metadata and its stored chunks from the vector store."""
    doc = await doc_service.get_by_doc_id_and_kb(doc_id, kb_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    chunks: list[dict] = []
    if doc.status.value == "completed" and doc.chunk_count > 0:
        try:
            chunks = await vs_service.get_chunks_by_doc_id(kb_id, doc_id)
        except Exception:
            pass  # Collection may not exist yet

    return DocChunksResponse(
        doc_id=doc.doc_id,
        file_name=doc.file_name,
        knowledge_base_id=doc.knowledge_base_id,
        status=DocumentStatus(doc.status.value),
        chunk_count=doc.chunk_count,
        chunks=[ChunkInfo(**c) for c in chunks],
    )


@router.post("/vectorize", response_model=VectorizeResponse)
async def vectorize_documents(
    request: VectorizeRequest,
    kb_service: KBService = Depends(get_kb_service_dep),
):
    """Start vectorization pipeline for one or more uploaded/failed documents.

    Sets documents to PENDING status. The background PipelineWorker will
    pick them up and process with controlled concurrency.
    """
    await kb_service.get_by_id(request.knowledge_base_id)

    settings = get_settings()
    session_factory = get_session_factory()
    docs_result: list[VectorizeDocInfo] = []

    async with session_factory() as session:
        doc_service = DocumentService(session)
        for doc_id in request.doc_ids:
            doc = await doc_service.get_by_doc_id_and_kb(doc_id, request.knowledge_base_id)
            if doc is None:
                raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")
            if doc.status.value not in ("uploaded", "failed", "completed"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Document {doc_id} status is '{doc.status.value}', must be 'uploaded', 'failed', or 'completed'",
                )

            # Determine chunk params: request override > doc stored > global default
            effective_chunk_size = request.chunk_size or doc.chunk_size
            effective_chunk_overlap = request.chunk_overlap or doc.chunk_overlap

            # Cross-field validation
            if (
                effective_chunk_size is not None
                and effective_chunk_overlap is not None
                and effective_chunk_overlap >= effective_chunk_size
            ):
                raise HTTPException(
                    status_code=400,
                    detail=f"chunk_overlap ({effective_chunk_overlap}) must be less than chunk_size ({effective_chunk_size})",
                )

            # Set cleanup flag if re-vectorizing a completed doc
            if doc.status.value == "completed":
                doc.needs_vector_cleanup = True

            # Persist override values
            if request.chunk_size is not None:
                doc.chunk_size = request.chunk_size
            if request.chunk_overlap is not None:
                doc.chunk_overlap = request.chunk_overlap

            # Verify source file exists
            file_path = settings.upload_path / request.knowledge_base_id / doc.file_name
            if not file_path.exists():
                raise HTTPException(
                    status_code=404,
                    detail=f"Original file not found for doc {doc_id}",
                )

            doc.status = ModelDocumentStatus.PENDING
            doc.error_message = None
            doc.progress_message = None
            await session.commit()

            docs_result.append(
                VectorizeDocInfo(
                    doc_id=doc_id,
                    status=DocumentStatus.PENDING,
                )
            )

    return VectorizeResponse(docs=docs_result)


@router.post("/{kb_id}/{doc_id}/retry", response_model=DocRetryResponse)
async def retry_document(
    kb_id: str,
    doc_id: str,
    doc_service: DocumentService = Depends(get_doc_service_dep),
):
    """Retry processing a failed, uploaded, or completed document.

    Sets the document to PENDING status. The background PipelineWorker
    will pick it up automatically.
    """
    doc = await doc_service.get_by_doc_id_and_kb(doc_id, kb_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")
    if doc.status.value not in ("failed", "uploaded", "completed"):
        raise HTTPException(
            status_code=400,
            detail=f"Only failed/uploaded/completed documents can be retried, current status: {doc.status.value}",
        )

    settings = get_settings()
    file_path = settings.upload_path / kb_id / doc.file_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Original file not found on disk")

    # Set cleanup flag if re-processing a completed doc
    if doc.status.value == "completed":
        doc.needs_vector_cleanup = True

    # Reset status to PENDING for worker pickup
    await doc_service.update_status(doc_id, kb_id, ModelDocumentStatus.PENDING)

    return DocRetryResponse(
        doc_id=doc_id,
        status=DocumentStatus.PENDING,
    )


@router.get("/{kb_id}/{doc_id}/download")
async def download_document(
    kb_id: str,
    doc_id: str,
    doc_service: DocumentService = Depends(get_doc_service_dep),
):
    """Download the original uploaded file."""
    doc = await doc_service.get_by_doc_id_and_kb(doc_id, kb_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    settings = get_settings()
    file_path = settings.upload_path / kb_id / doc.file_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        path=str(file_path),
        filename=doc.file_name,
        media_type="application/octet-stream",
    )


@router.patch("/{kb_id}/{doc_id}/settings", response_model=DocSettingsResponse)
async def update_document_settings(
    kb_id: str,
    doc_id: str,
    body: DocSettingsRequest,
    doc_service: DocumentService = Depends(get_doc_service_dep),
):
    """Update chunking parameters for a document."""
    doc = await doc_service.get_by_doc_id_and_kb(doc_id, kb_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    if body.chunk_size is not None:
        doc.chunk_size = body.chunk_size
    if body.chunk_overlap is not None:
        doc.chunk_overlap = body.chunk_overlap

    # Cross-field validation: overlap must be less than size
    effective_size = doc.chunk_size
    effective_overlap = doc.chunk_overlap
    if effective_size is not None and effective_overlap is not None:
        if effective_overlap >= effective_size:
            raise HTTPException(
                status_code=400,
                detail="chunk_overlap must be less than chunk_size",
            )
    await doc_service.session.commit()
    await doc_service.session.refresh(doc)

    return DocSettingsResponse(
        doc_id=doc.doc_id,
        chunk_size=doc.chunk_size,
        chunk_overlap=doc.chunk_overlap,
    )
