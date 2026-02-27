import aiofiles
from fastapi import APIRouter, Depends, UploadFile

from app.config import get_settings
from app.db.session import get_session_factory
from app.dependencies import (
    get_chunking_service,
    get_doc_service_dep,
    get_embedding_service,
    get_kb_service_dep,
    get_parsing_service,
    get_sparse_embedding_service,
    get_task_manager,
    get_vector_store_service,
)
from app.schemas.document import DocInfo, DocListResponse, DocumentStatus, DocUploadResponse
from app.services.document_service import DocumentService
from app.services.kb_service import KBService
from app.services.pipeline_service import PipelineService
from app.services.task_manager import TaskManager
from app.utils.id_gen import generate_doc_id

router = APIRouter(prefix="/document", tags=["Document"])


@router.post("/upload", response_model=DocUploadResponse)
async def upload_document(
    knowledge_base_id: str,
    file: UploadFile,
    kb_service: KBService = Depends(get_kb_service_dep),
    task_manager: TaskManager = Depends(get_task_manager),
):
    """Upload a document for processing into the knowledge base."""
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

    # Create document record in a new session
    session_factory = get_session_factory()
    async with session_factory() as session:
        doc_service = DocumentService(session)
        await doc_service.create(doc_id, file.filename, knowledge_base_id)

    # Create background task
    task_info = task_manager.create_task()

    # Build pipeline and submit
    async def _run_pipeline():
        async with session_factory() as pipeline_session:
            vs = await get_vector_store_service()
            pipeline = PipelineService(
                session=pipeline_session,
                parsing_service=get_parsing_service(),
                chunking_service=get_chunking_service(),
                embedding_service=get_embedding_service(),
                sparse_embedding_service=get_sparse_embedding_service(),
                vector_store_service=vs,
                task_manager=task_manager,
            )
            await pipeline.run_pipeline(
                task_id=task_info.task_id,
                file_path=str(file_path),
                doc_id=doc_id,
                file_name=file.filename,
                knowledge_base_id=knowledge_base_id,
            )

    task_manager.submit(task_info.task_id, _run_pipeline())

    return DocUploadResponse(
        task_id=task_info.task_id,
        doc_id=doc_id,
        file_name=file.filename,
        knowledge_base_id=knowledge_base_id,
        status=DocumentStatus.PENDING,
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
            upload_timestamp=d.upload_timestamp,
            updated_at=d.updated_at,
        )
        for d in docs
    ]
    return DocListResponse(documents=items, total=len(items))
