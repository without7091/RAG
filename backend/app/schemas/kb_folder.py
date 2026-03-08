from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class KBFolderCreateRequest(BaseModel):
    folder_name: str = Field(..., min_length=1, max_length=128)
    parent_folder_id: str | None = Field(default=None, min_length=1, max_length=64)


class KBFolderUpdateRequest(BaseModel):
    folder_name: str = Field(..., min_length=1, max_length=128)


class KBFolderResponse(BaseModel):
    folder_id: str
    folder_name: str
    parent_folder_id: str | None
    depth: int
    created_at: datetime


class KBTreeKnowledgeBaseNode(BaseModel):
    type: Literal["kb"] = "kb"
    knowledge_base_id: str
    knowledge_base_name: str
    description: str
    folder_id: str
    folder_name: str
    parent_folder_id: str | None
    parent_folder_name: str | None
    document_count: int = 0
    created_at: datetime


class KBTreeLeafFolderNode(BaseModel):
    type: Literal["folder"] = "folder"
    folder_id: str
    folder_name: str
    parent_folder_id: str | None
    depth: Literal[2] = 2
    created_at: datetime
    knowledge_base_count: int = 0
    knowledge_bases: list[KBTreeKnowledgeBaseNode]


class KBTreeRootFolderNode(BaseModel):
    type: Literal["folder"] = "folder"
    folder_id: str
    folder_name: str
    parent_folder_id: str | None
    depth: Literal[1] = 1
    created_at: datetime
    child_folder_count: int = 0
    knowledge_base_count: int = 0
    children: list[KBTreeLeafFolderNode]


class KBTreeResponse(BaseModel):
    folders: list[KBTreeRootFolderNode]
    total_knowledge_bases: int
