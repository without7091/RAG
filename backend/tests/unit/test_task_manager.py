import asyncio

import pytest

from app.exceptions import TaskNotFoundError
from app.schemas.common import TaskStatus
from app.services.task_manager import TaskManager


class TestTaskManager:
    def test_create_task(self):
        tm = TaskManager()
        info = tm.create_task()
        assert info.task_id.startswith("task_")
        assert info.status == TaskStatus.PENDING

    def test_get_task(self):
        tm = TaskManager()
        info = tm.create_task()
        found = tm.get_task(info.task_id)
        assert found.task_id == info.task_id

    def test_get_task_not_found(self):
        tm = TaskManager()
        with pytest.raises(TaskNotFoundError):
            tm.get_task("nonexistent")

    def test_update_task(self):
        tm = TaskManager()
        info = tm.create_task()
        tm.update_task(info.task_id, status=TaskStatus.PROCESSING, progress="Working...")
        updated = tm.get_task(info.task_id)
        assert updated.status == TaskStatus.PROCESSING
        assert updated.progress == "Working..."

    def test_update_task_with_result(self):
        tm = TaskManager()
        info = tm.create_task()
        tm.update_task(
            info.task_id,
            status=TaskStatus.COMPLETED,
            result={"doc_id": "abc", "chunk_count": 5},
        )
        updated = tm.get_task(info.task_id)
        assert updated.status == TaskStatus.COMPLETED
        assert updated.result["chunk_count"] == 5

    def test_update_task_with_error(self):
        tm = TaskManager()
        info = tm.create_task()
        tm.update_task(info.task_id, status=TaskStatus.FAILED, error="Something broke")
        updated = tm.get_task(info.task_id)
        assert updated.error == "Something broke"

    def test_list_tasks(self):
        tm = TaskManager()
        tm.create_task()
        tm.create_task()
        tasks = tm.list_tasks()
        assert len(tasks) == 2

    async def test_submit_async_task(self):
        tm = TaskManager()
        info = tm.create_task()
        result_holder = {}

        async def _work():
            result_holder["done"] = True
            tm.update_task(info.task_id, status=TaskStatus.COMPLETED)

        tm.submit(info.task_id, _work())
        await asyncio.sleep(0.1)  # let task finish
        assert result_holder.get("done") is True

    async def test_submit_failing_task(self):
        tm = TaskManager()
        info = tm.create_task()

        async def _fail():
            raise ValueError("boom")

        tm.submit(info.task_id, _fail())
        await asyncio.sleep(0.1)
        updated = tm.get_task(info.task_id)
        assert updated.status == TaskStatus.FAILED
        assert "boom" in updated.error

    def test_to_dict(self):
        tm = TaskManager()
        info = tm.create_task()
        d = info.to_dict()
        assert "task_id" in d
        assert "status" in d
        assert d["status"] == "pending"
