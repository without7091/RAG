from pydantic import BaseModel, Field


class SourceNode(BaseModel):
    text: str
    score: float
    doc_id: str
    file_name: str
    knowledge_base_id: str
    chunk_index: int | None = None
    header_path: str | None = None
    context_text: str | None = None
    metadata: dict = Field(default_factory=dict)


class RetrieveRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    knowledge_base_id: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=20, ge=1, le=100)
    top_n: int = Field(default=3, ge=1, le=50)
    min_score: float | None = Field(default=None, ge=0.0, le=1.0)
    enable_reranker: bool = Field(default=True, description="Enable reranker for result reranking")
    stream: bool = Field(default=True, description="SSE streaming mode")


class RetrieveResponse(BaseModel):
    query: str
    knowledge_base_id: str
    source_nodes: list[SourceNode]
    total_candidates: int
    top_k_used: int
    top_n_used: int
    min_score_used: float | None = None
    enable_reranker_used: bool = True
