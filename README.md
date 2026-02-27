# 生产级多租户 RAG 知识管理平台需求文档 (PRD)

## 一、 产品定位与目标

本项目旨在构建一个企业级的、提供“云服务体验”的 RAG (Retrieval-Augmented Generation) 知识管理系统平台。系统采用**前后端分离架构**，核心定位为内部 AI 应用提供坚实的数据检索基座。

- **前端定位**：面向业务与管理人员，提供多领域知识库（租户）管理、数据清洗状态监控与资产治理的可视化界面。
- **后端定位**：遵循 API-First 设计理念，作为纯粹的知识检索中台运行。**本系统仅专注高精度的 RAG 检索与上下文召回，不包含大语言模型 (LLM) 的对话/问答生成逻辑**，通过标准接口向公司内部其他平台或下游 AI Agent 输出高质量的上下文切片。

## 二、 核心技术栈架构

- **后端语言与框架**：Python 3.10.14，核心 Web 框架采用 FastAPI，侧重高并发 API 响应与完整的 ORM 管理。
- **环境隔离**：依托本地 `conda` 中的环境进行统一管理，你需要创建新的conda环境，并确保 LlamaIndex、Qdrant-Client 等依赖版本的绝对一致性。
- **RAG 核心编排框架**：LlamaIndex (LlamaIndex Core)。
- **向量数据库**：Qdrant。采用本地落盘部署，全量使用其原生的 Dense (稠密) + Sparse (稀疏) 混合检索能力。
- **外部模型依赖**：
  - **Embedding 模型**：用于生成高维语义稠密向量。
  - **稀疏向量模型**：Qdrant 底层需要的词频特征提取模型（如 FastEmbed/BM25）。
  - **Reranker 模型**：云端 Huawei Reranker (Qwen3-Reranker)，用于精排。
  - *(注：无需接入任何对话类 LLM API)*

## 三、 核心功能模块设计

### 3.1 核心一：数据治理 (多源异构数据的“大一统”)

**功能描述**：实现各类非结构化文档的统一清洗与标准化格式转化。支持对知识集增量添加和定点删除。

- **多源输入**：全面支持 PDF、PPTX、DOCX、XLSX、MD、TXT 等格式上传。
- **Markdown-First 转化策略**：摒弃传统粗暴提取纯文本的方式。引入前置版面解析工具（如微软 MarkItDown 或 Docling），将带有复杂排版的 Word 以及包含表格的 PDF/Excel，无损转化为标准的 Markdown (`.md`) 格式。最大程度保留原始文档的树状层级标题和表格二维语义。
- **元数据 (Metadata) 强制注入**：转化过程中，每个文档级对象必须绑定核心标签：
  - `doc_id`：基于文件内容生成的全局唯一哈希值（用于后续增量更新去重）。
  - `file_name`：原始文件名称。
  - `knowledge_base_name` (集 ID)：所属知识领域标识。
  - `upload_timestamp`：入库时间戳。

### 3.2 核心二：文档切分策略算法 (⭐ 核心重中之重)

**功能描述**：基于标准化 Markdown 数据，实施智能切分，保留完整语义块。

- **语义与结构化智能切分 (Semantic/Structural Chunking)**：识别 Markdown 的 Header 层级（如 `#`, `##`）进行基于结构的切块，避免强行按字符数截断导致语义撕裂。*(注：具体算法与参数配置需开展独立调研测试，系统架构需保持该模块的松耦合，以便随时替换优化策略)*。

### 3.3 核心三：双路混合 Embedding 与 Qdrant 向量库构建（rag_demo.py,中在公司环境跑的)

**功能描述**：实现高效的向量入库与多租户数据隔离。

- **多租户隔离**：平台按“知识领域”或“知识集 ID”建立逻辑数据源，在 Qdrant 中动态映射为完全独立的 Collection，确保检索边界清晰。
- **双路异构检索 (Hybrid Search) 支撑**：
  - **稠密向量 (Dense)**：调用云端 Embedding 接口，提取抽象语义特征。
  - **稀疏向量 (Sparse)**：开启 Qdrant 的 `enable_hybrid=True`，依赖本地挂载的 FastEmbed 稀疏模型，将计算下推至数据库底层，实现精准的中文词频与字面量匹配。（需要从HuggingFace 下载一些模型）
- **无冗余增量更新 (Upsert)**：向量入库强依赖 `doc_id` 字典映射。同名或同源文件更新时，系统必须先 Delete 旧节点的向量记录，再 Insert 新的切片，彻底杜绝知识库数据冗余和脏数据干扰。

### 3.4 核心四：检索、精排与上下文综合

**功能描述**：响应查询请求，执行高精度召回与拼装。

- **海选阶段 (Retrieval)**：接收到查询请求后，通过 Qdrant 原生引擎并行执行 Dense + Sparse 检索。利用 Qdrant 内部打分机制合并融合，召回 Top-K (如 K=10) 粗排切片候选集。（rag_demo.py）
- **精排阶段 (Rerank)**：将召回的 Top-K 切片送入 Huawei Reranker (Qwen3-Reranker) 接口。进行 Query 与 Context 的深度交叉注意力计算，重新打分排序，并严格截断至 Top-N (如 N=3)。（rag_demo.py）
- **上下文综合 (Context Synthesis)**：针对精排胜出的 Top-N 切片，通过内部索引逻辑，自动向前/向后提取相邻的原始切片进行“文本滑动窗口拼接”。确保最终返回的信息具有绝对的连贯性和充足的上下文背景。

### 3.5 核心五：原文索引与绝对溯源

**功能描述**：为前端和调用方提供数据来源的绝对可信度证明。

- **溯源透传**：后端 API 的检索响应结果 JSON 中，必须包含标准的 `source_nodes` 数组对象。该对象需完整透传 Metadata（文件名、入库时间、所属知识集等）以及精准对应的切片原文。用于支撑前端界面的“点击高亮查看原文”功能。

## 四、 API 规范与网关高可用设计

**基础规范**：系统作为内部服务，采用轻量级鉴权逻辑。

- **身份与路由标识**：API 请求头或 Body 中需携带 `user_id`（识别调用者身份）和 `knowledge_base_id`（精准路由至对应的 Qdrant Collection，支持不同内部 AI 应用如 WeLink 部门助手的特定知识集调用）。



embedding模型的测试如下：

curl --request POST --url https://api.siliconflow.cn/v1/embeddings --header "Authorization: Bearer sk-oofzqqipefkdxnccrsreklnlxuyvdoycvdwlrqwofcmzetni" --header "Content-Type: application/json" --data "{\"model\": \"Qwen/Qwen3-Embedding-4B\", \"input\": \"测试一下Qwen3的向量化服务是否连通。\"}"

reranker的测试如下：

curl --request POST --url https://api.siliconflow.cn/v1/rerank --header "Authorization: Bearer sk-oofzqqipefkdxnccrsreklnlxuyvdoycvdwlrqwofcmzetni" --header "Content-Type: application/json" --data "{\"model\": \"Qwen/Qwen3-Reranker-4B\", \"query\": \"苹果公司\", \"documents\": [\"我买了一部新手机\", \"今天吃了一个香蕉\", \"乔布斯是伟大的企业家\"]}"

你需要记住url，apikey，然后作为RAG的核心。