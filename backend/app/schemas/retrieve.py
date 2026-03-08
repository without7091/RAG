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


class QueryPlanDebug(BaseModel):
    enabled: bool
    strategy: str
    canonical_query: str
    generated_queries: list[str] = Field(default_factory=list)
    final_queries: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    fallback_used: bool = False
    model: str | None = None


class CandidateStatsDebug(BaseModel):
    query_count: int
    raw_candidate_count: int
    merged_candidate_count: int
    rerank_pool_size: int


class RetrieveDebug(BaseModel):
    query_plan: QueryPlanDebug | None = None
    candidate_stats: CandidateStatsDebug | None = None


class RetrieveRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    knowledge_base_id: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=20, ge=1, le=100)
    top_n: int = Field(default=3, ge=1, le=50)
    min_score: float | None = Field(default=None, ge=0.0, le=1.0)
    enable_reranker: bool = Field(default=True, description="Enable reranker for result reranking")
    enable_context_synthesis: bool = Field(
        default=True,
        description="Enable adjacent chunk context synthesis for context_text",
    )
    enable_query_rewrite: bool = Field(
        default=False,
        description="Enable query rewrite for this request",
    )
    query_rewrite_debug: bool = Field(
        default=False,
        description="Include query rewrite and candidate debug info in response",
    )
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
    enable_context_synthesis_used: bool = True
    debug: RetrieveDebug | None = None
