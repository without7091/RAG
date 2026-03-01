# 设计文档：基于数据库的 Pipeline Worker 向量化队列

## 1. 问题背景

### 当前问题

当多个文档同时提交向量化时，当前的 `asyncio.create_task()` fire-and-forget 模式会同时启动所有 pipeline，没有并发控制。这会导致 SiliconFlow Embedding API 过载，部分文档静默失败或永远无法完成处理。

### 根因分析

`POST /document/vectorize`（document.py:167-283）遍历所有 `doc_ids`，对每个文档调用 `task_manager.submit()`，立即生成一个 `asyncio.create_task()`。当提交 10+ 文档时，意味着 10+ 个并发 embedding API 调用链同时竞争同一个外部 API。

### 解决方案

用 **DB-backed queue + background worker** 替换 fire-and-forget 模式：

- vectorize 端点仅设置 `status=PENDING` 后立即返回
- 后台 `PipelineWorker` 轮询 documents 表，拾取 PENDING 状态的文档
- 使用 semaphore 控制并发（默认最多 2 个同时处理）
- 复用已有的 `Document.status` 列作为队列状态，无需新建表

## 2. 架构设计

### 处理流程

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  API 端点    │     │  Documents   │     │ PipelineWorker  │
│  /vectorize  │────>│  Table       │<────│  (后台轮询)      │
│  /retry      │     │  status=     │     │  semaphore=2    │
│              │     │  PENDING     │     │                 │
└─────────────┘     └──────────────┘     └────────┬────────┘
                                                   │
                                          ┌────────▼────────┐
                                          │ PipelineService  │
                                          │ .run_pipeline()  │
                                          └────────┬────────┘
                                                   │
                                    ┌──────────────┼──────────────┐
                                    ▼              ▼              ▼
                              Parse → MD    Chunk → Embed    Upsert → Qdrant
```

### 状态流转

```
UPLOADED ──(vectorize)──> PENDING ──(worker pick up)──> PARSING → CHUNKING → EMBEDDING → UPSERTING → COMPLETED
                                                                                                       │
                                                                                                  (失败时)
                                                                                                       ▼
                                                                                                    FAILED
                                                                                                       │
                                                                                              (retry)  │
                                                                                                       ▼
                                                                                                    PENDING
```

### 崩溃恢复

应用启动时，将所有处于中间状态（`parsing`/`chunking`/`embedding`/`upserting`）的文档重置为 `PENDING`，由 worker 重新处理。

## 3. 详细变更

### 3.1 `backend/app/config.py` — 新增 worker 配置

在 `Settings` 类中添加两个字段：

```python
pipeline_max_concurrency: int = 2       # 最大同时处理文档数
pipeline_poll_interval: float = 2.0     # 轮询间隔（秒）
```

### 3.2 `backend/app/models/document.py` — 新增 `needs_vector_cleanup` 列

添加 `Boolean` 类型的 `needs_vector_cleanup` 列（默认 `False`）。此标志告诉 worker 在重新向量化之前删除旧的 Qdrant 向量。

当前此清理逻辑存在于 endpoint 的 `_run_pipeline` 闭包中，需要持久化到 DB 以便 worker 能读取。

```python
needs_vector_cleanup = Column(Boolean, default=False, server_default="0")
```

### 3.3 `backend/app/db/session.py` — 新增列迁移

在 `init_db()` 的迁移循环中添加：

```python
"needs_vector_cleanup BOOLEAN DEFAULT 0"
```

### 3.4 `backend/app/services/pipeline_service.py` — `task_manager` 改为可选

- 将 `task_manager` 参数从必需改为 `TaskManager | None = None`
- 添加 `_update_task()` 辅助方法，当 `task_manager is None` 时为空操作
- 将所有 9 处直接调用 `self.task_manager.update_task(...)` 替换为 `self._update_task(...)`
- Worker 调用 `run_pipeline` 时不传 TaskManager — 文档状态更新通过独立的 `DocumentService.update_status()` 继续工作

### 3.5 `backend/app/services/pipeline_worker.py` — 新建后台 Worker

核心新文件。`PipelineWorker` 类包含：

| 方法 | 职责 |
|------|------|
| `start()` | 启动轮询循环 |
| `stop(timeout=30)` | 优雅关闭，等待活跃 pipeline 完成 |
| `_poll_loop()` | 每 `poll_interval` 秒运行一次，查询 PENDING 文档 |
| `_poll_and_dispatch()` | 获取 PENDING 文档（受 semaphore 可用槽位限制），跳过已在处理中的文档（`_active_doc_keys` 集合），派发 pipeline 任务 |
| `_run_pipeline_wrapper()` | 获取 semaphore → 调用 `PipelineService.run_pipeline()` → 释放 |
| `_cleanup_vectors()` | 处理 `needs_vector_cleanup` 标志，在 pipeline 执行前清理旧向量 |

**关键实现细节：**

```python
class PipelineWorker:
    def __init__(self, max_concurrency: int = 2, poll_interval: float = 2.0):
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._poll_interval = poll_interval
        self._active_doc_keys: set[tuple[str, str]] = set()  # (kb_id, doc_id)
        self._running = False
        self._poll_task: asyncio.Task | None = None
        self._active_tasks: set[asyncio.Task] = set()
```

**优雅关闭流程：**

1. 设置 `_running = False`
2. 等待所有 `_active_tasks` 完成（最多 `timeout` 秒）
3. 超时后取消剩余任务

### 3.6 `backend/app/schemas/document.py` — 简化响应类型

| 变更 | 说明 |
|------|------|
| `VectorizeTaskInfo` → `VectorizeDocInfo` | 重命名，移除 `task_id` 字段 |
| `VectorizeResponse.tasks` → `VectorizeResponse.docs` | 字段重命名 |
| `DocRetryResponse` | 移除 `task_id` |
| `DocUploadResponse` | 移除 `task_id` |

### 3.7 `backend/app/api/v1/document.py` — 简化 vectorize & retry 端点

**`vectorize_documents`（原 line 167-283）：**

移除所有 `TaskManager` 使用、`_run_pipeline` 闭包和 `asyncio.create_task`。新逻辑：

```
验证文档 → 若重新向量化则设 needs_vector_cleanup=True → 设 status=PENDING → 提交 → 返回 VectorizeResponse(docs=[...])
```

**`retry_document`（原 line 286-354）：**

同样简化 — 设 `needs_vector_cleanup` 标志（如需要）→ 设 `status=PENDING` → 提交 → 返回。

**移除的导入：** `PipelineService`、`TaskManager`、`get_task_manager`、`ChunkingService`

### 3.8 `backend/app/dependencies.py` — 替换 TaskManager 为 PipelineWorker

- 移除 `_task_manager` 单例和 `get_task_manager()` 函数
- 添加 `_pipeline_worker` 单例和 `get_pipeline_worker()` 函数

### 3.9 `backend/app/api/v1/tasks.py` — 删除 tasks 端点

删除文件内容。tasks API 仅用于轮询 `task_id` 状态，已被文档状态轮询替代。

### 3.10 `backend/app/api/router.py` — 移除 tasks 路由

从 import 和 `api_router.include_router()` 中移除 `tasks`。

### 3.11 `backend/app/main.py` — 启动恢复 + Worker 生命周期

在 `lifespan()` 中：

**启动恢复（init_db 之后）：**
```sql
UPDATE documents
SET status = 'pending', needs_vector_cleanup = 1
WHERE status IN ('parsing', 'chunking', 'embedding', 'upserting')
```

**启动 Worker：**
```python
worker = get_pipeline_worker()
worker.start()
```

**关闭（其他清理之前）：**
```python
await worker.stop(timeout=30)
```

### 3.12 `frontend/src/lib/api.ts` — 更新 TypeScript 类型

| 变更 | 说明 |
|------|------|
| `VectorizeTaskInfo` → `VectorizeDocInfo` | 移除 `task_id` |
| `VectorizeResponse.tasks` → `VectorizeResponse.docs` | 字段重命名 |
| `DocRetryResponse` | 移除 `task_id` |
| `uploadDocument` 返回类型 | 移除 `task_id` |

### 3.13 前端组件 — 无需变更

`doc-table.tsx` 和 `page.tsx` 不使用 vectorize/retry 响应中的 `task_id`。它们依赖文档列表轮询，保持不变。3 秒自动刷新轮询和乐观状态更新继续正常工作。

## 4. 实现顺序

| 阶段 | 文件 | 类型 |
|------|------|------|
| 1 | `config.py` | 追加配置 |
| 2 | `models/document.py` | 追加字段 |
| 3 | `db/session.py` | 追加迁移 |
| 4 | `services/pipeline_service.py` | 向后兼容修改 |
| 5 | `services/pipeline_worker.py` | 新文件（暂无调用方） |
| 6-10 | `schemas/document.py` + `api/v1/document.py` + `dependencies.py` + `api/v1/tasks.py` + `api/router.py` | 原子性变更组 |
| 11 | `main.py` | 连接所有组件 |
| 12 | `frontend/src/lib/api.ts` | 匹配后端 schema 变更 |
| 13 | 更新现有测试 | 测试适配 |

## 5. 验证方案

1. 启动后端，确认出现 `PipelineWorker started` 日志
2. 上传 5+ 文档到知识库
3. 点击全部向量化 — 确认 API 立即返回 PENDING 状态
4. 查看后端日志：worker 应每次处理 2 个文档（max_concurrency=2）
5. 前端轮询应显示状态进度：pending → parsing → chunking → embedding → upserting → completed
6. 处理过程中 kill 并重启后端 — 确认卡住的文档重置为 PENDING 并被重新处理
7. 运行 `pytest backend/tests/` 验证更新后的测试通过

## 6. 风险与注意事项

- **轮询延迟**：文档提交后最多等待 `poll_interval`（2 秒）才会被拾取，相比之前的即时启动有微小延迟，但换来了稳定性
- **SQLite 并发**：轮询和状态更新都通过 async session 进行，SQLite 的写锁可能在高并发下成为瓶颈，但当前规模（2 并发 worker）完全可以承受
- **向量清理失败**：如果 `_cleanup_vectors()` 失败（Qdrant 不可用），应将文档标记为 FAILED 而非继续处理
- **幂等性**：启动恢复的 `needs_vector_cleanup=1` 设置确保重新处理时清理旧数据，避免重复向量
