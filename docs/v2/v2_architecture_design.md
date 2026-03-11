# RAG 检索中台 V2.0 架构设计文档

> **版本**: V2.0.0
> **日期**: 2026-03-03
> **作者**: RAG Platform Team

---

## 1. 版本目标

V2.0 在 V1.0 完整可用的基础上，聚焦以下三个核心升级：

1. **Reranker 动态开关** — 支持在检索请求中实时切换 Reranker 开启/关闭，适配不同延迟敏感度场景
2. **预切分 JSON 上传** — 提供自定义切分入口，用户可在外部完成文档切分后直接上传 JSON，跳过平台内置解析和切分步骤
3. **技术前沿调研** — 系统性调研 PageIndex、Agentic RAG、GraphRAG 等前沿方向，为后续版本规划提供技术储备

---

## 2. 核心功能升级

### 2.1 Reranker 动态开关

**背景**：V1.0 中 Reranker 始终启用，每次检索都会调用 SiliconFlow Reranker API。对于延迟敏感或成本敏感的场景，用户希望跳过 Reranker 直接使用 RRF 融合分数。

**设计要点**：
- `RetrieveRequest` 新增 `enable_reranker: bool = True` 参数
- 关闭时跳过 Reranker API 调用，直接使用 Qdrant RRF 融合分数排序
- `min_score` 行为适配：RRF 分数量级 (~0.01-0.1) 与 Reranker 分数 (0-1) 完全不同，关闭 Reranker 时默认不过滤
- SSE 模式发送 `skipping_reranker` 事件替代 `reranking` 事件
- 前端 Playground 新增 Switch 控件

### 2.2 预切分 JSON 上传

**背景**：部分高级用户（如算法工程师）有自定义切分需求，希望用外部脚本/工具完成切分后直接导入。

**设计要点**：
- 新增 `POST /api/v1/document/upload-chunks` 端点
- 接受 JSON body 包含预切分的 chunks 数组
- 跳过解析和切分步骤，直接进入 embedding → upsert 流程
- Document 模型新增 `is_pre_chunked` 标记
- PipelineWorker 根据标记分发到 PreChunkPipelineService

**JSON 协议格式**：
```json
{
  "knowledge_base_id": "kb_xxx",
  "file_name": "my_document.pdf",
  "chunks": [
    {
      "text": "切片文本内容",
      "header_path": "第一章 > 引言",
      "header_level": 2,
      "content_type": "text",
      "metadata": {}
    }
  ],
  "doc_id": null
}
```

### 2.3 文档归档

V1.0 的 10 个文档迁移至 `docs/v1_archive/`，保持可追溯性。

---

## 3. 架构决策记录

### ADR-001: Reranker 开关的 min_score 行为

**决策**：当 `enable_reranker=False` 且用户未显式指定 `min_score` 时，`effective_min_score = 0.0`（不过滤）。

**理由**：RRF 融合分数的量级 (~0.01-0.1) 远低于 Reranker 分数 (0-1)。使用 Reranker 的默认阈值 (0.1) 会导致所有结果被过滤掉。

### ADR-002: 自定义切分选择预切分 JSON 而非脚本执行

**决策**：采用预切分 JSON 上传方案，不支持用户上传 Python 脚本在服务端执行。

**理由**：
- **安全性**：执行用户上传的脚本存在任意代码执行风险
- **实用性**：能写脚本的用户可在外部预处理后上传 JSON
- **简洁性**：无需沙箱、依赖管理等复杂基础设施
- **向前兼容**：未来可通过 Docker/WASM 沙箱实现插件系统

---

## 4. 未来演进路线

### V2.x — 增量优化
- 增量更新支持（chunk 级别的 diff 更新）
- 多模态 embedding（图片、表格）
- 检索质量评估工具

### V3.0 — 智能化
- Agentic RAG：查询路由、多步反思、工具调用
- GraphRAG：实体关系抽取、图遍历 + 向量检索融合
- 插件系统：Docker/WASM 沙箱执行用户自定义处理逻辑

### V4.0+ — 多模态与规模化
- PageIndex：ColPali/ColQwen 页面级索引
- 长上下文 embedding 模型支持
- 分布式 Qdrant 集群部署
- Self-RAG / Speculative RAG 反思式检索
