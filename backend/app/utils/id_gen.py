import hashlib
import uuid


def generate_doc_id(content: bytes) -> str:
    """Generate a content-based unique hash for a document."""
    return hashlib.sha256(content).hexdigest()[:32]


def generate_kb_id(name: str) -> str:
    """Generate a knowledge base ID from name + random suffix."""
    suffix = uuid.uuid4().hex[:8]
    safe_name = "".join(c if c.isalnum() else "_" for c in name)[:20].lower()
    return f"kb_{safe_name}_{suffix}"


def generate_task_id() -> str:
    """Generate a unique task ID."""
    return f"task_{uuid.uuid4().hex[:16]}"
