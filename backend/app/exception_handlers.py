from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.exceptions import (
    DocumentNotFoundError,
    EmbeddingError,
    KBFolderAlreadyExistsError,
    KBFolderNotEmptyError,
    KBFolderNotFoundError,
    KBFolderValidationError,
    KnowledgeBaseAlreadyExistsError,
    KnowledgeBaseNotFoundError,
    ParsingError,
    RAGBaseError,
    RerankerError,
    TaskNotFoundError,
    UnsupportedFileTypeError,
    VectorStoreError,
)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(KnowledgeBaseNotFoundError)
    async def kb_not_found_handler(request: Request, exc: KnowledgeBaseNotFoundError):
        return JSONResponse(status_code=404, content={"detail": exc.message})

    @app.exception_handler(KnowledgeBaseAlreadyExistsError)
    async def kb_already_exists_handler(
        request: Request, exc: KnowledgeBaseAlreadyExistsError
    ):
        return JSONResponse(status_code=409, content={"detail": exc.message})

    @app.exception_handler(KBFolderNotFoundError)
    async def kb_folder_not_found_handler(request: Request, exc: KBFolderNotFoundError):
        return JSONResponse(status_code=404, content={"detail": exc.message})

    @app.exception_handler(KBFolderAlreadyExistsError)
    async def kb_folder_already_exists_handler(
        request: Request, exc: KBFolderAlreadyExistsError
    ):
        return JSONResponse(status_code=409, content={"detail": exc.message})

    @app.exception_handler(KBFolderNotEmptyError)
    async def kb_folder_not_empty_handler(request: Request, exc: KBFolderNotEmptyError):
        return JSONResponse(status_code=409, content={"detail": exc.message})

    @app.exception_handler(KBFolderValidationError)
    async def kb_folder_validation_handler(request: Request, exc: KBFolderValidationError):
        return JSONResponse(status_code=400, content={"detail": exc.message})

    @app.exception_handler(DocumentNotFoundError)
    async def doc_not_found_handler(request: Request, exc: DocumentNotFoundError):
        return JSONResponse(status_code=404, content={"detail": exc.message})

    @app.exception_handler(TaskNotFoundError)
    async def task_not_found_handler(request: Request, exc: TaskNotFoundError):
        return JSONResponse(status_code=404, content={"detail": exc.message})

    @app.exception_handler(UnsupportedFileTypeError)
    async def unsupported_file_handler(request: Request, exc: UnsupportedFileTypeError):
        return JSONResponse(status_code=400, content={"detail": exc.message})

    @app.exception_handler(ParsingError)
    async def parsing_error_handler(request: Request, exc: ParsingError):
        return JSONResponse(status_code=422, content={"detail": exc.message})

    @app.exception_handler(EmbeddingError)
    async def embedding_error_handler(request: Request, exc: EmbeddingError):
        return JSONResponse(status_code=502, content={"detail": exc.message})

    @app.exception_handler(RerankerError)
    async def reranker_error_handler(request: Request, exc: RerankerError):
        return JSONResponse(status_code=502, content={"detail": exc.message})

    @app.exception_handler(VectorStoreError)
    async def vector_store_error_handler(request: Request, exc: VectorStoreError):
        return JSONResponse(status_code=500, content={"detail": exc.message})

    @app.exception_handler(RAGBaseError)
    async def rag_base_error_handler(request: Request, exc: RAGBaseError):
        return JSONResponse(status_code=500, content={"detail": exc.message})
