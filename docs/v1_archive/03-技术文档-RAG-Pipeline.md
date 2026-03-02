# 技术文档：RAG Pipeline 全链路深度解析

> 从文档上传到向量入库的完整数据流

## 目录

- [1. Pipeline 全景](#1-pipeline-全景)
- [2. 文档解析（Parse）](#2-文档解析parse)
- [3. 树状语义切分（Chunk）](#3-树状语义切分chunk)
- [4. 三路向量生成（Embed）](#4-三路向量生成embed)
- [5. Delete-before-Insert 幂等入库](#5-delete-before-insert-幂等入库)
- [6. doc_id 内容哈希策略](#6-doc_id-内容哈希策略)
- [7. Pipeline 执行编排](#7-pipeline-执行编排)

---

## 1. Pipeline 全景

```
Upload → Parse(MarkItDown) → Chunk(树状切分) → Embed(三路) → Upsert(Delete-before-Insert)
                                                  │
                                    ┌─────────────┼─────────────┐
                                    │             │             │
                              Dense(1024维)  SPLADE(Learned)  BM25(TF)
                              SiliconFlow API  FastEmbed本地   Jieba+CRC32
```

### 处理状态机

```
UPLOADED ─(触发向量化)→ PENDING ─(Worker拾取)→ PARSING → CHUNKING → EMBEDDING → UPSERTING → COMPLETED
                                                  │          │           │           │
                                                  └──────────┴───────────┴───────────┘
                                                               ↓
                                                             FAILED
```

每个阶段都记录进度消息到 SQLite（`progress_message` 字段），前端通过轮询展示实时状态。

---

## 2. 文档解析（Parse）

### 核心逻辑

文件: `backend/app/services/parsing_service.py`

```python
async def parse_file(self, file_path: str) -> str:
    suffix = Path(file_path).suffix.lower()
    if suffix in (".md", ".txt"):
        # 直接读取，零损耗
        async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
            return await f.read()
    # 二进制格式通过 MarkItDown 转换为 Markdown
    result = self.converter.convert(file_path)
    return result.text_content
```

### 支持格式

| 格式 | 处理方式 | 保真度 |
|------|---------|--------|
| `.md` | 直接读取 | 100% |
| `.txt` | 直接读取 | 100% |
| `.pdf` | MarkItDown 转换 | 保留标题层级和表格 |
| `.docx` | MarkItDown 转换 | 保留标题和结构 |
| `.pptx` | MarkItDown 转换 | 按页转换 |
| `.xlsx` | MarkItDown 转换 | 转为 Markdown 表格 |

### Markdown-First 策略的意义

所有非 Markdown 格式都先转换为 `.md`，因为：

1. **标题层级保留**：Markdown 的 `#` 到 `######` 提供了天然的语义层级信息
2. **统一切分接口**：切分算法只需处理一种格式
3. **表格和代码块边界清晰**：Markdown 的 fenced code block 和 `|` 表格语法可被精确识别
4. **可人工审查**：转换后的 Markdown 可直接查看验证

---

## 3. 树状语义切分（Chunk）

### 为什么弃用 LlamaIndex MarkdownNodeParser

LlamaIndex 内置的 `MarkdownNodeParser` 存在以下局限：

1. **扁平切分**：按标题行分割，不理解标题层级关系
2. **缺少上下文传递**：子节点丢失父标题信息，检索到的切片无法定位在文档中的位置
3. **溢出处理粗暴**：超长段落简单截断，不考虑 CJK 语境
4. **代码/表格不保护**：可能在代码块或表格中间切断

### 自研三阶段算法

文件: `backend/app/services/chunking_service.py`

#### 阶段 1：解析 Markdown 为标题树

```python
def _parse_markdown_tree(text: str) -> SectionNode:
```

将 Markdown 文本解析为嵌套的 `SectionNode` 树结构：

```python
@dataclass
class SectionNode:
    header: str                           # 标题文本（root 为空）
    level: int                            # 0=root, 1-6=h1-h6
    content_lines: list[str]              # 该节点下的正文行
    children: list["SectionNode"]         # 子节点
```

**关键处理：**

- **栈式层级管理**：用栈（stack）追踪从 root 到当前插入点的路径，遇到新标题时弹栈回溯到正确的父节点
- **层级跳跃处理**：允许 h1 直接跳到 h3（跳过 h2），算法通过 `while stack[-1].level >= level` 正确回溯
- **Fenced Code Block 保护**：在代码块内部的 `#` 行不会被误识别为标题
- **首内容归 root**：第一个标题之前的内容归属到 root 节点

示例输入：
```markdown
# 产品概述
这是概述内容。

## 功能特性
功能描述...

### 子功能 A
详细说明...

## 技术架构
架构描述...
```

解析后的树结构：
```
root (level=0)
├── "产品概述" (level=1)
│   ├── content: "这是概述内容。"
│   ├── "功能特性" (level=2)
│   │   ├── content: "功能描述..."
│   │   └── "子功能 A" (level=3)
│   │       └── content: "详细说明..."
│   └── "技术架构" (level=2)
│       └── content: "架构描述..."
```

#### 阶段 2：收集切片

```python
def _collect_chunks(node, ancestors, service) -> list[dict]:
```

递归遍历标题树，为每个有实际内容的节点生成切片：

1. **祖先路径传递**：`ancestors` 列表逐层传递标题信息
2. **标题前缀生成**：每个切片自动附加标题路径前缀，如 `[产品概述 > 功能特性 > 子功能 A]\n\n`
3. **超长内容触发溢出保护**：当 `len(prefix + content) > chunk_size` 时，进入 `_split_overflow`
4. **短内容过滤**：内容短于 `min_chunk_size`（默认 50 字符）且有子节点时跳过，让标题信息流向子切片

#### 阶段 3：溢出保护（CJK 感知分割）

```python
def _split_overflow(text, max_size, overlap) -> list[str]:
```

当单个节点内容超过 `chunk_size` 时，启动智能分割：

**原子区域保护（`_segment_atomic`）：**

```python
def _segment_atomic(text: str) -> list[tuple[str, bool]]:
```

先将文本分割为原子/非原子段落：
- **代码块**（fenced code block）→ 标记为 atomic，尽量不拆分
- **表格**（连续 `|` 开头的行）→ 标记为 atomic
- **普通文本** → 标记为 non-atomic，可自由分割

**CJK 感知分割点优先级（`_find_split_pos`）：**

```python
separators = ["\n\n", "\n", "。", "！", "？", "；", "，", "、", ". ", "! ", "? ", " "]
```

搜索顺序：
1. `\n\n` — 段落边界（最佳分割点）
2. `\n` — 行边界
3. `。！？；` — 中文句末标点
4. `，、` — 中文逗号/顿号
5. `. ! ? ` — 英文标点（含后续空格）
6. ` ` — 空格
7. 字符级截断 — 最终兜底

每个分割点要求 `pos > max_size // 4`，防止过早分割导致碎片化。

**重叠实现（`_force_split`）：**

```python
# 下一个切片从 (split_pos - overlap) 位置开始
# 但会 snap forward 到最近的句子边界
rewind_start = max(pos, split_pos - overlap)
# 在 rewind 区域搜索第一个句子边界
for sep in ["\n", "。", "！", "？", "；", ". ", "! ", "? "]:
    p = rewind_zone.find(sep)
```

重叠不是简单地回退 N 个字符，而是 snap 到最近的句子边界，确保重叠区域从可读的位置开始。

### 切分输出示例

输入文档结构：
```markdown
# 产品手册
## 第一章 概述
这是一段很长的产品概述文字...（假设 2000 字）
## 第二章 安装指南
### 2.1 系统要求
CPU: 4核, RAM: 8GB
### 2.2 安装步骤
1. 下载安装包...
```

输出切片：

| chunk_index | header_path | text (摘要) |
|-------------|------------|-------------|
| 0 | 产品手册 > 第一章 概述 | `[产品手册 > 第一章 概述]\n\n这是一段很长的产品概述文字...（前半）` |
| 1 | 产品手册 > 第一章 概述 | `[产品手册 > 第一章 概述]\n\n...概述文字（后半，含重叠）` |
| 2 | 产品手册 > 第二章 安装指南 > 2.1 系统要求 | `[产品手册 > 第二章 安装指南 > 2.1 系统要求]\n\nCPU: 4核, RAM: 8GB` |
| 3 | 产品手册 > 第二章 安装指南 > 2.2 安装步骤 | `[产品手册 > 第二章 安装指南 > 2.2 安装步骤]\n\n1. 下载安装包...` |

### TextNode 元数据结构

每个切片封装为 LlamaIndex `TextNode`：

```python
TextNode(
    text="[产品概述 > 功能特性]\n\n详细内容...",
    metadata={
        "doc_id": "a1b2c3d4...",
        "file_name": "product.pdf",
        "knowledge_base_id": "kb_abc123",
        "chunk_index": 0,
        "header_path": "产品概述 > 功能特性",
        "header_level": 2,
        "content_type": "text",  # "text" | "code" | "table"
    },
)
```

---

## 4. 三路向量生成（Embed）

每个切片生成三种向量表示，分别捕捉不同维度的语义信息：

### 4.1 Dense 向量 — 语义理解

**模型：** Qwen3-Embedding-4B（通过 SiliconFlow API）

**维度：** 1024

**作用：** 捕捉深层语义相似度，理解同义词、近义表达

```python
# backend/app/services/embedding_service.py
async def embed_texts(self, texts: list[str]) -> list[list[float]]:
    # 自动分批 (batch_size=64)
    for i in range(0, total, self.batch_size):
        batch = texts[i : i + self.batch_size]
        result = await self._embed_batch(batch)
        all_embeddings.extend(result)
```

**容错机制：**
- HTTP 400 错误自动降级到逐条发送（`_fallback_to_single` 标记）
- 降级后使用 `Semaphore(embedding_concurrency=5)` 控制并发
- 指数退避重试（最多 3 次）

### 4.2 Sparse 向量 — Learned Sparse（SPLADE）

**模型：** Qdrant/bm25（FastEmbed 本地模型）

**作用：** 学习到的词项权重，比传统 BM25 更智能的关键词匹配

```python
# backend/app/services/sparse_embedding_service.py
# 本地模式: FastEmbed SPLADE
def _local_embed_texts(self, texts: list[str]) -> list[dict]:
    model = self._get_local_model()
    embeddings = list(model.embed(texts))
    return [
        {"indices": emb.indices.tolist(), "values": emb.values.tolist()}
        for emb in embeddings
    ]
```

**双模式支持：**
- `local`：使用 FastEmbed 本地运行 SPLADE 模型（推荐，无网络依赖）
- `api`：调用远程 HTTP API（与 Dense Embedding 共享容错逻辑）

### 4.3 BM25 向量 — 传统关键词

**实现：** 自研 BM25Service（Jieba 分词 + CRC32 哈希）

**作用：** 精确的关键词匹配，对专有名词、编号等查询类型效果好

```python
# backend/app/services/bm25_service.py
class BM25Service:
    def text_to_sparse_vector(self, text: str) -> dict:
        tokens = self.tokenize(text)    # Jieba 分词 → 去停用词
        tf: dict[int, float] = {}
        for token in tokens:
            idx = self._hash_token(token)  # CRC32(token) % 1_048_576
            tf[idx] = tf.get(idx, 0) + 1.0
        sorted_indices = sorted(tf.keys())
        return {
            "indices": sorted_indices,
            "values": [tf[i] for i in sorted_indices],
        }
```

**关键设计：**
- **Jieba 分词**：对中文文本进行准确分词
- **CRC32 哈希**：将 token 映射到 [0, 2^20) 空间，作为稀疏向量的 index
- **TF 计数**：值为词频（Term Frequency）
- **服务端 IDF**：Qdrant 的 `SparseVectorParams(modifier=Modifier.IDF)` 自动在查询时应用 IDF 加权
- **内置停用词**：200+ 中英文停用词 + 标点符号过滤

### 三路向量互补关系

| 场景 | Dense | SPLADE | BM25 |
|------|-------|--------|------|
| "机器学习的应用" | 强 (语义) | 中 | 中 |
| "RFC-7231 协议" | 弱 | 中 | 强 (精确匹配) |
| "怎样提高性能" | 强 (同义) | 中 | 弱 (词不匹配) |
| "API 接口文档" | 中 | 强 (学习权重) | 强 |

---

## 5. Delete-before-Insert 幂等入库

### 问题

同一个文档重复上传或重新向量化时，如何防止向量库中出现重复数据？

### 解决方案

在每次 Upsert 前，先按 `doc_id` 删除该文档的所有旧向量点：

```python
# backend/app/services/pipeline_service.py:146-175
# Step 5: Upsert to vector store (delete-before-insert)
await self.vector_store.delete_by_doc_id(knowledge_base_id, doc_id)

payloads = []
for node in nodes:
    payload = {
        "text": node.text,
        "doc_id": doc_id,
        "file_name": file_name,
        "knowledge_base_id": knowledge_base_id,
        "chunk_index": node.metadata.get("chunk_index", 0),
        "header_path": node.metadata.get("header_path", ""),
        "header_level": node.metadata.get("header_level", 0),
        "content_type": node.metadata.get("content_type", "text"),
    }
    payloads.append(payload)

await self.vector_store.upsert_points(
    knowledge_base_id, dense_vectors, sparse_vectors, payloads,
    bm25_vectors=bm25_vectors,
)
```

### Qdrant 过滤删除

```python
# backend/app/services/vector_store_service.py:57-75
async def delete_by_doc_id(self, collection_name: str, doc_id: str) -> None:
    await self.client.delete(
        collection_name=collection_name,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="doc_id",
                        match=models.MatchValue(value=doc_id),
                    )
                ]
            )
        ),
    )
```

### 幂等性保证

1. 相同文件（内容哈希相同）→ 相同 `doc_id` → 删除旧的 → 插入新的
2. 修改后的文件（内容变化）→ 不同 `doc_id` → 不影响旧版本（除非手动删除）
3. 重新向量化 → `needs_vector_cleanup=True` → Worker 先清理旧向量

---

## 6. doc_id 内容哈希策略

### 生成算法

```python
# backend/app/utils/id_gen.py
import hashlib

def generate_doc_id(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()[:32]
```

- 算法：SHA-256
- 截断：取前 32 个十六进制字符（128 位）
- 输入：文件原始字节内容

### 设计考量

| 特性 | 说明 |
|------|------|
| **内容寻址** | 相同内容 → 相同 ID，天然去重 |
| **碰撞概率** | 128 位空间，实际碰撞概率极低 |
| **不可逆** | 无法从 ID 反推文件内容 |
| **确定性** | 同一文件任何时候上传，ID 一致 |

### 与知识库的关系

`doc_id` 不包含 `knowledge_base_id` 信息，因此同一文件上传到不同知识库时，`doc_id` 相同但属于不同 Collection，不会冲突。唯一约束为 `(knowledge_base_id, doc_id)`。

---

## 7. Pipeline 执行编排

### PipelineService 完整流程

文件: `backend/app/services/pipeline_service.py`

```
┌─────────┐   ┌──────────┐   ┌──────────────────────────┐
│ PARSING │ → │ CHUNKING │ → │ EMBEDDING (3 stages)     │
│         │   │          │   │ ├ Dense (API, batch)      │
│MarkItDown   │ 树状切分  │   │ ├ Sparse (local/API)     │
│ → .md   │   │ → TextNode│   │ └ BM25 (local, jieba)    │
└─────────┘   └──────────┘   └──────────┬───────────────┘
                                         │
                              ┌──────────▼───────────────┐
                              │ UPSERTING                 │
                              │ ├ delete_by_doc_id()      │
                              │ └ upsert_points()         │
                              │   (dense+sparse+bm25)     │
                              └──────────┬───────────────┘
                                         │
                              ┌──────────▼───────────────┐
                              │ COMPLETED                 │
                              │ chunk_count 记录到 SQLite  │
                              └──────────────────────────┘
```

### 各阶段耗时日志

Pipeline 内每个阶段都有 `time.perf_counter()` 计时：

```
Pipeline[a1b2c3d4e5f6] parsing: 234.5ms
Pipeline[a1b2c3d4e5f6] chunking: 12.3ms, 42 chunks
Pipeline[a1b2c3d4e5f6] dense embedding: 1523.7ms, 42 vectors
Pipeline[a1b2c3d4e5f6] sparse embedding: 876.2ms, 42 vectors
Pipeline[a1b2c3d4e5f6] BM25 vectors: 5.1ms, 42 vectors
Pipeline[a1b2c3d4e5f6] upsert: 45.8ms, 42 points
Pipeline[a1b2c3d4e5f6] completed: 42 chunks, total 2697.6ms
```

### 异常处理

任何阶段失败时，将文档状态设为 `FAILED`，记录错误信息：

```python
except Exception as e:
    logger.error(f"Pipeline failed for doc_id={doc_id}: {e}", exc_info=True)
    await self.doc_service.update_status(
        doc_id, knowledge_base_id, DocumentStatus.FAILED,
        error_message=str(e)[:1000],  # 截断到 1000 字符
    )
```
