from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class DocumentStatus(str, Enum):
    UPLOADED = "uploaded"
    PENDING = "pending"
    PARSING = "parsing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    UPSERTING = "upserting"
    COMPLETED = "completed"
    FAILED = "failed"


class DocUploadResponse(BaseModel):
    doc_id: str
    file_name: str
    knowledge_base_id: str
    status: DocumentStatus
    chunk_size: int | None = None
    chunk_overlap: int | None = None


class DocInfo(BaseModel):
    doc_id: str
    file_name: str
    knowledge_base_id: str
    status: DocumentStatus
    chunk_count: int = 0
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    error_message: str | None = None
    progress_message: str | None = None
    upload_timestamp: datetime
    updated_at: datetime


class DocListResponse(BaseModel):
    documents: list[DocInfo]
    total: int


class DocDeleteResponse(BaseModel):
    doc_id: str
    deleted: bool


class ChunkInfo(BaseModel):
    chunk_index: int
    text: str
    header_path: str = ""
    header_level: int = 0
    content_type: str = "text"


class DocChunksResponse(BaseModel):
    doc_id: str
    file_name: str
    knowledge_base_id: str
    status: DocumentStatus
    chunk_count: int
    chunks: list[ChunkInfo]


class DocRetryResponse(BaseModel):
    doc_id: str
    status: DocumentStatus


class VectorizeRequest(BaseModel):
    knowledge_base_id: str
    doc_ids: list[str] = Field(..., min_length=1)
    chunk_size: int | None = Field(default=None, ge=64, le=8192)
    chunk_overlap: int | None = Field(default=None, ge=0, le=4096)


class VectorizeDocInfo(BaseModel):
    doc_id: str
    status: DocumentStatus


class VectorizeResponse(BaseModel):
    docs: list[VectorizeDocInfo]


class DocSettingsRequest(BaseModel):
    chunk_size: int | None = Field(default=None, ge=64, le=8192)
    chunk_overlap: int | None = Field(default=None, ge=0, le=4096)


class DocSettingsResponse(BaseModel):
    doc_id: str
    chunk_size: int | None = None
    chunk_overlap: int | None = None


# ─── Pre-chunked Upload ───

class ChunkInput(BaseModel):
    text: str = Field(..., min_length=1)
    header_path: str = ""
    header_level: int = Field(default=0, ge=0, le=6)
    content_type: str = "text"
    metadata: dict = Field(default_factory=dict)


class UploadChunksRequest(BaseModel):
    knowledge_base_id: str = Field(..., min_length=1)
    file_name: str = Field(..., min_length=1)
    chunks: list[ChunkInput] = Field(..., min_length=1)
    doc_id: str | None = Field(default=None, description="Optional custom doc_id; auto-generated if null")


class UploadChunksResponse(BaseModel):
    doc_id: str
    file_name: str
    knowledge_base_id: str
    status: DocumentStatus
    chunk_count: int
    is_pre_chunked: bool = True
