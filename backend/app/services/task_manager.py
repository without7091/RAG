import asyncio
import logging
from datetime import datetime, timezone

from app.exceptions import TaskNotFoundError
from app.schemas.common import TaskStatus
from app.utils.id_gen import generate_task_id

logger = logging.getLogger(__name__)


class TaskInfo:
    __slots__ = ("task_id", "status", "progress", "result", "error", "created_at", "updated_at")

    def __init__(self, task_id: str):
        self.task_id = task_id
        self.status = TaskStatus.PENDING
        self.progress: str | None = None
        self.result: dict | None = None
        self.error: str | None = None
        now = datetime.now(timezone.utc)
        self.created_at = now
        self.updated_at = now

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class TaskManager:
    """In-process async task manager backed by asyncio.create_task."""

    def __init__(self):
        self._tasks: dict[str, TaskInfo] = {}
        self._async_tasks: dict[str, asyncio.Task] = {}

    def create_task(self) -> TaskInfo:
        task_id = generate_task_id()
        info = TaskInfo(task_id)
        self._tasks[task_id] = info
        return info

    def get_task(self, task_id: str) -> TaskInfo:
        info = self._tasks.get(task_id)
        if info is None:
            raise TaskNotFoundError(task_id)
        return info

    def update_task(
        self,
        task_id: str,
        status: TaskStatus | None = None,
        progress: str | None = None,
        result: dict | None = None,
        error: str | None = None,
    ) -> TaskInfo:
        info = self.get_task(task_id)
        if status is not None:
            info.status = status
        if progress is not None:
            info.progress = progress
        if result is not None:
            info.result = result
        if error is not None:
            info.error = error
        info.updated_at = datetime.now(timezone.utc)
        return info

    def submit(self, task_id: str, coro) -> None:
        """Submit an async coroutine as a background task."""
        async_task = asyncio.create_task(coro)
        self._async_tasks[task_id] = async_task

        def _on_done(t: asyncio.Task):
            if t.exception():
                logger.error(f"Task {task_id} failed: {t.exception()}")
                self.update_task(
                    task_id,
                    status=TaskStatus.FAILED,
                    error=str(t.exception()),
                )

        async_task.add_done_callback(_on_done)

    def list_tasks(self) -> list[TaskInfo]:
        return list(self._tasks.values())
