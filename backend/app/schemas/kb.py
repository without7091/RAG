from datetime import datetime

from pydantic import BaseModel, Field


class KBCreateRequest(BaseModel):
    knowledge_base_name: str = Field(..., min_length=1, max_length=128)
    folder_id: str | None = Field(default=None, min_length=1, max_length=64)
    description: str = Field(default="", max_length=512)


class KBCreateResponse(BaseModel):
    knowledge_base_id: str
    knowledge_base_name: str
    folder_id: str | None = None
    folder_name: str | None = None
    parent_folder_id: str | None = None
    parent_folder_name: str | None = None
    description: str
    created_at: datetime


class KBInfo(BaseModel):
    knowledge_base_id: str
    knowledge_base_name: str
    folder_id: str | None = None
    folder_name: str | None = None
    parent_folder_id: str | None = None
    parent_folder_name: str | None = None
    description: str
    document_count: int = 0
    created_at: datetime


class KBListResponse(BaseModel):
    knowledge_bases: list[KBInfo]
    total: int


class KBUpdateRequest(BaseModel):
    knowledge_base_name: str | None = Field(default=None, min_length=1, max_length=128)
    folder_id: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=512)


class KBUpdateResponse(BaseModel):
    knowledge_base_id: str
    knowledge_base_name: str
    folder_id: str | None = None
    folder_name: str | None = None
    parent_folder_id: str | None = None
    parent_folder_name: str | None = None
    description: str
    created_at: datetime


class KBDeleteResponse(BaseModel):
    knowledge_base_id: str
    deleted: bool
