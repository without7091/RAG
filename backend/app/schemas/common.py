from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    detail: str


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskStatusResponse(BaseModel):
    task_id: str
    status: TaskStatus
    progress: str | None = None
    result: dict | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
