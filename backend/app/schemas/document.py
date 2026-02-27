from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class DocumentStatus(str, Enum):
    PENDING = "pending"
    PARSING = "parsing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    UPSERTING = "upserting"
    COMPLETED = "completed"
    FAILED = "failed"


class DocUploadResponse(BaseModel):
    task_id: str
    doc_id: str
    file_name: str
    knowledge_base_id: str
    status: DocumentStatus


class DocInfo(BaseModel):
    doc_id: str
    file_name: str
    knowledge_base_id: str
    status: DocumentStatus
    chunk_count: int = 0
    upload_timestamp: datetime
    updated_at: datetime


class DocListResponse(BaseModel):
    documents: list[DocInfo]
    total: int
