class RAGBaseError(Exception):
    """Base exception for RAG platform."""

    def __init__(self, message: str = "An error occurred"):
        self.message = message
        super().__init__(self.message)


class KnowledgeBaseNotFoundError(RAGBaseError):
    """Raised when a knowledge base is not found."""

    def __init__(self, kb_id: str):
        super().__init__(f"Knowledge base not found: {kb_id}")
        self.kb_id = kb_id


class KnowledgeBaseAlreadyExistsError(RAGBaseError):
    """Raised when creating a knowledge base that already exists."""

    def __init__(self, kb_id: str):
        super().__init__(f"Knowledge base already exists: {kb_id}")
        self.kb_id = kb_id


class KBFolderNotFoundError(RAGBaseError):
    """Raised when a folder is not found."""

    def __init__(self, folder_id: str):
        super().__init__(f"Knowledge base folder not found: {folder_id}")
        self.folder_id = folder_id


class KBFolderAlreadyExistsError(RAGBaseError):
    """Raised when creating a folder that already exists under the same parent."""

    def __init__(self, folder_name: str):
        super().__init__(f"Knowledge base folder already exists: {folder_name}")
        self.folder_name = folder_name


class KBFolderNotEmptyError(RAGBaseError):
    """Raised when deleting a non-empty folder."""

    def __init__(self, folder_id: str):
        super().__init__(f"Knowledge base folder is not empty: {folder_id}")
        self.folder_id = folder_id


class KBFolderValidationError(RAGBaseError):
    """Raised when folder constraints are violated."""

    def __init__(self, message: str):
        super().__init__(message)


class DocumentNotFoundError(RAGBaseError):
    """Raised when a document is not found."""

    def __init__(self, doc_id: str):
        super().__init__(f"Document not found: {doc_id}")
        self.doc_id = doc_id


class ParsingError(RAGBaseError):
    """Raised when document parsing fails."""

    def __init__(self, filename: str, reason: str = ""):
        msg = f"Failed to parse document: {filename}"
        if reason:
            msg += f" ({reason})"
        super().__init__(msg)
        self.filename = filename


class EmbeddingError(RAGBaseError):
    """Raised when embedding API call fails."""

    def __init__(self, message: str = "Embedding API call failed"):
        super().__init__(message)


class RerankerError(RAGBaseError):
    """Raised when reranker API call fails."""

    def __init__(self, message: str = "Reranker API call failed"):
        super().__init__(message)


class QueryRewriteError(RAGBaseError):
    """Raised when query rewrite or chat completion fails."""

    def __init__(self, message: str = "Query rewrite failed"):
        super().__init__(message)


class VectorStoreError(RAGBaseError):
    """Raised when vector store operations fail."""

    def __init__(self, message: str = "Vector store operation failed"):
        super().__init__(message)


class TaskNotFoundError(RAGBaseError):
    """Raised when a background task is not found."""

    def __init__(self, task_id: str):
        super().__init__(f"Task not found: {task_id}")
        self.task_id = task_id


class UnsupportedFileTypeError(RAGBaseError):
    """Raised when an unsupported file type is uploaded."""

    def __init__(self, filename: str, supported: list[str] | None = None):
        supported = supported or [".pdf", ".pptx", ".docx", ".xlsx", ".md", ".txt"]
        super().__init__(
            f"Unsupported file type: {filename}. Supported: {', '.join(supported)}"
        )
        self.filename = filename
