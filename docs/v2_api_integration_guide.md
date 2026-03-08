# v2 API 接口文档（集成接入手册）

## 1. 文档定位

本文面向需要调用本项目 v2 后端接口的系统集成方，重点覆盖：

- 知识库与目录管理
- 文档上传与向量化
- 检索接口（重点）
- 常见错误与接入建议

接口基准前缀：

```text
http://<host>:<port>/api/v1
```

例如本地默认环境：

```text
http://localhost:8000/api/v1
```

> 说明：当前后端未内建认证授权，若对外提供服务，建议通过网关统一完成鉴权、限流和审计。

---

## 2. 快速开始

推荐接入顺序：

1. 创建知识库
2. 上传文档或预切分 JSON
3. 触发向量化
4. 轮询文档状态直到完成
5. 调用检索接口

### 2.1 创建知识库

```bash
curl -X POST http://localhost:8000/api/v1/kb/create \
  -H "Content-Type: application/json" \
  -d '{
    "knowledge_base_name": "产品知识库",
    "description": "用于客服问答"
  }'
```

返回示例：

```json
{
  "knowledge_base_id": "kb_abc123def45678",
  "knowledge_base_name": "产品知识库",
  "folder_id": "folder_xxx",
  "folder_name": "默认分组",
  "parent_folder_id": "folder_root",
  "parent_folder_name": "未分组",
  "description": "用于客服问答",
  "created_at": "2026-03-08T12:00:00"
}
```

### 2.2 上传原始文档

```bash
curl -X POST "http://localhost:8000/api/v1/document/upload?knowledge_base_id=kb_abc123def45678" \
  -F "file=@product-manual.pdf"
```

返回示例：

```json
{
  "doc_id": "a1b2c3d4e5f6",
  "file_name": "product-manual.pdf",
  "knowledge_base_id": "kb_abc123def45678",
  "status": "uploaded",
  "chunk_size": 1024,
  "chunk_overlap": 128
}
```

支持格式：

- `.pdf`
- `.docx`
- `.pptx`
- `.xlsx`
- `.md`
- `.txt`

### 2.3 触发向量化

```bash
curl -X POST http://localhost:8000/api/v1/document/vectorize \
  -H "Content-Type: application/json" \
  -d '{
    "knowledge_base_id": "kb_abc123def45678",
    "doc_ids": ["a1b2c3d4e5f6"]
  }'
```

返回示例：

```json
{
  "docs": [
    {
      "doc_id": "a1b2c3d4e5f6",
      "status": "pending"
    }
  ]
}
```

### 2.4 轮询文档状态

```bash
curl http://localhost:8000/api/v1/document/list/kb_abc123def45678
```

等待文档状态变为 `completed` 后，再发起检索。

---

## 3. 检索接口（最重要）

接口路径：

```text
POST /api/v1/retrieve
```

当前支持两种调用模式：

- **JSON 模式**：`stream=false`
- **SSE 模式**：`stream=true`

> 建议：后端服务、批处理、网关聚合优先使用 JSON 模式；需要展示阶段进度的前端场景使用 SSE 模式。

### 3.1 请求字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---:|---:|---|
| `user_id` | string | 是 | 无 | 当前为保留字段，建议传调用方系统标识 |
| `knowledge_base_id` | string | 是 | 无 | 目标知识库 ID |
| `query` | string | 是 | 无 | 用户查询 |
| `top_k` | int | 否 | 20 | 混合召回规模，范围 `1~100` |
| `top_n` | int | 否 | 3 | 最终返回数量，范围 `1~50` |
| `min_score` | float/null | 否 | null | 手工覆盖最终得分阈值 |
| `enable_reranker` | bool | 否 | true | 是否启用 reranker |
| `enable_context_synthesis` | bool | 否 | true | 是否合成相邻上下文 |
| `enable_query_rewrite` | bool | 否 | false | 是否启用查询改写 |
| `query_rewrite_debug` | bool | 否 | false | 是否返回调试信息 |
| `stream` | bool | 否 | true | 是否启用 SSE 流式返回 |

### 3.2 JSON 模式示例

```bash
curl -X POST http://localhost:8000/api/v1/retrieve \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "crm-service",
    "knowledge_base_id": "kb_abc123def45678",
    "query": "产品的核心功能有哪些？",
    "top_k": 20,
    "top_n": 3,
    "enable_reranker": true,
    "enable_context_synthesis": true,
    "enable_query_rewrite": true,
    "query_rewrite_debug": true,
    "stream": false
  }'
```

返回示例：

```json
{
  "query": "产品的核心功能有哪些？",
  "knowledge_base_id": "kb_abc123def45678",
  "source_nodes": [
    {
      "text": "本产品支持……",
      "score": 0.92,
      "doc_id": "a1b2c3d4e5f6",
      "file_name": "product-manual.pdf",
      "knowledge_base_id": "kb_abc123def45678",
      "chunk_index": 5,
      "header_path": "产品概述 > 功能特性",
      "context_text": "产品概述……功能特性……",
      "metadata": {
        "header_level": 2,
        "content_type": "text",
        "matched_queries": ["产品的核心功能有哪些？", "产品功能"],
        "query_scores": {
          "产品的核心功能有哪些？": 0.67,
          "产品功能": 0.70
        },
        "merge_score": 0.701
      }
    }
  ],
  "total_candidates": 18,
  "top_k_used": 20,
  "top_n_used": 3,
  "min_score_used": 0.1,
  "enable_reranker_used": true,
  "enable_context_synthesis_used": true,
  "debug": {
    "query_plan": {
      "enabled": true,
      "strategy": "expand",
      "canonical_query": "产品功能",
      "generated_queries": ["产品特点", "产品核心能力"],
      "final_queries": ["产品的核心功能有哪些？", "产品功能", "产品特点"],
      "reasons": ["classifier:expand", "llm"],
      "fallback_used": false,
      "model": "Pro/zai-org/GLM-4.7"
    },
    "candidate_stats": {
      "query_count": 3,
      "raw_candidate_count": 52,
      "merged_candidate_count": 29,
      "rerank_pool_size": 40
    }
  }
}
```

### 3.3 `source_nodes` 字段说明

| 字段 | 说明 |
|---|---|
| `text` | 命中的核心 chunk 文本 |
| `score` | 最终得分；启用 reranker 时为 reranker 分数 |
| `doc_id` | 文档 ID |
| `file_name` | 原始文件名 |
| `knowledge_base_id` | 所属知识库 |
| `chunk_index` | chunk 序号 |
| `header_path` | 标题路径 |
| `context_text` | 邻近上下文扩展结果 |
| `metadata` | 其他元数据与调试字段 |

### 3.4 调试信息说明

只有当 `query_rewrite_debug=true` 时才会返回 `debug`：

- `query_plan`：记录 query rewrite 策略、最终 queries、fallback 原因
- `candidate_stats`：记录多 query fanout 后的候选统计

推荐用途：

- 联调 query rewrite 是否生效
- 分析召回池是否过大/过小
- 验证多 query 合并收益

### 3.5 SSE 模式示例

请求：

```bash
curl -N -X POST http://localhost:8000/api/v1/retrieve \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "playground",
    "knowledge_base_id": "kb_abc123def45678",
    "query": "产品的核心功能有哪些？",
    "stream": true,
    "enable_query_rewrite": true
  }'
```

事件流示例：

```text
event: status
data: {"step":"query_rewrite"}

event: status
data: {"step":"embedding_query"}

event: status
data: {"step":"hybrid_search"}

event: status
data: {"step":"reranking","candidates":18}

event: status
data: {"step":"context_synthesis"}

event: status
data: {"step":"building_response"}

event: result
data: {...最终 RetrieveResponse JSON...}
```

当前状态事件的 `step` 取值包括：

- `query_rewrite`
- `embedding_query`
- `hybrid_search`
- `reranking`
- `skipping_reranker`
- `context_synthesis`
- `skipping_context_synthesis`
- `building_response`

异常时会返回：

```text
event: error
data: {"error":"..."}
```

### 3.6 检索接入建议

- 非前端调用建议显式传 `stream=false`
- 联调阶段建议开启 `query_rewrite_debug=true`
- 对低延迟要求高的场景，先关闭 `enable_query_rewrite`
- 对结果完整性要求高的问答场景，保持 `enable_context_synthesis=true`

---

## 4. 知识库与目录接口

### 4.1 创建知识库

```text
POST /api/v1/kb/create
```

请求体：

```json
{
  "knowledge_base_name": "产品知识库",
  "folder_id": "folder_xxx",
  "description": "用于客服问答"
}
```

说明：

- `folder_id` 可不传，不传时系统会放到默认叶子目录
- 同一目录下知识库名称不能重复

### 4.2 查询知识库列表

```text
GET /api/v1/kb/list
```

返回所有知识库的平铺列表，包含 `document_count`。

### 4.3 查询知识库树

```text
GET /api/v1/kb/tree
```

适合前端树组件或需要目录化管理的系统使用。

### 4.4 目录管理

```text
POST   /api/v1/kb/folders
PATCH  /api/v1/kb/folders/{folder_id}
DELETE /api/v1/kb/folders/{folder_id}
```

说明：

- 目录最大深度为 2
- 不能删除非空目录

### 4.5 更新与删除知识库

```text
PATCH  /api/v1/kb/{kb_id}
DELETE /api/v1/kb/{kb_id}
```

删除知识库时，会尝试删除对应 Qdrant collection。

---

## 5. 文档治理接口

### 5.1 上传原始文档

```text
POST /api/v1/document/upload
```

请求方式：

- `multipart/form-data`
- 查询参数中传 `knowledge_base_id`
- 可选传 `chunk_size`、`chunk_overlap`

### 5.2 上传预切分 JSON

```text
POST /api/v1/document/upload-chunks
```

请求方式：

- `multipart/form-data`
- 只接受 `.json` 文件

JSON 顶层格式示例：

```json
[
  {
    "text": "这是第一段内容",
    "header_path": "章节1 > 小节1",
    "header_level": 2,
    "content_type": "text",
    "metadata": {
      "page": 1
    }
  }
]
```

### 5.3 获取 chunk 模板

```text
GET /api/v1/document/chunk-template
```

用于下载预切分样例脚本。

### 5.4 文档列表

```text
GET /api/v1/document/list/{kb_id}
```

每个文档会返回：

- 状态
- chunk 数量
- 生效的 chunk 参数
- 是否预切分
- 错误消息
- 进度消息

### 5.5 查看文档 chunk

```text
GET /api/v1/document/{kb_id}/{doc_id}/chunks
```

适合做预览、诊断和抽样检查。

### 5.6 批量向量化

```text
POST /api/v1/document/vectorize
```

请求体：

```json
{
  "knowledge_base_id": "kb_abc123def45678",
  "doc_ids": ["a1b2c3d4e5f6"],
  "chunk_size": 1024,
  "chunk_overlap": 128
}
```

可处理的文档状态：

- `uploaded`
- `failed`
- `completed`

### 5.7 重试单文档

```text
POST /api/v1/document/{kb_id}/{doc_id}/retry
```

同样适用于：

- `uploaded`
- `failed`
- `completed`

### 5.8 下载原文

```text
GET /api/v1/document/{kb_id}/{doc_id}/download
```

返回原始上传文件。

### 5.9 更新文档切分参数

```text
PATCH /api/v1/document/{kb_id}/{doc_id}/settings
```

请求体：

```json
{
  "chunk_size": 1024,
  "chunk_overlap": 128
}
```

说明：

- 参数不会自动触发重建向量
- 需要后续再调用 `vectorize` 或 `retry`

### 5.10 删除文档

```text
DELETE /api/v1/document/{kb_id}/{doc_id}
```

删除数据库记录后，会尝试删除对应向量。

---

## 6. 统计接口

```text
GET /api/v1/stats
```

返回：

- `total_knowledge_bases`
- `total_documents`
- `total_chunks`
- 每个知识库的文档数

适合做仪表盘、运营大盘或简单健康检查。

---

## 7. 常见错误码

| HTTP 状态码 | 常见场景 |
|---|---|
| `400` | 非法文件名、非法目录层级、chunk 参数非法、JSON 格式不合法 |
| `404` | 知识库不存在、目录不存在、文档不存在、磁盘源文件不存在 |
| `409` | 同目录知识库重名、目录重名、删除非空目录 |
| `422` | 请求参数校验失败、字段缺失 |
| `500` | 向量存储或服务内部异常 |
| `502` | Embedding / Reranker 等上游模型调用失败 |

统一错误响应格式：

```json
{
  "detail": "错误说明"
}
```

SSE 模式下则以 `error` 事件返回：

```json
{
  "error": "错误说明"
}
```

---

## 8. 接入最佳实践

### 8.1 建议的生产接入方式

- 在网关层做认证、限流和审计
- 后端服务调用检索时显式传 `stream=false`
- 前端调试界面或运营工具使用 `stream=true`

### 8.2 建议的最小调用闭环

1. 调 `kb/create`
2. 调 `document/upload`
3. 调 `document/vectorize`
4. 轮询 `document/list/{kb_id}`
5. 调 `retrieve`

### 8.3 接入注意事项

- `stream` 默认值是 `true`，不要省略
- `user_id` 当前不会自动做权限校验
- 若需要“外部切分后直接入库”，优先使用 `upload-chunks`
- 若修改了 chunk 参数，记得重新向量化

---

## 9. 补充说明

当前 FastAPI 自带：

- Swagger UI：`/docs`
- OpenAPI JSON：`/openapi.json`

但需要特别注意：

> 当前自动生成的 OpenAPI 尚未完整表达检索接口的 SSE 模式，因此请以本文档和代码实现为准，尤其是 `POST /api/v1/retrieve`。

如果后续进入 v3，建议优先把检索接口的 JSON 与 SSE 契约拆开，以便第三方系统更稳定地自动接入。
