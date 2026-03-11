# v2 技术报告（三）：数据治理、入库链路与前后端协同

## 1. 报告摘要

v2 在“数据治理”上的进步，比纯检索增强更像平台化升级。

当前版本已经把知识资产拆成了三层对象：

- **目录（Folder）**
- **知识库（Knowledge Base）**
- **文档（Document）**

并围绕它们提供了：

- 树形组织
- 文档上传与预切分上传
- 显式向量化触发
- 文档级参数更新
- 重试与下载
- 文档状态轮询

这意味着 v2 的数据治理面已经可以承载“运营式管理”，而不仅仅是“开发时导入文档”。

---

## 2. 知识治理模型

### 2.1 目录树模型

当前目录模型由 `kb_folders` 表承载，具备以下约束：

- 目录最大深度固定为 `2`
- 根目录深度是 `1`
- 叶子目录深度是 `2`
- 知识库只能属于叶子目录

因此，v2 当前并不是任意层级树，而是 **固定两层目录树**。

这对治理的意义是：

- 足够表达“项目 → 子项目/业务域 → 知识库”；
- 同时避免无限层级带来的前端和接口复杂度。

### 2.2 默认目录回填

`KBService.list_all()` 与 `KBService.list_tree()` 在读取知识库时，会自动把老数据分配到默认目录层级。

这是一种 **兼容 v1 数据的读时迁移策略**：

- 老知识库如果没有 `folder_id`
- 读取列表或树结构时，会被自动挂到默认叶子目录

这个设计降低了升级成本，但也意味着：

- 部分“读接口”实际上带有写入副作用。

### 2.3 知识库治理接口

当前 v2 提供的治理接口包括：

- `POST /api/v1/kb/create`
- `GET /api/v1/kb/list`
- `GET /api/v1/kb/tree`
- `POST /api/v1/kb/folders`
- `PATCH /api/v1/kb/folders/{folder_id}`
- `DELETE /api/v1/kb/folders/{folder_id}`
- `PATCH /api/v1/kb/{kb_id}`
- `DELETE /api/v1/kb/{kb_id}`

这套接口已经足够支撑一个后台数据治理页。

---

## 3. 文档入库模型

### 3.1 文档状态机

当前文档状态包含：

- `uploaded`
- `pending`
- `parsing`
- `chunking`
- `embedding`
- `upserting`
- `completed`
- `failed`

前端为了改善交互，还额外引入了一个仅 UI 侧使用的伪状态：

- `initializing`

这个状态不会由后端返回，而是前端在“刚触发向量化/重试后、下一次轮询前”临时展示。

### 3.2 文档对象的治理字段

v2 文档对象除了基础身份字段，还新增/强化了以下治理信息：

- `chunk_count`
- `chunk_size`
- `chunk_overlap`
- `effective_chunk_size`
- `effective_chunk_overlap`
- `is_pre_chunked`
- `error_message`
- `progress_message`
- `upload_timestamp`
- `updated_at`
- `needs_vector_cleanup`

这些字段让文档不再只是“文件记录”，而是可运维、可重试、可诊断的处理对象。

---

## 4. v2 入库链路的两种模式

### 4.1 标准上传模式

接口：

- `POST /api/v1/document/upload`

行为：

1. 校验知识库存在；
2. 校验文件名安全；
3. 根据文件内容生成 `doc_id`；
4. 将原始文件写入 `upload_dir/<knowledge_base_id>/<file_name>`；
5. 创建或重置文档记录，状态为 `uploaded`。

需要注意的是：

- 上传本身 **不自动启动向量化**；
- 需要再调用 `POST /api/v1/document/vectorize`。

### 4.2 预切分上传模式

接口：

- `POST /api/v1/document/upload-chunks`

行为：

1. 仅接受 `.json` 文件；
2. 顶层必须是数组；
3. 每个元素至少要有非空 `text`；
4. `header_level` 必须在 `0~6`；
5. 保存原始 JSON 文件；
6. 创建 `is_pre_chunked=true` 的文档记录。

对应后台流程由 `PreChunkPipelineService` 完成，跳过了解析和切分阶段，直接进入 embedding / upsert。

这使 v2 可以接入：

- 外部已切分数据；
- 第三方知识处理流水线；
- 特定格式的离线 chunk 产物。

---

## 5. 向量化触发与重试机制

### 5.1 显式向量化

接口：

- `POST /api/v1/document/vectorize`

特点：

- 允许批量传入多个 `doc_ids`
- 允许覆盖 `chunk_size/chunk_overlap`
- 可对 `uploaded`、`failed`、`completed` 文档再次发起处理

如果目标文档已经是 `completed`：

- 会打上 `needs_vector_cleanup=true`
- 后续 Worker 真正处理时，先尝试删旧向量，再重新入库

### 5.2 文档重试

接口：

- `POST /api/v1/document/{kb_id}/{doc_id}/retry`

特点：

- 与 `vectorize` 类似，也允许对 `failed/uploaded/completed` 文档再次处理
- 如果文档原本已完成，同样会设置向量清理标记
- 本质上是把单文档状态重置为 `pending`

### 5.3 文档设置更新

接口：

- `PATCH /api/v1/document/{kb_id}/{doc_id}/settings`

作用：

- 调整单文档的 `chunk_size/chunk_overlap`
- 参数会在下一次向量化时生效

当前参数优先级为：

> 请求参数 > 文档级配置 > 全局配置

---

## 6. Worker 与失败恢复

### 6.1 Worker 的职责

`PipelineWorker` 当前负责：

- 周期轮询 `PENDING` 文档；
- 受 `pipeline_max_concurrency` 控制并发消费；
- 针对标准上传文档使用 `PipelineService`；
- 针对预切分文档使用 `PreChunkPipelineService`。

### 6.2 启动恢复

应用启动时会执行恢复逻辑：

- 把卡在 `PARSING/CHUNKING/EMBEDDING/UPSERTING` 的文档改回 `PENDING`
- 同时打上 `needs_vector_cleanup=1`

这使服务异常退出后，文档不会永久卡死在中间状态。

### 6.3 可恢复错误重试

`v2.1.0` 已引入文档级补偿重试：

- 只对可恢复上游错误生效
- 最大次数由 `PIPELINE_RETRY_ATTEMPTS` 控制
- 重试退避由 `PIPELINE_RETRY_BACKOFF_S` 控制
- 计数保存在 Worker 进程内存中

这是一种“单进程内可恢复”的机制，已经足够覆盖多数内网模型波动场景，但还不是分布式任务系统。

---

## 7. v2 前后端协同方式

### 7.1 数据治理页

`frontend/src/app/data-governance/page.tsx` 体现了 v2 的治理模式：

- 左侧使用目录树选择 folder / knowledge base；
- 右侧展示当前知识库文档列表；
- 只要存在未完成文档，就按 3 秒轮询文档列表；
- 创建知识库/目录后自动刷新树并保持选中状态。

### 7.2 文档操作体验

前端针对文档治理已经打通以下操作：

- 上传标准文档
- 上传预切分 JSON
- 批量向量化
- 文档重试
- 原文下载
- chunk 预览

这说明 v2 已不仅仅面向内部开发者，而是已经具备给运营/实施人员使用的基础界面。

---

## 8. v2 相比 v1 的数据治理增量

| 主题 | v1 | v2 |
|---|---|---|
| 知识库组织 | 平铺列表为主 | 两层目录树 |
| 文档输入 | 原始文件上传 | 原始文件 + 预切分 JSON |
| 文档参数 | 以全局配置为主 | 支持文档级 chunk 参数 |
| 文档运维 | 基础状态轮询 | 下载、重试、chunk 预览、cleanup 标记 |
| 恢复能力 | 基础异步处理 | 启动恢复 + Worker 重试 |

v2 的治理提升主要体现在：

- 对象更清晰；
- 状态更清晰；
- 运维动作更清晰。

---

## 9. 当前数据治理面的优点与边界

### 优点

- 树结构已足够支撑大多数中小规模知识治理场景；
- 文档对象状态和诊断信息比较完整；
- 入库链已支持原始文档和预切分两种来源；
- 前后端协同路径清晰。

### 边界

- 目录层级固定为 2，不适合更复杂组织结构；
- Worker 仍是单进程内存态重试，不适合横向扩展；
- 文件存储仍以原始文件名为路径键，存在一致性风险；
- 治理接口还未引入认证授权与操作审计。

---

## 10. 面向 v3 的建议

建议 v3 围绕以下方向增强数据治理：

1. **存储一致性**：文件物理存储名改成 `doc_id` 或 UUID，避免同名覆盖；
2. **任务一致性**：把重试次数、任务 lease、执行历史从内存移到数据库；
3. **治理规模化**：文档列表、chunk 列表、统计接口支持分页与筛选；
4. **权限治理**：目录、知识库、文档的读写权限与审计日志独立建模。

这四项能把 v2 的治理后台，进一步推进到真正可多团队共用的平台级数据治理面。
