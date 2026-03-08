# RAG Knowledge Management Platform — API Documentation

> Base URL: `http://localhost:8000/api/v1`

All responses with errors follow the format:
```json
{ "detail": "Error message" }
```

---

## 1. Knowledge Base

### 1.1 Create Knowledge Base

```
POST /api/v1/kb/create
```

Creates a new knowledge base and initializes its Qdrant collection (dense + sparse index).

**Request Body** (`application/json`):

| Field | Type | Required | Constraints | Description |
|---|---|---|---|---|
| `knowledge_base_name` | string | Yes | 1-128 chars | Knowledge base display name |
| `folder_id` | string | No | 1-64 chars | Target level-2 folder ID; omitted values fall back to the default folder |
| `description` | string | No | max 512 chars | Description (default: `""`) |

**Response** `200`:
```json
{
  "knowledge_base_id": "kb_xxxxxxxx",
  "knowledge_base_name": "产品文档库",
  "folder_id": "folder_xxxxxxxx",
  "folder_name": "子项目A",
  "parent_folder_id": "folder_root_xxxxxxxx",
  "parent_folder_name": "项目A",
  "description": "内部产品文档",
  "created_at": "2026-02-27T10:00:00"
}
```

**Errors**:

| Code | Condition |
|---|---|
| 409 | Knowledge base with same name already exists |
| 422 | Validation error (name too short/long) |

---

### 1.2 List Knowledge Bases

```
GET /api/v1/kb/list
```

Returns all knowledge bases with their document counts.

**Response** `200`:
```json
{
  "knowledge_bases": [
    {
      "knowledge_base_id": "kb_xxxxxxxx",
      "knowledge_base_name": "产品文档库",
      "folder_id": "folder_xxxxxxxx",
      "folder_name": "子项目A",
      "parent_folder_id": "folder_root_xxxxxxxx",
      "parent_folder_name": "项目A",
      "description": "内部产品文档",
      "document_count": 12,
      "created_at": "2026-02-27T10:00:00"
    }
  ],
  "total": 1
}
```

---

### 1.3 Knowledge Base Tree

```
GET /api/v1/kb/tree
```

Returns the fixed two-level folder tree used by the data governance page.

**Response** `200`:
```json
{
  "folders": [
    {
      "type": "folder",
      "folder_id": "folder_root_xxxxxxxx",
      "folder_name": "项目A",
      "parent_folder_id": null,
      "depth": 1,
      "child_folder_count": 1,
      "knowledge_base_count": 2,
      "created_at": "2026-03-08T09:00:00",
      "children": [
        {
          "type": "folder",
          "folder_id": "folder_xxxxxxxx",
          "folder_name": "子项目A",
          "parent_folder_id": "folder_root_xxxxxxxx",
          "depth": 2,
          "knowledge_base_count": 2,
          "created_at": "2026-03-08T09:01:00",
          "knowledge_bases": []
        }
      ]
    }
  ],
  "total_knowledge_bases": 2
}
```

---

### 1.4 Knowledge Base Folders

```
POST /api/v1/kb/folders
PATCH /api/v1/kb/folders/{folder_id}
DELETE /api/v1/kb/folders/{folder_id}
```

- `POST` creates a level-1 folder when `parent_folder_id` is omitted, or a level-2 folder when it points to a level-1 folder.
- `PATCH` renames a folder.
- `DELETE` deletes only empty folders; non-empty folders return `409`.

**Create Request Body** (`application/json`):

| Field | Type | Required | Description |
|---|---|---|---|
| `folder_name` | string | Yes | Folder display name |
| `parent_folder_id` | string | No | Parent level-1 folder ID for creating a level-2 folder |

**Response** `200`:
```json
{
  "folder_id": "folder_xxxxxxxx",
  "folder_name": "子项目A",
  "parent_folder_id": "folder_root_xxxxxxxx",
  "depth": 2,
  "created_at": "2026-03-08T09:01:00"
}
```

---

### 1.5 Delete Knowledge Base

```
DELETE /api/v1/kb/{kb_id}
```

Deletes the knowledge base record and its Qdrant collection.

**Path Parameters**:

| Parameter | Type | Description |
|---|---|---|
| `kb_id` | string | Knowledge base ID |

**Response** `200`:
```json
{
  "knowledge_base_id": "kb_xxxxxxxx",
  "deleted": true
}
```

**Errors**:

| Code | Condition |
|---|---|
| 404 | Knowledge base not found |

---

## 2. Document

### 2.1 Upload Document

```
POST /api/v1/document/upload?knowledge_base_id={kb_id}
```

Uploads a file for async processing (parse → chunk → embed → upsert). Returns a task ID for tracking progress.

**Query Parameters**:

| Parameter | Type | Required | Description |
|---|---|---|---|
| `knowledge_base_id` | string | Yes | Target knowledge base ID |

**Request Body** (`multipart/form-data`):

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | file | Yes | Document file (PDF, DOCX, PPTX, XLSX, MD, TXT) |

**Response** `200`:
```json
{
  "task_id": "task_xxxxxxxx",
  "doc_id": "doc_sha256_xxxxx",
  "file_name": "guide.pdf",
  "knowledge_base_id": "kb_xxxxxxxx",
  "status": "pending"
}
```

**Errors**:

| Code | Condition |
|---|---|
| 400 | Unsupported file type |
| 404 | Knowledge base not found |

**Notes**:
- `doc_id` is a content-based SHA hash — re-uploading the same file produces the same `doc_id`
- Backend uses delete-before-insert on `doc_id`, so re-uploading effectively updates the document
- Use the returned `task_id` to poll `GET /api/v1/tasks/{task_id}` for processing status

---

### 2.2 List Documents

```
GET /api/v1/document/list/{kb_id}
```

Lists all documents in a knowledge base.

**Path Parameters**:

| Parameter | Type | Description |
|---|---|---|
| `kb_id` | string | Knowledge base ID |

**Response** `200`:
```json
{
  "documents": [
    {
      "doc_id": "doc_sha256_xxxxx",
      "file_name": "guide.pdf",
      "knowledge_base_id": "kb_xxxxxxxx",
      "status": "completed",
      "chunk_count": 42,
      "upload_timestamp": "2026-02-27T10:05:00",
      "updated_at": "2026-02-27T10:06:30"
    }
  ],
  "total": 1
}
```

**Document Status Values**:

| Status | Description |
|---|---|
| `pending` | Uploaded, waiting for processing |
| `parsing` | Converting document to Markdown |
| `chunking` | Splitting into semantic chunks |
| `embedding` | Generating dense + sparse vectors |
| `upserting` | Writing vectors to Qdrant |
| `completed` | Successfully processed |
| `failed` | Processing failed (check task error) |

---

## 3. Tasks

### 3.1 Get Task Status

```
GET /api/v1/tasks/{task_id}
```

Returns the current status of an async background task (e.g., document processing).

**Path Parameters**:

| Parameter | Type | Description |
|---|---|---|
| `task_id` | string | Task ID (from upload response) |

**Response** `200`:
```json
{
  "task_id": "task_xxxxxxxx",
  "status": "processing",
  "progress": "embedding",
  "result": null,
  "error": null,
  "created_at": "2026-02-27T10:05:00",
  "updated_at": "2026-02-27T10:05:30"
}
```

**Task Status Values**:

| Status | Description |
|---|---|
| `pending` | Created, not yet started |
| `processing` | Currently running |
| `completed` | Successfully finished |
| `failed` | Failed (see `error` field) |

**Errors**:

| Code | Condition |
|---|---|
| 404 | Task not found |

---

## 4. Retrieval

### 4.1 Retrieve

```
POST /api/v1/retrieve
```

Core retrieval endpoint: hybrid search (dense + sparse) → rerank → context synthesis. Supports two modes: SSE streaming (`stream: true`) and JSON (`stream: false`).

**Request Body** (`application/json`):

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `user_id` | string | Yes | — | min 1 char | Caller identity |
| `knowledge_base_id` | string | Yes | — | min 1 char | Target KB |
| `query` | string | Yes | — | min 1 char | Search query |
| `top_k` | int | No | 10 | 1-100 | Hybrid search candidates |
| `top_n` | int | No | 3 | 1-50 | Final results after reranking |
| `stream` | bool | No | true | — | SSE streaming mode |

---

#### JSON Mode (`stream: false`)

**Response** `200`:
```json
{
  "query": "如何配置系统参数",
  "knowledge_base_id": "kb_xxxxxxxx",
  "source_nodes": [
    {
      "text": "系统参数配置需要在管理后台...",
      "score": 0.8732,
      "doc_id": "doc_sha256_xxxxx",
      "file_name": "admin_guide.pdf",
      "knowledge_base_id": "kb_xxxxxxxx",
      "chunk_index": 5,
      "header_path": "管理指南 > 系统配置",
      "metadata": {
        "upload_timestamp": "2026-02-27T10:05:00"
      }
    }
  ],
  "total_candidates": 10,
  "top_k_used": 10,
  "top_n_used": 3
}
```

---

#### SSE Streaming Mode (`stream: true`)

**Response**: `Content-Type: text/event-stream`

Events are sent in order:

**1. Status events** — pipeline progress:

```
event: status
data: {"step": "embedding_query"}

event: status
data: {"step": "hybrid_search"}

event: status
data: {"step": "reranking", "candidates": 10}

event: status
data: {"step": "building_response"}
```

**2. Result event** — final results (same shape as JSON mode):

```
event: result
data: {"query": "...", "knowledge_base_id": "...", "source_nodes": [...], "total_candidates": 10, "top_k_used": 10, "top_n_used": 3}
```

**3. Error event** (if failure occurs):

```
event: error
data: {"error": "Error description"}
```

**SSE Step Sequence**:
`embedding_query` → `hybrid_search` → `reranking` → `building_response` → `result`

---

**Errors** (JSON mode):

| Code | Condition |
|---|---|
| 404 | Knowledge base not found |
| 422 | Validation error |
| 500 | Vector store error / unexpected error |
| 502 | Embedding or reranker API call failed |

---

## Error Code Summary

| HTTP Code | Description |
|---|---|
| 400 | Bad request (unsupported file type, invalid input) |
| 404 | Resource not found (KB / Document / Task) |
| 409 | Conflict (duplicate KB name) |
| 422 | Validation error (Pydantic) |
| 500 | Internal server error (vector store, unexpected) |
| 502 | Upstream API error (embedding / reranker service) |
