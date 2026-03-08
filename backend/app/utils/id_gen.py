import hashlib
import uuid


def generate_doc_id(content: bytes) -> str:
    """Generate a content-based unique hash for a document."""
    return hashlib.sha256(content).hexdigest()[:32]


def generate_kb_id() -> str:
    """Generate a random knowledge base ID (decoupled from name)."""
    return f"kb_{uuid.uuid4().hex[:16]}"


def generate_folder_id() -> str:
    """Generate a random knowledge base folder ID."""
    return f"folder_{uuid.uuid4().hex[:16]}"


def generate_task_id() -> str:
    """Generate a unique task ID."""
    return f"task_{uuid.uuid4().hex[:16]}"
