# 项目审阅报告（2026-03-06）

## 1. 审阅范围
- 后端核心链路：上传、向量化、检索、向量存储、配置与测试。
- 重点目标：识别潜在 Bug、可能导致系统崩溃或不可用的问题，并给出可执行修复建议。

## 2. 本轮已落地修改
- 已将 **Embedding 默认维度** 从 `1024` 调整为 `2560`：
  - `backend/app/config.py`
  - `backend/.env.example`
  - `backend/tests/conftest.py`
  - `backend/tests/unit/test_config.py`
  - `backend/tests/unit/test_embedding_service.py`
  - `backend/tests/unit/test_pipeline_service.py`
  - `backend/tests/unit/test_retrieval_service.py`
  - `backend/tests/integration/test_full_pipeline.py`
  - `backend/docs/retrieval_optimization_proposal.md`
- 已将 `backend/.env.example` 中示例密钥改为占位值（避免明文泄露）。
- 验证结果：
  - `uv run pytest tests/unit/test_config.py tests/unit/test_embedding_service.py tests/unit/test_vector_store_service.py tests/unit/test_retrieval_service.py -q` -> 30 passed
  - `uv run pytest tests/integration/test_full_pipeline.py::TestRetrievalServiceEndToEnd::test_retrieve_returns_ranked_results -q` -> 1 passed

## 3. 关键风险与修复建议（按严重度）

### [高] 上传文件名未做路径安全校验（路径穿越风险）
- 证据：
  - `backend/app/api/v1/document.py:65`
  - `backend/app/api/v1/document.py:146`
- 风险：恶意文件名可尝试写入上传目录外路径，存在越权写入/读取风险。
- 建议：
  - 仅保留 `Path(filename).name`；
  - 禁止 `..`、绝对路径、盘符前缀；
  - 存储名使用服务端生成 UUID，原名仅作 metadata。

### [高] 向量上载时 `zip()` 截断导致静默数据丢失
- 证据：
  - `backend/app/services/vector_store_service.py:91`
- 风险：`dense_vectors/sparse_vectors/payloads` 长度不一致时，后续数据被静默丢弃，检索结果异常且难定位。
- 建议：
  - 在 `upsert_points()` 前强制长度一致校验，不一致直接抛 `VectorStoreError`。

### [中高] Embedding 响应未做结构和维度校验
- 证据：
  - `backend/app/services/embedding_service.py:57`
  - `backend/app/services/embedding_service.py:58`
- 风险：上游响应变更或维度错误会在后续 Qdrant 写入阶段失败，导致文档处理批量失败。
- 建议：
  - 校验 `data` 字段结构；
  - 校验每个向量长度必须等于 `self.dimension`，否则抛 `EmbeddingError`。

### [中] 预切分管道在 async 流程内使用同步文件 I/O
- 证据：
  - `backend/app/services/prechunk_pipeline_service.py:58`
- 风险：大 JSON 文件会阻塞事件循环，降低并发吞吐并诱发超时。
- 建议：
  - 使用 `aiofiles` 或 `run_in_executor` 读取 JSON。

## 4. 后续测试建议
- 新增安全回归用例：上传 `../`、绝对路径、盘符路径文件名，期望全部拒绝。
- 新增一致性用例：构造向量列表长度不一致，确保直接失败且返回明确错误。
- 新增维度守卫用例：mock 返回错误维度向量，验证在 embedding 层即失败，不进入 upsert。

## 5. 并发与长耗时专项调研（内网场景）

### 5.1 现状与问题定位
- 当前全局 HTTP 客户端超时固定为 60s（`backend/app/core/httpx_client.py`），当内网 `embedding/reranker` 处理超过 60 秒时会触发超时异常。
- `EmbeddingService` 仅在 one-by-one 回退路径使用并发信号量；批量请求路径没有统一并发闸门。
- `RerankerService` 目前没有独立并发上限控制，在多用户并发检索时可能瞬时放大对内网模型服务的压力。
- 当前重试主要覆盖超时/连接错误和 429，未对常见临时 5xx（502/503/504）做针对性重试。

### 5.2 下个小版本优化目标（建议命名：v2.1）
- 将 embedding/reranker 的单次请求等待时间提升到 **180 秒**（可配置 120~240 秒）。
- 将 embedding 与 reranker 的服务端调用并发统一收敛到 **5**（与你的内网容量匹配）。
- 减少长任务场景下的误失败，把“可恢复错误”优先转为自动重试。

### 5.3 迭代改造清单（可执行）
1. 超时配置化
- 在 `Settings` 新增：
  - `http_connect_timeout_s`（默认 10）
  - `http_read_timeout_s`（默认 180）
  - `http_write_timeout_s`（默认 180）
  - `http_pool_timeout_s`（默认 30）
- `get_httpx_client()` 改为读取上述配置，替换硬编码 `Timeout(60.0, connect=10.0)`。

2. 并发闸门统一
- `EmbeddingService`：把信号量保护下沉到 `_call_api()`，确保所有 embedding 请求（含 batch）都受 `embedding_concurrency=5` 控制。
- `RerankerService`：新增 `reranker_concurrency`（默认 5）并加 `asyncio.Semaphore`，限制并发 rerank 调用。

3. 重试策略增强
- 在 `retry_on_api_error` 中新增“可重试 5xx”策略（建议 502/503/504）。
- 对超时和 5xx 使用指数退避 + 抖动，避免雪崩重试。

4. 失败分级与恢复
- 对 `TimeoutError/临时5xx` 标记为“可重试失败”，允许 PipelineWorker 自动重试 1-2 次再置 `FAILED`。
- 对确定性错误（参数错误、校验错误）保持立即失败，避免无效重试。

### 5.4 验收与压测建议
- 并发压测：`embedding=5`、`reranker=5`，持续 30-60 分钟，观察失败率与 P95/P99 延迟。
- 长耗时验证：模拟 120s/180s/210s 响应，确认 180s 阈值内不误报超时，超阈值可控失败并可重试。
- 回归标准：检索正确性不下降、文档向量化成功率提升、超时类故障显著下降。
