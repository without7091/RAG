# 检索优化方案评估

> 目标：在现有 Dense + BM42 Sparse + Reranker 三段式检索的基础上，引入 BM25 关键词检索并综合评估当前最佳实践，**不引入额外外部 API**。

---

## 一、当前架构分析

### 现有流水线

```
Query ──┬── Dense Embedding (Qwen3-Embedding-4B, SiliconFlow API)  ── Prefetch top_k
        │
        └── Sparse Embedding (BM42, SiliconFlow API)               ── Prefetch top_k
                                                                          │
                                                                    RRF Fusion
                                                                          │
                                                                    Reranker (Qwen3-Reranker-4B)
                                                                          │
                                                                    min_score 过滤
                                                                          │
                                                                    上下文合成 (±1 chunk)
```

### 已知问题

| 问题 | 说明 |
|------|------|
| **BM42 已被官方降级为实验性方案** | Qdrant 发布后承认基准测试脚本有误，BM42 并不优于标准 BM25。原文已追加声明：*"Please consider BM42 as an experimental approach"* |
| **缺少纯关键词精确匹配** | BM42 是 learned sparse representation，对专有名词、编号、型号等精确关键词匹配能力不如 BM25 |
| **稀疏向量依赖外部 API** | 当前 BM42 通过 SiliconFlow embedding API 生成，增加了网络延迟和成本 |
| **上下文窗口固定** | 固定 ±1 chunk，不能根据文档结构自适应扩展 |
| **融合策略单一** | 仅 RRF，无法调整 dense/sparse 权重 |

---

## 二、BM25 方案对比

### 2.1 可选方案总览

| 方案 | 原理 | 额外依赖 | 是否需要 API | 中文支持 | 索引持久化 | 推荐度 |
|------|------|---------|-------------|---------|-----------|--------|
| **A. Qdrant 原生 BM25** | 客户端分词生成稀疏向量，Qdrant 服务端计算 IDF | qdrant-client (已有) | 否 | 需自定义分词 | Qdrant 管理 | ★★★★★ |
| **B. bm25s 库** | 纯 Python 高性能 BM25 引擎 | bm25s (~55MB) | 否 | 需自定义分词 | 支持磁盘保存 | ★★★★ |
| **C. tantivy-py** | Rust 全文搜索引擎的 Python 绑定 | tantivy (~10MB) | 否 | 需 CJK 扩展 | 磁盘索引 | ★★★ |
| **D. rank_bm25** | 经典 Python BM25 实现 | rank_bm25 | 否 | 需自定义分词 | 不支持 | ★★ |

### 2.2 方案 A：Qdrant 原生 BM25（推荐）

**当前 qdrant-client 版本 1.17.0，完全支持此方案。**

核心思路：将 BM25 作为第二个 sparse vector 存储在 Qdrant 中，与 Dense 向量共存于同一个 Collection，利用 Qdrant 的 Prefetch + RRF 实现服务端三路融合。

**架构变更：**

```
Collection 向量配置:
├── "dense"   → VectorParams(size=1024, distance=COSINE)
├── "sparse"  → SparseVectorParams(modifier=IDF)    # 保留原 BM42（或替换为 miniCOIL）
└── "bm25"    → SparseVectorParams(modifier=IDF)    # 新增 BM25
```

**检索流程变更：**

```
Query ──┬── Dense Embedding (SiliconFlow API)    ── Prefetch top_k
        │
        ├── Sparse Embedding (BM42/miniCOIL)      ── Prefetch top_k
        │
        └── BM25 Sparse (本地分词, 无需 API)       ── Prefetch top_k
                                                          │
                                                    RRF / DBSF Fusion
                                                          │
                                                    Reranker (SiliconFlow API)
```

**优势：**
- 零额外基础设施：BM25 向量存入同一个 Qdrant Collection
- 零额外 API 调用：分词在客户端本地完成
- 融合由 Qdrant 服务端执行，单次查询完成
- IDF 由 Qdrant 自动计算维护，无需手动管理

**实现要点：**

```python
# 1. Collection 创建 — 添加 BM25 向量空间
await client.create_collection(
    collection_name=kb_id,
    vectors_config={
        "dense": models.VectorParams(size=1024, distance=models.Distance.COSINE),
    },
    sparse_vectors_config={
        "sparse": models.SparseVectorParams(modifier=models.Modifier.IDF),  # BM42/miniCOIL
        "bm25": models.SparseVectorParams(modifier=models.Modifier.IDF),    # BM25
    },
)

# 2. 文档写入 — 同时生成三种向量
point = models.PointStruct(
    id=uuid4(),
    vector={
        "dense": dense_vector,         # from SiliconFlow API
        "sparse": sparse_vector,       # from BM42/miniCOIL
        "bm25": bm25_sparse_vector,    # from 本地 BM25 分词
    },
    payload=metadata,
)

# 3. 三路混合检索
results = await client.query_points(
    collection_name=kb_id,
    prefetch=[
        models.Prefetch(query=dense_vector, using="dense", limit=top_k),
        models.Prefetch(query=sparse_vector, using="sparse", limit=top_k),
        models.Prefetch(query=bm25_vector, using="bm25", limit=top_k),
    ],
    query=models.FusionQuery(fusion=models.Fusion.RRF),
    limit=top_k,
)
```

**BM25 本地分词方案（中文适配）：**

由于 Qdrant 内置的 BM25 分词器默认仅支持英文（Snowball stemmer），中文文档需要客户端自行分词后传入稀疏向量：

```python
import jieba
from collections import Counter

def text_to_bm25_sparse(text: str) -> dict:
    """将文本转换为 BM25 稀疏向量（TF 部分，IDF 由 Qdrant 计算）。"""
    tokens = jieba.lcut(text)
    # 去停用词
    tokens = [t for t in tokens if len(t.strip()) > 0 and t not in STOPWORDS]
    # 计算词频
    tf = Counter(tokens)
    # 映射到固定词表索引（或使用 hash）
    indices = [hash_token(t) for t in tf.keys()]
    values = [float(c) for c in tf.values()]
    return {"indices": indices, "values": values}
```

> 注：也可直接使用 FastEmbed 的 `Qdrant/bm25` 模型，它内置了英文分词 + IDF 处理。中文场景需评估效果或自定义分词。

### 2.3 方案 B：bm25s 独立索引

如果需要对 BM25 有完全控制权（自定义 BM25 变体、参数调优等），可使用 bm25s 作为独立索引：

```python
import bm25s

# 建索引（文档入库时）
corpus_tokens = bm25s.tokenize(texts, stopwords="zh")  # 需自定义中文分词
retriever = bm25s.BM25()
retriever.index(corpus_tokens)
retriever.save("./data/bm25_index/kb_xxx")

# 检索（查询时）
query_tokens = bm25s.tokenize([query], stopwords="zh")
results, scores = retriever.retrieve(query_tokens, k=top_k)
```

**然后在应用层与 Qdrant 结果做 RRF 融合：**

```python
def rrf_fusion(result_lists: list[list], k: int = 60) -> list:
    """Reciprocal Rank Fusion — 多路结果融合。"""
    scores = {}
    for result_list in result_lists:
        for rank, item in enumerate(result_list):
            doc_key = item["doc_id"] + "_" + str(item["chunk_index"])
            scores[doc_key] = scores.get(doc_key, 0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)
```

**优势：** 完全控制 BM25 参数（k1, b, delta）、支持 5 种 BM25 变体、500x 快于 rank_bm25
**劣势：** 需要单独管理索引生命周期（创建/更新/删除与 Qdrant 同步）、融合在应用层执行（多一次网络往返 vs Qdrant 服务端融合）

### 2.4 方案 C/D 不推荐的理由

| 方案 | 不推荐理由 |
|------|-----------|
| **tantivy-py** | 引入 Rust 依赖，CJK 支持需额外扩展，运维复杂度高，与 Qdrant 功能重叠 |
| **rank_bm25** | 已停止维护，无持久化，大数据集性能差，不适合生产环境 |

---

## 三、BM42 处置方案

BM42 已被 Qdrant 官方降级为实验性方案，建议有三种处理方式：

| 策略 | 说明 | 代价 |
|------|------|------|
| **替换为 BM25** | 直接用 BM25 稀疏向量替换现有的 BM42 | 需重新索引全部文档，省掉一路 API 调用 |
| **替换为 miniCOIL** | 使用 Qdrant 推荐的 `Qdrant/minicoil-v1`，兼具语义和关键词能力 | 需 FastEmbed 本地模型，需重新索引 |
| **保留 BM42 + 新增 BM25** | 三路并存，BM42 提供 learned sparse，BM25 提供纯关键词 | 存储空间增加，但无需重新索引已有数据 |

**推荐策略：替换为 BM25**。理由：
1. 减少一路 SiliconFlow API 调用（BM42 走 API，BM25 本地生成）
2. BM25 在精确匹配场景已证明优于 BM42
3. 架构更简洁：Dense（语义）+ BM25（关键词），职责清晰

---

## 四、超越 BM25 — 其他检索优化

### 4.1 融合策略优化

当前仅使用 RRF，Qdrant 还支持 **DBSF (Distribution-Based Score Fusion)**：

| 融合方法 | 特点 | 适用场景 |
|---------|------|---------|
| **RRF** | 基于排名位置，忽略原始分数，无需调参 | 通用默认选择 |
| **DBSF** | 基于分数分布归一化后加权，对分数差异敏感 | 当某路检索质量明显更高时 |

建议：默认用 RRF，提供 API 参数让调用方可选 DBSF。

### 4.2 上下文合成优化

当前固定 ±1 chunk 的策略可升级：

**方案 A：可配置窗口大小**
```python
# 从固定 ±1 改为可配置
context_window: int = 1  # 请求参数，默认 1，可设为 2-3
for ci in range(chunk_index - context_window, chunk_index + context_window + 1):
    if ci in chunk_map:
        parts.append(chunk_map[ci])
```

**方案 B：按 Heading 边界截取**

利用 chunk 中已存储的 `header_path` 元数据，将上下文扩展限制在同一个 heading section 内：

```python
current_header = node.get("header_path", "")
for ci in sorted(chunk_map.keys()):
    chunk = chunk_map[ci]
    if chunk["header_path"] == current_header:
        parts.append(chunk["text"])
```

**方案 C：Parent-Child 分层检索**

在分块时同时生成大块（parent, ~2000 tokens）和小块（child, ~512 tokens）。检索用小块匹配精度高，返回时用大块提供完整上下文。这需要较大的架构改动，可作为后续迭代。

### 4.3 检索候选数优化

当前 dense 和 sparse 各取相同的 top_k，可以分别设置：

```python
prefetch=[
    models.Prefetch(query=dense_vector, using="dense", limit=top_k * 2),   # 语义多召回
    models.Prefetch(query=bm25_vector, using="bm25", limit=top_k),         # 关键词精确
],
```

经验值：dense 通常设 2-3x top_k，BM25 设 1-1.5x top_k，最终 RRF 融合后取 top_k 给 reranker。

### 4.4 Lost-in-the-Middle 缓解

LLM 对上下文中间位置的信息关注度最低（U 形注意力曲线）。在最终返回结果时，可重新排列 source_nodes：

```python
def mitigate_lost_in_middle(nodes: list[dict]) -> list[dict]:
    """将最相关的结果放在首尾，次相关放中间。"""
    if len(nodes) <= 2:
        return nodes
    sorted_nodes = sorted(nodes, key=lambda x: x["score"], reverse=True)
    result = []
    for i, node in enumerate(sorted_nodes):
        if i % 2 == 0:
            result.append(node)       # 偶数位 → 前端
        else:
            result.insert(len(result) // 2, node)  # 奇数位 → 中间
    return result
```

### 4.5 Payload 索引加速过滤

为 Qdrant Collection 添加 payload 索引，支持按文件名、文档类型等字段快速过滤：

```python
await client.create_payload_index(
    collection_name=kb_id,
    field_name="file_name",
    field_schema="keyword",
)
await client.create_payload_index(
    collection_name=kb_id,
    field_name="doc_id",
    field_schema="keyword",
)
```

这使得混合检索时可以附加过滤条件（如只搜某个文档），且不影响向量搜索性能。

---

## 五、推荐实施路线

### Phase 1：引入 BM25 + 替换 BM42（核心改动）

**改动范围：**

| 文件 | 改动 |
|------|------|
| `config.py` | 新增 BM25 分词配置项，移除 BM42 API 配置 |
| `services/bm25_service.py` | **新建** — 本地 BM25 分词服务（jieba 分词 + 稀疏向量生成） |
| `services/vector_store_service.py` | Collection 创建增加 `"bm25"` 向量空间；`upsert_points` 接收 BM25 向量；`hybrid_search` 改为三路 Prefetch（或替换 BM42 为 BM25 后仍为两路） |
| `services/pipeline_service.py` | 文档处理流水线增加 BM25 向量生成步骤 |
| `services/retrieval_service.py` | 查询时生成 BM25 query 向量，传入混合检索 |
| `services/sparse_embedding_service.py` | 如果完全替换 BM42，此服务可简化或移除 API 模式 |

**新增依赖：**
```
jieba>=0.42.0          # 中文分词（~15MB）
```

> 如果文档主要是英文，可直接使用 Qdrant/FastEmbed 的内置 BM25 模型，无需 jieba。

### Phase 2：检索参数精细化

- 融合策略可选（RRF / DBSF）
- 各路 Prefetch limit 独立配置
- 上下文窗口大小可配置
- Payload 索引创建

### Phase 3：高级优化（可选）

- Lost-in-the-Middle 重排
- Parent-Child 分层检索
- 条件性 Reranking（高置信度跳过 Reranker 节省 API 调用）

---

## 六、方案对比总结

| 维度 | 现状 (Dense + BM42) | 方案 A (Dense + BM25, Qdrant 原生) | 方案 B (Dense + BM25, bm25s) |
|------|---------------------|-------------------------------------|------------------------------|
| 关键词匹配 | 弱（BM42 实验性） | 强（BM25 经典验证） | 强（BM25 经典验证） |
| API 调用数 | 2 次（Dense + Sparse） | 1 次（仅 Dense） | 1 次（仅 Dense） |
| 额外依赖 | 无 | jieba（中文场景） | bm25s + jieba |
| 索引管理 | Qdrant 统一 | Qdrant 统一 | 需同步两套索引 |
| 融合执行 | Qdrant 服务端 | Qdrant 服务端 | 应用层 |
| 改动量 | — | 中等 | 较大 |
| 推荐度 | — | ★★★★★ | ★★★★ |

**最终推荐：方案 A — Qdrant 原生 BM25 替换 BM42**

这是改动最小、收益最大的方案：减少一次 API 调用、提升关键词匹配能力、架构更简洁。
