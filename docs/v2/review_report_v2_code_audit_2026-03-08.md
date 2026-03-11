# v2.0.0 代码审查修复报告（2026-03-08）

## 1. 审查范围

对 v2.0.0 多租户 RAG 检索中台进行全面代码审查，覆盖后端全部核心链路（Pipeline Worker、Pipeline Service、Retrieval Service、SSE 流、Sparse Embedding、Context Synthesis）以及前端 SSE 解析与构建配置。

审查目标：识别运行时 Bug、事件循环阻塞风险、设计层面缺陷，并逐项修复验证。

## 2. 问题总览

| 级别 | ID | 文件 | 问题 |
|------|----|------|------|
| **严重** | BUG-1 | `pipeline_worker.py` | cleanup 标志无条件清除，Qdrant 故障时导致残留向量 |
| **中等** | BUG-2 | `pipeline_worker.py` | retry 睡眠期间占用 Semaphore 槽位，阻塞 pipeline |
| **中等** | BUG-3 | `sparse_embedding_service.py` | `_parse_sparse_results` 裸 KeyError 不被重试识别 |
| **中等** | BUG-4 | `sparse_embedding_service.py` | local 模式下 async 函数同步阻塞 FastEmbed 推理 |
| **低** | BUG-5 | `pipeline_service.py` | chunking + BM25 同步调用阻塞事件循环 |
| 设计 | DESIGN-1 | `retrieve.py` + `retrieval_service.py` | SSE 进度事件为假进度，不反映真实执行步骤 |
| 设计 | DESIGN-2 | `context_synthesis_service.py` | 异常静默吞掉，无日志 |
| 设计 | DESIGN-3 | `frontend/src/lib/api.ts` | SSE JSON 解析无 try-catch，流崩溃无提示 |
| 设计 | DESIGN-4 | `frontend/next.config.ts` | 后端 URL 硬编码 localhost |

## 3. 修复详情

### BUG-1（严重）：向量清理失败时仍清除 cleanup 标志

**文件**：`backend/app/services/pipeline_worker.py`

**问题**：`needs_vector_cleanup = False` 写在 `except` 之后无条件执行。当 Qdrant 暂时不可用时，`delete_by_doc_id` 抛出异常被 `except` 吞掉，但 flag 仍被清除并 commit。下次处理同一文档时不会再尝试清理，导致 Qdrant 中永久残留旧向量。

**修复**：将 `needs_vector_cleanup = False` 和 `session.commit()` 移入 `try` 块内，仅在 `delete_by_doc_id` 确认成功后才清除标志。

```python
# 修复后
if doc.needs_vector_cleanup:
    try:
        vs = await get_vector_store_service()
        await vs.delete_by_doc_id(doc.knowledge_base_id, doc.doc_id)
        # 仅成功后清除
        doc.needs_vector_cleanup = False
        await session.commit()
    except Exception:
        logger.warning("Vector cleanup failed for %s/%s, will retry on next run", ...)
```

---

### BUG-2（中等）：retry 睡眠期间占用 Semaphore 槽位

**文件**：`backend/app/services/pipeline_worker.py`

**问题**：`asyncio.sleep(5)` 在 `async with self._semaphore` 块内执行。当 `max_concurrency=2`、两个 pipeline 同时触发重试时，整个 pipeline 系统暂停 5 秒。

**修复**：重构 `_run_pipeline_wrapper`，在 semaphore 块内只设置 `needs_backoff` 标志，`asyncio.sleep` 移到 `async with self._semaphore` 退出之后执行。同时从 `_retry_or_requeue` 中移除 sleep。

```python
# 修复后
async with self._semaphore:
    ...  # pipeline 执行 + 重试判断
    if retry_needed:
        needs_backoff = True

# semaphore 已释放，其他文档可以继续处理
if needs_backoff and self._retry_backoff_s > 0:
    await asyncio.sleep(self._retry_backoff_s)
```

---

### BUG-3（中等）：`_parse_sparse_results` 缺少防御性解析

**文件**：`backend/app/services/sparse_embedding_service.py`

**问题**：若 SiliconFlow API 返回 200 OK 但 JSON 结构异常（缺少 `data` 或 `embedding` 字段），会抛出裸 `KeyError`。`is_retryable_api_exception` 对 `KeyError` 返回 `False`，导致重试逻辑无法识别。

**对比**：`EmbeddingService._validate_embeddings_response` 有完整的字段校验，`SparseEmbeddingService` 缺少类似保护。

**修复**：添加 `"data"` 和 `"embedding"` 字段存在性检查，缺失时抛出 `EmbeddingError`（可被重试框架识别）。

---

### BUG-4（中等）：local 模式下 `embed_texts_async` 同步阻塞事件循环

**文件**：`backend/app/services/sparse_embedding_service.py`

**问题**：`_local_embed_texts` 调用 FastEmbed 模型的同步 CPU 密集推理。虽然包装在 `async def` 中，但实际直接同步调用，阻塞事件循环。`sparse_embedding_mode` 默认值为 `"local"`，因此是默认生效的问题。

**修复**：使用 `loop.run_in_executor(None, self._local_embed_texts, texts)` 将 CPU 密集操作卸载到线程池。

---

### BUG-5（低）：Chunking 和 BM25 未异步化

**文件**：`backend/app/services/pipeline_service.py`

**问题**：`chunk_markdown()` 和 `batch_to_sparse_vectors()` 均为同步 CPU 密集调用（jieba 分词、Markdown 解析），在异步 pipeline 中直接执行会阻塞事件循环。

**修复**：两处均使用 `loop.run_in_executor(None, ...)` 包装。文件顶部新增 `import asyncio`。

---

### DESIGN-1：SSE 进度从假进度改为真实实时进度

**文件**：`backend/app/api/v1/retrieve.py` + `backend/app/services/retrieval_service.py`

**问题**：原实现在 retrieval 开始前一次性发送 `query_rewrite → embedding_query → hybrid_search` 三个状态事件，然后所有实际工作在一个 `await` 里完成。前端显示的"实时进度"完全是假的。

**修复**：
1. `RetrievalService.retrieve()` 新增 `status_callback` 参数，在每个真实步骤开始时回调
2. 回调传播到 `_collect_candidates` 和 `_search_single_query`
3. `_stream_retrieval` 改为 `asyncio.Queue` + `asyncio.ensure_future` 模式：retrieve 作为后台 Task 运行，通过 Queue 发送状态事件，generator 实时消费并 yield
4. 添加 `finally` 块确保客户端断开时 cancel 后台 Task，防止孤儿任务泄漏

```
真实事件流：query_rewrite → embedding_query → hybrid_search → reranking → context_synthesis → building_response → result
```

---

### DESIGN-2：上下文合成异常添加日志

**文件**：`backend/app/services/context_synthesis_service.py`

**问题**：`except Exception: continue` 完全静默，向量库查询失败时无法通过日志排查。

**修复**：添加 `logger.warning(..., exc_info=True)` 记录异常详情。新增 `import logging` 和 `logger` 实例。

---

### DESIGN-3：前端 SSE JSON 解析添加 try-catch

**文件**：`frontend/src/lib/api.ts`

**问题**：`JSON.parse(line.slice(5).trim())` 无保护。后端 SSE 流出现格式错误的 JSON 行时，异常导致整个 async IIFE 崩溃，流完全中断，用户无任何提示。

**修复**：包装在 `try/catch` 中，格式错误的行打印 `console.warn` 并跳过，不中断流。

---

### DESIGN-4：后端 URL 从硬编码改为环境变量

**文件**：`frontend/next.config.ts`

**问题**：`destination: "http://localhost:8000/api/:path*"` 硬编码，部署到非 localhost 环境需要修改源代码。

**修复**：读取 `process.env.BACKEND_URL`，缺省值保持 `http://localhost:8000`。

---

### 自审发现：SSE Task 泄漏

**文件**：`backend/app/api/v1/retrieve.py`

在实现 DESIGN-1 的 queue-based SSE 时发现：`asyncio.ensure_future` 创建的 retrieve_task 在客户端断开连接后会继续运行，无人消费其结果。添加 `finally` 块在 generator 退出时 cancel 后台 Task。

## 4. 测试更新

### 修改的测试文件

- `backend/tests/unit/test_retrieve_route.py`：`test_stream_retrieval_emits_embedding_query_step` 更新 mock 以适配新的 `status_callback` 机制（mock 中主动调用 callback 发送状态事件）。

### 测试结果

```
tests/unit/ (排除预存在故障)：200 passed
```

**预存在故障（未引入）**：
- `test_does_not_retry_non_retryable_error`：in-memory SQLite `QueuePool` 连接隔离问题，在原始代码上同样失败
- `test_manual_retrieve_test.py`：引用了已删除的 `manual_retrieve_test.py` 文件，收集阶段报错

## 5. 已验证的"假问题"

| 嫌疑点 | 验证结论 |
|--------|---------|
| rewrite + no-reranker 路径分数不可比 | ✅ Qdrant 使用 RRF 融合（`1/(k+rank)`），分数纯基于排名位置，与 query 向量无关，跨 query 可比 |
| `TimeoutError` 是否被重试 | ✅ `retry.py:22` 将 `TimeoutError` 加入 `_NETWORK_RETRYABLE_ERRORS` |
| `sparse_vector.get("indices")` 空列表判断 | ✅ 空列表为 falsy，会跳过，不会构造无效向量 |
| `coverage_bonus = 0.001` 人为加分 | ✅ 仅作排序辅助，不影响 reranker 结果 |
| `_merge_overlapping_ranges` 负 index 处理 | ✅ chunk_index=0 时下界为 -1 不影响结果 |

## 6. 变更文件清单

| 文件 | 变更类型 |
|------|---------|
| `backend/app/services/pipeline_worker.py` | BUG-1 + BUG-2 修复 |
| `backend/app/services/sparse_embedding_service.py` | BUG-3 + BUG-4 修复 |
| `backend/app/services/pipeline_service.py` | BUG-5 修复 |
| `backend/app/services/retrieval_service.py` | DESIGN-1 status_callback |
| `backend/app/api/v1/retrieve.py` | DESIGN-1 queue-based SSE + Task 泄漏修复 |
| `backend/app/services/context_synthesis_service.py` | DESIGN-2 日志 |
| `frontend/src/lib/api.ts` | DESIGN-3 try-catch |
| `frontend/next.config.ts` | DESIGN-4 环境变量 |
| `backend/tests/unit/test_retrieve_route.py` | 测试适配 |

## 7. Git 提交记录

```
35bf288 fix: add finally-cancel for SSE task leak and update SSE test for callback
a9927de fix: address all v2.0.0 code review findings (BUG-1 through DESIGN-4)
```
