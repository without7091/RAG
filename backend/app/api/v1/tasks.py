from fastapi import APIRouter, Depends

from app.dependencies import get_task_manager
from app.schemas.common import TaskStatusResponse
from app.services.task_manager import TaskManager

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    task_manager: TaskManager = Depends(get_task_manager),
):
    """Get the status of a background task."""
    info = task_manager.get_task(task_id)
    return TaskStatusResponse(
        task_id=info.task_id,
        status=info.status,
        progress=info.progress,
        result=info.result,
        error=info.error,
        created_at=info.created_at,
        updated_at=info.updated_at,
    )
