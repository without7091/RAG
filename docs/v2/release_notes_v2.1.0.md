# RAG v2.1.0 发布说明

> 发布日期：2026-03-08
> 适用范围：内网大模型接入、文档入库链路、检索链路健壮性

## 概述

`v2.1.0` 聚焦内网模型 API 的稳定性治理，覆盖三类上游调用：

1. `embedding`：文档向量化与查询向量化；
2. `reranker`：检索结果重排；
3. `chat / query rewrite`：查询改写与检索前增强。

本次版本重点解决长耗时、临时 5xx、并发放大和误失败问题，目标是在不牺牲现有检索体验的前提下，提升内网部署环境下的可恢复性和可观测性。

## 重点更新

### 1. HTTP 超时从固定值改为可配置

- 共享 HTTP 客户端不再硬编码 `60s` 超时；
- 新增四段式超时配置：
  - `HTTP_CONNECT_TIMEOUT_S`
  - `HTTP_READ_TIMEOUT_S`
  - `HTTP_WRITE_TIMEOUT_S`
  - `HTTP_POOL_TIMEOUT_S`
- 默认值面向长耗时内网模型场景调整为：
  - `connect=10s`
  - `read=180s`
  - `write=180s`
  - `pool=30s`

### 2. Query Rewrite 单独走快速降级策略

- `chat/query rewrite` 保持独立超时，不跟随 embedding/reranker 的长等待策略；
- 新增独立配置：
  - `QUERY_REWRITE_CONNECT_TIMEOUT_S`
  - `QUERY_REWRITE_READ_TIMEOUT_S`
  - `QUERY_REWRITE_WRITE_TIMEOUT_S`
  - `QUERY_REWRITE_POOL_TIMEOUT_S`
  - `QUERY_REWRITE_CONCURRENCY`
- 默认目标是“尽快给出改写结果，失败则快速回退到原始 query”，避免拖慢在线检索。

### 3. 三类模型调用统一并发闸门

- `EmbeddingService` 的 semaphore 下沉到 `_call_api()`，确保 batch 路径与 one-by-one fallback 路径都受统一并发控制；
- `RerankerService` 新增独立并发上限 `RERANKER_CONCURRENCY`；
- `ChatCompletionService` 新增 `QUERY_REWRITE_CONCURRENCY`，避免高并发检索时 rewrite 请求过量堆积。

默认并发建议：

- `EMBEDDING_CONCURRENCY=5`
- `RERANKER_CONCURRENCY=5`
- `QUERY_REWRITE_CONCURRENCY=10`

## 重试与失败恢复

### API 层重试增强

- 统一识别并重试以下可恢复故障：
  - 超时
  - 连接错误
  - `429`
  - `502`
  - `503`
  - `504`
- 重试策略升级为“指数退避 + 抖动”，降低雪崩重试风险；
- `embedding` / `reranker` 默认最多重试 3 次；
- `chat/query rewrite` 默认最多重试 2 次。

### 失败分级更清晰

- `EmbeddingError`、`RerankerError`、`QueryRewriteError` 现在会携带：
  - `status_code`
  - `retryable`
  - `upstream`
- 结构错误、维度错误、非 JSON 返回等确定性故障，明确标记为不可重试；
- 临时上游故障明确标记为可重试，便于服务层与 worker 层统一处理。

### PipelineWorker 增加文档级补偿重试

- 对文档入库链路中的可恢复上游失败，`PipelineWorker` 会自动重试；
- 新增配置：
  - `PIPELINE_RETRY_ATTEMPTS`
  - `PIPELINE_RETRY_BACKOFF_S`
- 默认行为：
  - 最多补偿重试 2 次
  - 每次重试前退避 5 秒
- 重试计数为当前 worker 进程内存态：
  - 成功后清理
  - 最终失败后清理
  - 进程重启后不保留历史次数

## 检索链路行为变化

### Query Rewrite 失败不再影响主检索

- `QueryRewriteService` 对 chat 失败继续执行降级回退；
- 现在会区分更精确的 fallback reason：
  - `rewrite_timeout`
  - `rewrite_5xx`
  - `rewrite_error`
- 在线检索仍优先保证“可返回结果”，而不是因改写失败整体报错。

### 入库链路可恢复异常会向上冒泡给 Worker

- `PipelineService`
- `PreChunkPipelineService`

这两个链路现在会在更新文档状态为 `FAILED` 后，将“可恢复上游异常”继续抛出给 `PipelineWorker`，由 worker 统一决定是否重试。

## 配置变更

本次版本新增以下配置项：

- `HTTP_CONNECT_TIMEOUT_S`
- `HTTP_READ_TIMEOUT_S`
- `HTTP_WRITE_TIMEOUT_S`
- `HTTP_POOL_TIMEOUT_S`
- `RERANKER_CONCURRENCY`
- `QUERY_REWRITE_CONNECT_TIMEOUT_S`
- `QUERY_REWRITE_READ_TIMEOUT_S`
- `QUERY_REWRITE_WRITE_TIMEOUT_S`
- `QUERY_REWRITE_POOL_TIMEOUT_S`
- `QUERY_REWRITE_CONCURRENCY`
- `PIPELINE_RETRY_ATTEMPTS`
- `PIPELINE_RETRY_BACKOFF_S`

参考样例见：`backend/.env.example`

## 代码层补充修复

- 修复 `app/services/chunking_service.py` 中的预存 Ruff `E741` 告警；
- 将歧义变量名 `l` 改为更明确的 `line`，避免与数字 `1` 或大写 `I` 混淆。

## 测试与验证

本次版本新增并通过以下验证：

- timeout 构造测试
- retryable 状态码判定测试
- embedding 503 自动恢复测试
- reranker 503 自动恢复测试
- query rewrite 独立 timeout 测试
- query rewrite fallback reason 测试
- PipelineWorker 文档级自动重试测试
- retryable 异常向 worker 透传测试
- 检索相关回归测试

已执行验证命令：

```bash
uv run pytest tests/unit/test_httpx_client.py tests/unit/test_retry_utils.py tests/unit/test_embedding_service.py tests/unit/test_reranker_service.py tests/unit/test_chat_completion_service.py tests/unit/test_query_rewrite_service.py tests/unit/test_pipeline_worker.py tests/unit/test_pipeline_service.py tests/unit/test_prechunk_pipeline_service.py tests/unit/test_retrieval_service.py tests/unit/test_retrieve_route.py tests/unit/test_schemas.py

uv run ruff check app/config.py app/core/httpx_client.py app/exceptions.py app/services/chat_completion_service.py app/services/chunking_service.py app/services/embedding_service.py app/services/pipeline_service.py app/services/pipeline_worker.py app/services/prechunk_pipeline_service.py app/services/query_rewrite_service.py app/services/reranker_service.py app/utils/retry.py tests/unit/test_httpx_client.py tests/unit/test_retry_utils.py tests/unit/test_embedding_service.py tests/unit/test_reranker_service.py tests/unit/test_chat_completion_service.py tests/unit/test_query_rewrite_service.py tests/unit/test_pipeline_worker.py tests/unit/test_pipeline_service.py tests/unit/test_prechunk_pipeline_service.py
```

## 升级提示

- 若你的内网模型服务吞吐有限，建议先使用默认并发值上线观察，再按容量逐步调整；
- 若 query rewrite 对响应时延非常敏感，优先调低 `QUERY_REWRITE_READ_TIMEOUT_S`，而不是提高共享 HTTP 超时；
- 若需要跨进程持久化文档重试次数，可在后续版本为 `documents` 增加重试字段，本次版本尚未引入数据库结构变更。
