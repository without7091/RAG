# 使用文档：API 接入指南

> 面向外部应用开发者的 RAG 检索中台接入指南

## 目录

- [1. 快速上手](#1-快速上手)
- [2. API 端点参考](#2-api-端点参考)
- [3. SSE 事件格式与前端消费](#3-sse-事件格式与前端消费)
- [4. 错误码参考表](#4-错误码参考表)
- [5. 性能建议与限流](#5-性能建议与限流)
- [6. 完整 Schema 附录](#6-完整-schema-附录)

---

## 1. 快速上手

> 5 分钟完成：创建知识库 → 上传文档 → 向量化 → 检索

### 前置条件

- RAG 服务已部署并运行（默认 `http://localhost:8000`）
- 有网络访问权限

### Step 1：创建知识库

```bash
curl -X POST http://localhost:8000/api/v1/kb/create \
  -H "Content-Type: application/json" \
  -d '{
    "knowledge_base_name": "产品文档库",
    "description": "存放产品相关技术文档"
  }'
```

响应：
```json
{
  "knowledge_base_id": "kb_abc123def45678",
  "knowledge_base_name": "产品文档库",
  "description": "存放产品相关技术文档",
  "created_at": "2026-03-01T10:00:00"
}
```

记住 `knowledge_base_id`，后续操作都需要它。

### Step 2：上传文档

```bash
KB_ID="kb_abc123def45678"

curl -X POST "http://localhost:8000/api/v1/document/upload?knowledge_base_id=${KB_ID}" \
  -F "file=@./product-manual.pdf"
```

响应：
```json
{
  "doc_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
  "file_name": "product-manual.pdf",
  "knowledge_base_id": "kb_abc123def45678",
  "status": "uploaded",
  "chunk_size": null,
  "chunk_overlap": null
}
```

支持格式：`.pdf` `.docx` `.pptx` `.xlsx` `.md` `.txt`

### Step 3：触发向量化

```bash
DOC_ID="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"

curl -X POST http://localhost:8000/api/v1/document/vectorize \
  -H "Content-Type: application/json" \
  -d "{
    \"knowledge_base_id\": \"${KB_ID}\",
    \"doc_ids\": [\"${DOC_ID}\"]
  }"
```

响应：
```json
{
  "docs": [
    {"doc_id": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6", "status": "pending"}
  ]
}
```

向量化在后台异步执行，可通过文档列表接口查看进度。

### Step 4：检查处理状态

```bash
curl http://localhost:8000/api/v1/document/list/${KB_ID}
```

等待 `status` 变为 `"completed"` 后即可检索。

### Step 5：检索

```bash
curl -X POST http://localhost:8000/api/v1/retrieve \
  -H "Content-Type: application/json" \
  -d "{
    \"user_id\": \"my-app-001\",
    \"knowledge_base_id\": \"${KB_ID}\",
    \"query\": \"产品的核心功能有哪些？\",
    \"top_k\": 20,
    \"top_n\": 3,
    \"stream\": false
  }"
```

响应：
```json
{
  "query": "产品的核心功能有哪些？",
  "knowledge_base_id": "kb_abc123def45678",
  "source_nodes": [
    {
      "text": "[产品概述 > 功能特性]\n\n本产品支持...",
      "score": 0.9234,
      "doc_id": "a1b2c3d4...",
      "file_name": "product-manual.pdf",
      "chunk_index": 5,
      "header_path": "产品概述 > 功能特性",
      "context_text": "...(包含前后切片的扩展上下文)...",
      "metadata": {"header_level": 2, "content_type": "text"}
    }
  ],
  "total_candidates": 20,
  "top_k_used": 20,
  "top_n_used": 3,
  "min_score_used": 0.1
}
```

### Python 快速示例

```python
import httpx

BASE = "http://localhost:8000/api/v1"

async def main():
    async with httpx.AsyncClient(timeout=60) as client:
        # 1. 创建知识库
        r = await client.post(f"{BASE}/kb/create", json={
            "knowledge_base_name": "test-kb",
            "description": "测试知识库",
        })
        kb_id = r.json()["knowledge_base_id"]

        # 2. 上传文件
        with open("document.pdf", "rb") as f:
            r = await client.post(
                f"{BASE}/document/upload",
                params={"knowledge_base_id": kb_id},
                files={"file": ("document.pdf", f)},
            )
        doc_id = r.json()["doc_id"]

        # 3. 触发向量化
        await client.post(f"{BASE}/document/vectorize", json={
            "knowledge_base_id": kb_id,
            "doc_ids": [doc_id],
        })

        # 4. 等待处理完成
        import asyncio
        while True:
            r = await client.get(f"{BASE}/document/list/{kb_id}")
            docs = r.json()["documents"]
            if all(d["status"] in ("completed", "failed") for d in docs):
                break
            await asyncio.sleep(2)

        # 5. 检索
        r = await client.post(f"{BASE}/retrieve", json={
            "user_id": "python-client",
            "knowledge_base_id": kb_id,
            "query": "文档的主要内容是什么？",
            "top_n": 3,
            "stream": False,
        })
        result = r.json()
        for node in result["source_nodes"]:
            print(f"[{node['score']:.4f}] {node['text'][:100]}...")

import asyncio
asyncio.run(main())
```

---

## 2. API 端点参考

### 知识库管理

#### POST `/api/v1/kb/create`

创建新知识库。

```bash
curl -X POST http://localhost:8000/api/v1/kb/create \
  -H "Content-Type: application/json" \
  -d '{"knowledge_base_name": "my-kb", "description": "描述"}'
```

```python
r = await client.post(f"{BASE}/kb/create", json={
    "knowledge_base_name": "my-kb",
    "description": "描述",
})
```

#### GET `/api/v1/kb/list`

列出所有知识库。

```bash
curl http://localhost:8000/api/v1/kb/list
```

```python
r = await client.get(f"{BASE}/kb/list")
kbs = r.json()["knowledge_bases"]
```

#### PATCH `/api/v1/kb/{kb_id}`

更新知识库名称或描述。

```bash
curl -X PATCH http://localhost:8000/api/v1/kb/kb_abc123 \
  -H "Content-Type: application/json" \
  -d '{"knowledge_base_name": "新名称"}'
```

```python
r = await client.patch(f"{BASE}/kb/{kb_id}", json={
    "knowledge_base_name": "新名称",
})
```

#### DELETE `/api/v1/kb/{kb_id}`

删除知识库及其所有文档和向量。

```bash
curl -X DELETE http://localhost:8000/api/v1/kb/kb_abc123
```

```python
r = await client.delete(f"{BASE}/kb/{kb_id}")
```

---

### 文档管理

#### POST `/api/v1/document/upload`

上传文件到指定知识库。

```bash
curl -X POST "http://localhost:8000/api/v1/document/upload?knowledge_base_id=kb_abc123" \
  -F "file=@./document.pdf"

# 指定自定义切分参数
curl -X POST "http://localhost:8000/api/v1/document/upload?knowledge_base_id=kb_abc123&chunk_size=2048&chunk_overlap=256" \
  -F "file=@./document.pdf"
```

```python
with open("document.pdf", "rb") as f:
    r = await client.post(
        f"{BASE}/document/upload",
        params={"knowledge_base_id": kb_id, "chunk_size": 2048},
        files={"file": ("document.pdf", f)},
    )
```

#### GET `/api/v1/document/list/{kb_id}`

列出知识库中的所有文档。

```bash
curl http://localhost:8000/api/v1/document/list/kb_abc123
```

```python
r = await client.get(f"{BASE}/document/list/{kb_id}")
docs = r.json()["documents"]
# 检查处理状态
for doc in docs:
    print(f"{doc['file_name']}: {doc['status']} ({doc['chunk_count']} chunks)")
```

#### POST `/api/v1/document/vectorize`

批量触发文档向量化。

```bash
curl -X POST http://localhost:8000/api/v1/document/vectorize \
  -H "Content-Type: application/json" \
  -d '{
    "knowledge_base_id": "kb_abc123",
    "doc_ids": ["doc1_hash", "doc2_hash"],
    "chunk_size": 1024,
    "chunk_overlap": 128
  }'
```

```python
r = await client.post(f"{BASE}/document/vectorize", json={
    "knowledge_base_id": kb_id,
    "doc_ids": [doc_id_1, doc_id_2],
})
```

#### DELETE `/api/v1/document/{kb_id}/{doc_id}`

删除文档及其向量。

```bash
curl -X DELETE http://localhost:8000/api/v1/document/kb_abc123/a1b2c3d4
```

#### GET `/api/v1/document/{kb_id}/{doc_id}/chunks`

查看文档的切片详情。

```bash
curl http://localhost:8000/api/v1/document/kb_abc123/a1b2c3d4/chunks
```

#### POST `/api/v1/document/{kb_id}/{doc_id}/retry`

重试失败的文档。

```bash
curl -X POST http://localhost:8000/api/v1/document/kb_abc123/a1b2c3d4/retry
```

#### GET `/api/v1/document/{kb_id}/{doc_id}/download`

下载原始文件。

```bash
curl -O http://localhost:8000/api/v1/document/kb_abc123/a1b2c3d4/download
```

#### PATCH `/api/v1/document/{kb_id}/{doc_id}/settings`

更新文档的切分参数（需要重新向量化才生效）。

```bash
curl -X PATCH http://localhost:8000/api/v1/document/kb_abc123/a1b2c3d4/settings \
  -H "Content-Type: application/json" \
  -d '{"chunk_size": 2048, "chunk_overlap": 256}'
```

---

### 检索

#### POST `/api/v1/retrieve`

核心检索接口，支持 JSON 和 SSE 两种响应模式。

**JSON 模式（stream=false）：**

```bash
curl -X POST http://localhost:8000/api/v1/retrieve \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "app-001",
    "knowledge_base_id": "kb_abc123",
    "query": "关键词或问题",
    "top_k": 20,
    "top_n": 3,
    "min_score": 0.1,
    "stream": false
  }'
```

```python
r = await client.post(f"{BASE}/retrieve", json={
    "user_id": "my-app",
    "knowledge_base_id": kb_id,
    "query": "查询内容",
    "top_k": 20,
    "top_n": 3,
    "stream": False,
})
result = r.json()
for node in result["source_nodes"]:
    print(f"Score: {node['score']:.4f}")
    print(f"Text: {node['text'][:200]}")
    print(f"File: {node['file_name']} Chunk: {node['chunk_index']}")
    print(f"Context: {node['context_text'][:300]}")
    print("---")
```

**SSE 模式（stream=true）：**

```python
import httpx
import json

async def stream_retrieve(kb_id: str, query: str):
    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream(
            "POST",
            f"{BASE}/retrieve",
            json={
                "user_id": "stream-client",
                "knowledge_base_id": kb_id,
                "query": query,
                "stream": True,
            },
        ) as response:
            current_event = ""
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    current_event = line[6:].strip()
                elif line.startswith("data:"):
                    data = json.loads(line[5:].strip())
                    if current_event == "status":
                        print(f"[进度] {data['step']}", end="")
                        if "candidates" in data:
                            print(f" (候选: {data['candidates']})")
                        else:
                            print()
                    elif current_event == "result":
                        print(f"\n[结果] {len(data['source_nodes'])} 条结果")
                        return data
                    elif current_event == "error":
                        print(f"[错误] {data['error']}")
                        return None
```

---

### 统计

#### GET `/api/v1/stats`

获取全局统计信息。

```bash
curl http://localhost:8000/api/v1/stats
```

```python
r = await client.get(f"{BASE}/stats")
stats = r.json()
print(f"知识库: {stats['total_knowledge_bases']}")
print(f"文档: {stats['total_documents']}")
print(f"切片: {stats['total_chunks']}")
```

---

## 3. SSE 事件格式与前端消费

### 事件类型

| 事件名 | 数据格式 | 说明 |
|--------|---------|------|
| `status` | `{"step": string, "candidates"?: number}` | 处理进度 |
| `result` | `RetrieveResponse` | 最终结果 |
| `error` | `{"error": string}` | 错误信息 |

### Step 枚举值

| step 值 | 含义 | 说明 |
|---------|------|------|
| `embedding_query` | 查询向量化 | 生成 Dense + Sparse + BM25 查询向量 |
| `hybrid_search` | 混合检索 | Qdrant 三路 Prefetch + RRF 融合 |
| `reranking` | 精排 | Reranker 交叉注意力评分 |
| `context_synthesis` | 上下文合成 | 拼接相邻切片 |
| `building_response` | 构建响应 | 组装最终结果 |

### JavaScript/TypeScript 消费代码

```typescript
import { retrieveSSE, type RetrieveResponse } from "@/lib/api";

function handleRetrieve(kbId: string, query: string) {
  const cancel = retrieveSSE(
    {
      user_id: "web-app",
      knowledge_base_id: kbId,
      query: query,
      top_k: 20,
      top_n: 3,
    },
    {
      onStatus: (step, candidates) => {
        console.log(`进度: ${step}`);
        if (candidates !== undefined) {
          console.log(`候选数量: ${candidates}`);
        }
        // 更新 UI 进度条
      },
      onResult: (result: RetrieveResponse) => {
        console.log(`完成，返回 ${result.source_nodes.length} 条结果`);
        // 渲染结果
      },
      onError: (error: string) => {
        console.error(`检索失败: ${error}`);
      },
    }
  );

  // 需要时取消请求
  // cancel();
}
```

---

## 4. 错误码参考表

### HTTP 状态码

| 状态码 | 含义 | 典型场景 |
|-------|------|---------|
| 200 | 成功 | 正常响应 |
| 400 | 请求参数错误 | 不支持的文件格式、参数验证失败 |
| 404 | 资源不存在 | 知识库/文档/任务未找到 |
| 409 | 资源冲突 | 知识库名称重复 |
| 422 | 处理失败 | 文档解析失败 |
| 500 | 服务器内部错误 | Qdrant 操作失败 |
| 502 | 上游服务错误 | Embedding/Reranker API 调用失败 |

### 错误响应格式

所有错误响应统一格式：

```json
{
  "detail": "错误描述信息"
}
```

### 常见错误及排查

| 错误信息 | 原因 | 解决方案 |
|---------|------|---------|
| `Knowledge base not found: kb_xxx` | 知识库 ID 不存在 | 检查 KB_ID 是否正确 |
| `Knowledge base name already exists` | 名称重复 | 使用不同的名称 |
| `Embedding API returned 401` | API Key 无效 | 检查 `.env` 中的 SILICONFLOW_API_KEY |
| `Embedding API returned 429` | 请求限流 | 系统会自动重试，也可降低 `embedding_batch_size` |
| `Embedding API timeout` | API 超时 | 检查网络连接，或增加超时配置 |
| `Unsupported file type: .zip` | 文件格式不支持 | 仅支持 PDF/DOCX/PPTX/XLSX/MD/TXT |
| `Failed to create collection` | Qdrant 错误 | 检查 Qdrant 存储路径权限 |
| `Original file not found` | 源文件丢失 | 文件可能被手动删除，需重新上传 |

---

## 5. 性能建议与限流

### 推荐用法

| 操作 | 建议 |
|------|------|
| 批量上传 | 使用 `/document/vectorize` 批量触发，而非逐个上传后立即触发 |
| 文件大小 | 单文件建议 < 50MB（硬限制 100MB） |
| 切片大小 | 默认 1024 字符适合大多数场景，代码文档可用 1536 |
| 并发检索 | 检索接口无限制，但受 Embedding/Reranker API 并发影响 |
| 轮询频率 | 查询文档处理状态建议 2-3 秒间隔 |

### 系统并发限制

| 资源 | 限制 | 配置项 |
|------|------|--------|
| 同时处理文档数 | 2 | `PIPELINE_MAX_CONCURRENCY` |
| 单次 Embedding API 批量大小 | 64 文本 | `EMBEDDING_BATCH_SIZE` |
| Embedding 降级并发 | 5 | `EMBEDDING_CONCURRENCY` |
| Worker 轮询间隔 | 2 秒 | `PIPELINE_POLL_INTERVAL` |

### 大批量处理建议

1. 上传所有文件（状态为 `uploaded`）
2. 一次性触发向量化（单次 `vectorize` 请求包含所有 doc_ids）
3. Worker 会按 `max_concurrency=2` 自动调度
4. 通过 `/document/list/{kb_id}` 轮询整体进度

---

## 6. 完整 Schema 附录

### RetrieveRequest

```json
{
  "user_id": "string (必填, 调用方标识)",
  "knowledge_base_id": "string (必填, 知识库ID)",
  "query": "string (必填, 查询文本)",
  "top_k": "int (可选, 默认20, 范围1-100, 粗排候选数)",
  "top_n": "int (可选, 默认3, 范围1-50, 精排返回数)",
  "min_score": "float (可选, 默认0.1, 范围0.0-1.0, 最低分数阈值)",
  "stream": "bool (可选, 默认true, 是否SSE流式)"
}
```

### RetrieveResponse

```json
{
  "query": "string",
  "knowledge_base_id": "string",
  "source_nodes": [
    {
      "text": "string (切片原文)",
      "score": "float (Reranker分数, 0-1)",
      "doc_id": "string (文档ID)",
      "file_name": "string (原始文件名)",
      "knowledge_base_id": "string",
      "chunk_index": "int|null (切片序号)",
      "header_path": "string|null (标题路径, 如 'A > B > C')",
      "context_text": "string|null (含前后切片的扩展上下文)",
      "metadata": {
        "header_level": "int (标题层级, 0-6)",
        "content_type": "string ('text'|'code'|'table')",
        "chunk_index": "int",
        "header_path": "string"
      }
    }
  ],
  "total_candidates": "int (粗排候选总数)",
  "top_k_used": "int (实际使用的top_k)",
  "top_n_used": "int (实际使用的top_n)",
  "min_score_used": "float|null (实际使用的min_score)"
}
```

### SourceNode 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `text` | string | 切片原文（含标题前缀） |
| `score` | float | Reranker 相关性评分（0-1，越高越相关） |
| `doc_id` | string | 文档 ID（SHA256 哈希前 32 位） |
| `file_name` | string | 原始上传文件名 |
| `knowledge_base_id` | string | 所属知识库 ID |
| `chunk_index` | int \| null | 切片在文档中的序号（0-based） |
| `header_path` | string \| null | 标题层级路径，如 "第一章 > 1.1 概述" |
| `context_text` | string \| null | 扩展上下文（当前切片 + 前后各一个切片） |
| `metadata` | object | 附加元数据 |

### DocInfo 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `doc_id` | string | 文档唯一标识 |
| `file_name` | string | 原始文件名 |
| `knowledge_base_id` | string | 所属知识库 |
| `status` | DocumentStatus | 处理状态 |
| `chunk_count` | int | 切片数量（completed 后有值） |
| `chunk_size` | int \| null | 自定义切片大小 |
| `chunk_overlap` | int \| null | 自定义重叠大小 |
| `error_message` | string \| null | 错误信息（failed 时有值） |
| `progress_message` | string \| null | 进度消息（处理中时有值） |
| `upload_timestamp` | string | 上传时间 (ISO 8601) |
| `updated_at` | string | 最后更新时间 (ISO 8601) |

### DocumentStatus 枚举

| 值 | 说明 |
|---|------|
| `uploaded` | 已上传，未触发向量化 |
| `pending` | 等待 Worker 处理 |
| `parsing` | 正在解析文档为 Markdown |
| `chunking` | 正在切分 |
| `embedding` | 正在生成向量 |
| `upserting` | 正在写入向量库 |
| `completed` | 处理完成 |
| `failed` | 处理失败（查看 error_message） |
