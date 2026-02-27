from fastapi import APIRouter

from app.api.v1 import document, kb, retrieve, tasks

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(kb.router)
api_router.include_router(document.router)
api_router.include_router(retrieve.router)
api_router.include_router(tasks.router)
