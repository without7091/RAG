from pydantic import BaseModel, Field


class SourceNode(BaseModel):
    text: str
    score: float
    doc_id: str
    file_name: str
    knowledge_base_id: str
    chunk_index: int | None = None
    header_path: str | None = None
    metadata: dict = Field(default_factory=dict)


class RetrieveRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    knowledge_base_id: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=10, ge=1, le=100)
    top_n: int = Field(default=3, ge=1, le=50)
    stream: bool = Field(default=True, description="SSE streaming mode")


class RetrieveResponse(BaseModel):
    query: str
    knowledge_base_id: str
    source_nodes: list[SourceNode]
    total_candidates: int
    top_k_used: int
    top_n_used: int
