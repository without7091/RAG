# RAG 文档切分技术调研与选型报告

> 调研日期：2026-02-28
> 项目：多租户 RAG 知识管理平台（检索中台）

---

## 一、背景与问题定义

### 1.1 项目架构概要

```
上传 → 解析为 Markdown → 生成 doc_id → 分块(Chunk) →
Embedding (Dense + Sparse) → Upsert 至 Qdrant → 查询 →
混合检索 (Top-K) → Rerank (Top-N) → 上下文合成 → 返回 source_nodes
```

| 组件 | 技术选型 | 调用方式 |
|------|---------|---------|
| Dense Embedding | Qwen3-Embedding-4B | 远程 API (SiliconFlow) |
| Sparse Embedding | BM42 (FastEmbed) | 本地模型 (~88MB ONNX) |
| Reranker | Qwen3-Reranker-4B | 远程 API (SiliconFlow) |
| 向量数据库 | Qdrant | 本地磁盘存储 |
| 文档解析 | MarkItDown | 本地 |

### 1.2 当前切分策略

当前使用 LlamaIndex 的 `MarkdownNodeParser` + `SentenceSplitter` 的两阶段方案：

- **阶段一**：`MarkdownNodeParser` 按 Markdown 标题层级拆分
- **阶段二**：对超过 `chunk_size`（默认 512 字符）的块，用 `SentenceSplitter` 按句子边界二次拆分（overlap=64）

### 1.3 发现的问题

**连续标题空块问题**：当文档出现连续嵌套标题时：

```markdown
## 3 系统架构
### 3.1 后端设计
#### 3.1.1 服务层
服务层采用分层架构，包括 API 层、业务逻辑层...
```

`MarkdownNodeParser` 在每个标题边界都执行一次 flush，产出 3 个 chunk：

| Chunk | 内容 | 问题 |
|-------|------|------|
| 1 | `3 系统架构` | 只有标题，无检索价值 |
| 2 | `3.1 后端设计` | 只有标题，无检索价值 |
| 3 | `3.1.1 服务层\n服务层采用分层架构...` | 正常，但丢失了上级标题上下文 |

这是 `MarkdownNodeParser` 的已知缺陷（LlamaIndex GitHub Issue #6711、#17599、#16780）。

**上下文丢失问题**：即使内容正常的 chunk，也缺少祖先标题的上下文。一个包含"超时时间为 30 秒"的 chunk，如果没有"系统架构 > API 网关 > 限流策略"的上下文，检索时几乎无法精确匹配。

---

## 二、业界切分策略全景调研

### 2.1 策略分类与对比

#### 2.1.1 递归字符分割 (Recursive Character Splitting)

**原理**：使用分隔符层级列表（`\n\n` → `\n` → `。` → ` ` → `""`），从大到小依次尝试拆分。

**代表实现**：LangChain `RecursiveCharacterTextSplitter`

**优势**：
- 实现简单，无外部依赖
- Chroma Research 评测中表现"consistently well across metrics"

**劣势**：
- 内容无关——忽略语义和结构边界
- 可能从句子中间、段落中间任意位置切断
- 不同格式需要不同的分隔符配置

**适用场景**：无结构纯文本的兜底方案；结构切分后的溢出二次拆分。

#### 2.1.2 Markdown 结构感知分割

**原理**：解析 Markdown 结构（标题、代码块、列表、表格），在结构边界处拆分，保持结构元素完整。

**代表实现**：
- LlamaIndex `MarkdownNodeParser`
- LangChain `MarkdownHeaderTextSplitter`
- Docling `HierarchicalChunker`
- Dify Advanced Markdown Chunker

**优势**：
- 保留文档语义和作者的逻辑组织
- 生成的 chunk 与人类组织信息的方式一致
- 代码块、表格、列表保持完整

**劣势**：
- 连续标题空块问题（本报告核心问题）
- chunk 大小高度不均匀（一个 section 可能 10 token 或 5000 token）
- 需要两阶段方案：结构拆分 + 溢出保护

**适用场景**：结构化文档、技术手册、API 文档、知识库。Stack Overflow Blog 称其为"对有清晰标题层级的文档的最大单项改进"。

#### 2.1.3 语义切分 (Semantic Chunking)

**原理**：对每个句子做 embedding，在连续句子间余弦相似度下降处切分。

**代表实现**：
- LangChain `SemanticChunker`（支持百分位、标准差、四分位距阈值）
- Chonkie `SemanticChunker` / `SDPMChunker`（语义双通道合并）
- Max-Min Semantic Chunking（Springer 2025 论文，将切分建模为 embedding 空间的约束聚类）

**优势**：
- 能捕捉结构线索遗漏的主题转换
- 对无标题的非结构化文本效果好
- Chroma 评测中 recall 比 naive 方法提升约 9%

**劣势**：
- 入库时需要对每个句子做 embedding（大规模语料成本高）
- 对 embedding 模型选择敏感
- 忽略结构线索（代码块与相邻段落可能有相似 embedding）
- **NAACL 2025 论文** "Is Semantic Chunking Worth the Computational Cost?" 发现：在非合成数据集上，固定 200 词 chunk 的表现与语义切分持平甚至更好

**适用场景**：叙事性文档、混合主题页面、无清晰结构标记的内容。**不推荐**作为结构化 Markdown 文档的主策略。

#### 2.1.4 滑动窗口 (Sliding Window with Overlap)

**原理**：固定大小窗口以小于窗口的步长滑过文本，产生重叠 chunk。

**优势**：
- 防止边界处信息丢失
- 实现最简单

**劣势**：
- 存储增量与重叠比例成正比
- 索引中存在冗余信息
- Chroma Research 发现去掉 overlap 反而使 IoU 提升 2-3 个百分点
- 2026 年一项使用 SPLADE 检索的分析发现 overlap 没有可测量的收益

**适用场景**：均质内容（新闻、社交媒体帖子）。**不推荐**作为结构化 Markdown 的主策略。

#### 2.1.5 Late Chunking（延迟切分）

**原理**：先将整篇文档通过长上下文 Transformer 模型 embedding，再在 token 级别按 chunk 边界做 mean pooling。

**论文**：Jina AI, arXiv:2409.04701

**优势**：
- 每个 chunk embedding 自然包含全文上下文
- 无额外存储开销
- 不需要 LLM 调用

**劣势**：
- 需要长上下文 embedding 模型（Jina v2/v3，8192+ token 上下文）
- 需要模型暴露 token 级别 embedding，SiliconFlow API 不支持
- 技术较新，生产环境经验有限

**本项目适用性**：**不适用**。项目使用 Qwen3-Embedding-4B via SiliconFlow API，无法获取 token 级别 embedding。

#### 2.1.6 命题切分 (Proposition / Atomic Chunking)

**原理**：使用 LLM 将文本分解为原子化的事实命题——每个命题是一个自包含、最小化、有上下文的陈述。

**论文**：Dense X Retrieval (EMNLP 2024)

**优势**：
- 精确度显著优于段落级检索
- 所有检索预算下 recall 都更高

**劣势**：
- 每个段落需要 LLM 调用（大规模成本高）
- 叙事流被破坏——答案"事实正确但碎片化"
- 临床决策支持研究证实了碎片化问题

**本项目适用性**：**不适用**。本项目定位为纯检索中间件，不含 LLM。

#### 2.1.7 Agentic / LLM 驱动切分

**原理**：AI Agent 分析每篇文档，动态决定最佳切分策略。

**代表实现**：Chonkie `SlumberChunker`；Chroma LLMChunker (GPT-4o) 在评测中 recall 达 91.9%

**优势**：质量天花板最高；能适应异构文档集合

**劣势**：最贵（每篇文档需 LLM 调用）；最慢；不确定性

**本项目适用性**：**不适用**。同上，不含 LLM。

#### 2.1.8 Anthropic Contextual Retrieval（上下文检索）

**原理**：使用 LLM 为每个 chunk 生成一段简短的文档级上下文摘要，前缀注入到 chunk 正文中。

**Prompt 模板**：
```
<document>{{WHOLE_DOCUMENT}}</document>
Here is the chunk we want to situate within the whole document
<chunk>{{CHUNK_CONTENT}}</chunk>
Please give a short succinct context to situate this chunk within
the overall document for the purposes of improving search retrieval.
```

**效果数据**：
- 上下文 Embedding 单独使用：检索失败率降低 **35%**
- 上下文 Embedding + 上下文 BM25：降低 **49%**
- 加上 Reranking：降低 **67%**（失败率从 5.7% 降至 1.9%）

**成本**：使用 prompt caching 约 $1.02 / 百万 document tokens

**本项目适用性**：**不适用**。需要 LLM 调用。但其思路（将上下文注入 chunk 正文）可以通过标题前缀注入来部分实现，无需 LLM。

### 2.2 策略总结矩阵

| 策略 | 检索质量 | 成本 | 速度 | 结构化文档 | 非结构化文档 | 本项目适用 |
|------|---------|------|------|-----------|-------------|-----------|
| 递归字符分割 | 中 | 极低 | 极快 | 差 | 中 | 仅作溢出兜底 |
| Markdown 结构感知 | 高 | 低 | 快 | 优秀 | N/A | **主策略** |
| 语义切分 | 高 | 中 | 中 | 中 | 高 | 不推荐主策略 |
| 滑动窗口 | 中低 | 低 | 快 | 差 | 中 | 不推荐 |
| Late Chunking | 高 | 低 | 中 | 高 | 高 | 不兼容 |
| 命题切分 | 极高精度 | 极高 | 慢 | 中 | 高 | 不适用(需LLM) |
| Agentic 切分 | 最高 | 极高 | 极慢 | 优秀 | 优秀 | 不适用(需LLM) |
| 上下文检索 | 极高 | 高 | 慢 | 高 | 高 | 不适用(需LLM) |

---

## 三、框架实现对比

### 3.1 LlamaIndex MarkdownNodeParser

**源码**：`llama_index/core/node_parser/file/markdown.py`

**工作原理**：逐行遍历，用正则 `r"^(#+)\s(.*)"` 检测标题。维护 `header_stack: List[tuple[int, str]]` 跟踪标题层级。遇到新标题时，flush 已累积的 `current_section` 为 `TextNode`。

**已知问题**：
- Issue #6711：`markdown_to_tups` 中 `if current_text == "" or None: continue` 逻辑导致空内容标题被丢弃
- Issue #17599：标题层级跳跃（H1 直接到 H3）导致 `header_path` 错误
- Issue #17965：默认分隔符 `/` 与标题中的正斜杠冲突
- Issue #16780：标题文本同时出现在 metadata 和 text content 中，导致 embedding 重复
- Issue #17650：无法控制最大 chunk 大小

**结论**：存在多个已知缺陷，不适合直接用于生产环境。

### 3.2 LangChain MarkdownHeaderTextSplitter

**核心差异**：将各级标题作为独立 metadata 字段传播：

```python
# 输出示例
Document(
    page_content='实际内容...',
    metadata={'Header 1': 'Foo', 'Header 2': 'Bar', 'Header 3': 'Boo'}
)
```

`aggregate_lines_to_chunks` 方法将共享相同 metadata 的连续行合并为单个 chunk，可减少碎片化。

**对比**：

| 特性 | LangChain | LlamaIndex |
|------|-----------|------------|
| 上下文传播 | 标题作为独立 metadata 字段 | 标题作为路径字符串 |
| 连续标题处理 | 合并相同 metadata 的行；空 section 仍可能出现 | 产出独立的空节点 |
| 标题剥离 | 可配置 `strip_headers` 参数 | 标题默认包含在文本中 |
| 最大 chunk 大小 | 无内置控制；需两阶段 pipeline | 无内置控制 |

**推荐的两阶段模式**：

```python
# 阶段一：按标题拆分，获取 metadata
md_docs = md_splitter.split_text(markdown_text)

# 阶段二：用 split_documents()（非 split_text()）对长 section 二次拆分
# 这样阶段一的标题 metadata 会自动保留到每个子 chunk
final_docs = text_splitter.split_documents(md_docs)
```

**局限**：标题仅存于 metadata 中，embedding 模型看不到标题上下文——需要额外步骤将标题注入正文。

### 3.3 Docling HierarchicalChunker / HybridChunker

**来源**：IBM 开源项目（42,000+ stars）

**原理**：文档解析后得到带类型的元素（Title、NarrativeText、Table、ListItem 等），然后按元素类型和层级进行分块。`HybridChunker`（docling 2.9.0+）在层级切分基础上增加了 tokenization 感知的精细化——智能拆分过大块、合并过小块，同时保留文档结构和元数据。

**优势**：对复杂文档（PDF 含表格、图片）的处理最为完善

**局限**：依赖较重；本项目已将所有文档转为 Markdown，用 Docling 有些过度

### 3.4 Chonkie

**来源**：专用 RAG 切分库（MIT License, 2024）

**特色**：9 种切分策略（Token, Word, Sentence, Recursive, Semantic, SDPM, Late, Code, Neural）。支持 `recipe="markdown"` 使递归切分器使用 Markdown 特定分隔符。C 扩展实现，性能优异（33x 更快的 token 切分）。

**局限**：对连续标题问题没有专门处理；引入额外依赖。

### 3.5 md2chunks (Verloop)

**来源**：专注于"上下文丰富的 Markdown 切分"的轻量库

**特色**：每个 chunk 自动携带来自父标题的层级上下文。灵感来自 LlamaIndex 的 `TextNode` 结构，但专为 Markdown 设计。

---

## 四、关键技术细节

### 4.1 标题上下文注入策略

| 策略 | 描述 | 优势 | 劣势 |
|------|------|------|------|
| **前缀注入正文** | 将 `[架构 > 后端 > 服务层]` 注入 chunk 正文开头 | embedding 模型直接看到上下文；实现简单 | 增加 chunk token 数 |
| 仅 metadata 存储 | `{"header_path": "架构 > 后端 > 服务层"}` | 正文干净；可用于过滤 | embedding 模型看不到；检索质量依赖 metadata 过滤 |
| 正文 + metadata 双写 | 两者结合 | 检索质量最好；过滤灵活 | token 开销最大 |
| 仅注入直接父标题 | 只前缀紧邻的父标题 | token 节省 | 深层嵌套时上下文不完整 |

**推荐**：**正文 + metadata 双写**。Qwen3-Embedding-4B 支持 8192 token 上下文，标题前缀约 50-100 token 的开销完全可接受。Anthropic 的 Contextual Retrieval 研究证实，将上下文信息写入 chunk 正文对检索质量的提升是显著的。

### 4.2 Chunk 大小研究

#### 按查询类型（arXiv 多数据集分析，2025.05）

| 查询类型 | 最优大小 | 证据 |
|---------|---------|------|
| 事实查询（人名、日期、实体） | 128-256 tokens | SQuAD: 64-token chunk recall@1 = 64.1% |
| 实体密集型问题 | 256-512 tokens | NewsQA: 512 token 时 recall@1 峰值 55.9% |
| 分析/推理型 | 512-1024 tokens | NarrativeQA: recall@1 从 4.2%(64t) 升至 10.7%(1024t) |
| 技术领域 | 400-512 tokens | TechQA: recall@1 从 16.5%(128t) 升至 61.3%(512t) |

#### 按 Embedding 模型

| 模型 | 特点 |
|------|------|
| BERT 系列 | 硬限制 512 tokens |
| Stella | 较大 chunk (512-1024) 时 recall 提升 5-8% |
| Qwen3-Embedding-4B | 支持最大 32K tokens，推荐 max_length=8192 |

#### 中文特殊考量

中文平均 token 比率约为英文的 **1.76 倍**。512 token 的中文 chunk 约含 **290 个汉字**的实际内容（vs 英文约 380 词）。加上标题前缀开销 ~50-100 字符，有效内容约 200-250 个汉字。

**本项目建议**：目标 chunk 大小 **400-512 tokens**，与技术文档最优范围对齐。

### 4.3 Overlap 策略研究

| 场景 | 是否需要 Overlap | 原因 |
|------|-----------------|------|
| 结构感知主拆分 | **不需要** | chunk 已遵循自然文档边界 |
| 语义切分 | **不需要** | 边界选在主题转换处 |
| 溢出二次拆分 | **需要 (10-15%)** | 句子拆分可能切断跨句引用 |
| 固定大小兜底 | **需要 (10-20%)** | 无语义边界保障 |

Chroma Research 发现去掉 overlap 使 IoU 提升 2-3 个百分点。FinanceBench 评测中 1024-token + 15% overlap 比 512 无 overlap 准确率高 22%。

**本项目建议**：结构切分阶段无 overlap；溢出拆分阶段 10% overlap。

### 4.4 原子元素保护

#### 表格

- **原则**：永远不从表格中间切断
- **策略**：表格作为原子单元保留。若超过 chunk_size，按行组拆分，每组保留表头行
- 参考：Docling 和 Dify Advanced Markdown Chunker 的做法

#### 代码块

- **原则**：永远不在 ` ``` ` 围栏内部切断
- **策略**：代码块作为原子单元。超大代码块按空行或函数边界拆分，保留语言标签
- 参考：LlamaIndex 已跟踪三反引号防止解析内部标题

#### 列表

- **原则**：尽量保持列表完整
- **策略**：超大列表按顶级列表项拆分，保留列表引导上下文

### 4.5 中文分句感知

中文使用不同的句末标点，切分器必须显式处理：

```
分隔符优先级（从大到小）：
\n\n  →  \n  →  。  →  ．  →  ！  →  ？  →  ；  →  ，  →  、  →  .  →  !  →  ?  →  " "  →  ""
```

**关键警告**：纯 token 级别的分割器可能在**汉字中间**切断（因为一个汉字可能是多个 BPE token），产生不可读的 Unicode 碎片。必须使用字符级别的分隔符查找 + token 级别的大小度量。

---

## 五、最终技术选型

### 5.1 方案决策

**选型：自定义树解析器 + CJK 感知溢出保护**

| 备选方案 | 决策 | 理由 |
|---------|------|------|
| **自定义树解析器** | **采用** | 完全控制；根治连续标题问题；~150 行代码；无新依赖 |
| LangChain MarkdownHeaderTextSplitter | 不采用 | 引入新生态依赖；标题仅在 metadata，embedding 看不到 |
| Chonkie RecursiveChunker | 不采用 | 对连续标题问题无专门处理；增加依赖 |
| Docling HybridChunker | 不采用 | 依赖过重；本项目已转 Markdown，Docling 过度 |
| 语义切分 | 不采用 | 入库成本高；NAACL 2025 证明对结构化文档收益不明显 |
| Late Chunking | 不适用 | 需要 Jina 模型，SiliconFlow API 不兼容 |
| 命题/Agentic/上下文检索 | 不适用 | 均需要 LLM 调用，本项目无 LLM |

### 5.2 架构设计

```
Markdown 文本
    │
    ▼
┌────────────────────────────┐
│  阶段一：树解析             │
│  解析为标题树结构            │
│  Node{header, level,       │
│       content, children}   │
└────────────┬───────────────┘
             │
             ▼
┌────────────────────────────┐
│  阶段二：叶子节点序列化      │
│  只在有实际内容的节点生成     │
│  chunk，祖先标题作为前缀     │
│  注入 chunk 正文            │
│                            │
│  输入:                      │
│    ## 3 系统架构             │
│    ### 3.1 后端设计          │
│    #### 3.1.1 服务层         │
│    服务层采用分层架构...      │
│                            │
│  输出:                      │
│    [系统架构 > 后端设计 >    │
│     服务层]                 │
│    服务层采用分层架构...      │
└────────────┬───────────────┘
             │
             ▼
┌────────────────────────────┐
│  阶段三：原子元素保护        │
│  表格、代码块、列表          │
│  标记为原子单元，不可切断     │
└────────────┬───────────────┘
             │
             ▼
┌────────────────────────────┐
│  阶段四：溢出保护            │
│  超过 chunk_size 的块        │
│  用 CJK 感知句子分割器       │
│  二次拆分 (10% overlap)     │
│  标题前缀自动继承到子块      │
└────────────┬───────────────┘
             │
             ▼
┌────────────────────────────┐
│  阶段五：元数据补全          │
│  chunk_index / header_path │
│  header_level /content_type│
└────────────────────────────┘
```

### 5.3 输出示例

**输入文档**：

```markdown
## 3 系统架构
### 3.1 后端设计
#### 3.1.1 服务层
服务层采用分层架构，包括 API 层、业务逻辑层和数据访问层。
#### 3.1.2 数据层
数据层使用 PostgreSQL 作为主数据库，Redis 作为缓存。
### 3.2 前端设计
前端采用 React + TypeScript 技术栈。
```

**输出 chunks**：

| # | 正文内容 | header_path | content_type |
|---|---------|-------------|-------------|
| 0 | `[系统架构 > 后端设计 > 服务层]\n\n服务层采用分层架构，包括 API 层、业务逻辑层和数据访问层。` | `系统架构 > 后端设计 > 服务层` | text |
| 1 | `[系统架构 > 后端设计 > 数据层]\n\n数据层使用 PostgreSQL 作为主数据库，Redis 作为缓存。` | `系统架构 > 后端设计 > 数据层` | text |
| 2 | `[系统架构 > 前端设计]\n\n前端采用 React + TypeScript 技术栈。` | `系统架构 > 前端设计` | text |

**关键特征**：
- `## 3 系统架构` 和 `### 3.1 后端设计` 不再产生空 chunk
- 每个 chunk 的正文开头都有完整的标题层级路径，embedding 模型能直接理解上下文
- `header_path` 同时存入 metadata，支持过滤检索

### 5.4 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `chunk_size` | 512 | 目标 chunk 大小（字符数） |
| `chunk_overlap` | 64 | 溢出拆分时的重叠（仅用于阶段四） |
| `min_chunk_size` | 50 | 低于此阈值的纯标题块触发向下合并 |
| `header_prefix_template` | `[{path}]\n\n` | 标题前缀注入模板 |
| `header_separator` | ` > ` | 标题层级之间的分隔符 |

### 5.5 实施优先级

1. **P0 - 树解析 + 连续标题合并**：根治空块问题
2. **P0 - 标题前缀注入 chunk 正文**：提升 embedding 检索质量
3. **P1 - 代码块和表格原子保护**：防止结构化内容被溢出拆分器切断
4. **P1 - CJK 感知分句**：正确处理中文句子边界
5. **P2 - chunk 大小调优**：在真实查询上做基准测试（256 / 400 / 512 tokens）

---

## 六、参考文献

### 学术论文

- Dense X Retrieval: What Retrieval Granularity Should We Use? (EMNLP 2024) — [arXiv:2312.06648](https://arxiv.org/html/2312.06648v3)
- Late Chunking: Contextual Chunk Embeddings Using Long-Context Embedding Models — [arXiv:2409.04701](https://arxiv.org/abs/2409.04701)
- Rethinking Chunk Size for Long-Document Retrieval: A Multi-Dataset Analysis (2025.05) — [arXiv:2505.21700](https://arxiv.org/html/2505.21700v2)
- The Chunking Paradigm: Recursive Semantic for RAG Optimization (ICNLSP 2025) — [ACL Anthology](https://aclanthology.org/2025.icnlsp-1.15/)
- Is Semantic Chunking Worth the Computational Cost? (NAACL 2025) — [arXiv:2410.13070](https://arxiv.org/abs/2410.13070)
- Max-Min Semantic Chunking of Documents for RAG Application (Springer, 2025) — [Springer Link](https://link.springer.com/article/10.1007/s10791-025-09638-7)
- Contextual Retrieval vs Late Chunking (ECIR 2025 Workshop) — [arXiv:2504.19754](https://arxiv.org/abs/2504.19754)

### 框架文档与源码

- [LlamaIndex MarkdownNodeParser 源码](https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/node_parser/file/markdown.py)
- [LangChain MarkdownHeaderTextSplitter API](https://python.langchain.com/api_reference/text_splitters/markdown/langchain_text_splitters.markdown.MarkdownHeaderTextSplitter.html)
- [Docling Chunking 概念文档](https://docling-project.github.io/docling/concepts/chunking/)
- [Qwen3-Embedding-4B (Hugging Face)](https://huggingface.co/Qwen/Qwen3-Embedding-4B)

### 行业博客与分析

- [Anthropic: Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval)
- [Chroma Research: Evaluating Chunking](https://research.trychroma.com/evaluating-chunking)
- [Stack Overflow: Breaking Up Is Hard to Do — Chunking in RAG](https://stackoverflow.blog/2024/12/27/breaking-up-is-hard-to-do-chunking-in-rag-applications/)
- [Unstructured.io: Chunking for RAG Best Practices](https://unstructured.io/blog/chunking-for-rag-best-practices)
- [Firecrawl: Best Chunking Strategies for RAG](https://www.firecrawl.dev/blog/best-chunking-strategies-rag)

### 开源工具

- [Chonkie — 轻量 RAG 切分库](https://github.com/chonkie-inc/chonkie)
- [md2chunks — 上下文丰富的 Markdown 切分](https://github.com/verloop/md2chunks)
- [Docling — 文档解析与切分](https://github.com/docling-project/docling)
- [Dify Advanced Markdown Chunker](https://github.com/langgenius/dify/discussions/29635)

### LlamaIndex 相关 Issue

- [#6711: Markdown Reader Empty Text Bug](https://github.com/run-llama/llama_index/issues/6711)
- [#17599: Incorrect header_path When Levels Jump](https://github.com/run-llama/llama_index/issues/17599)
- [#17965: header_path Uses Poor Separator](https://github.com/run-llama/llama_index/issues/17965)
- [#16780: Headings Duplicated in Content](https://github.com/run-llama/llama_index/issues/16780)
- [#17650: No Max Chunk Size Control](https://github.com/run-llama/llama_index/issues/17650)
