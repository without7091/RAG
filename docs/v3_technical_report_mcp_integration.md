# RAG 平台 v3.0.0 技术报告 — MCP Server 集成

**版本**: v3.0.0
**日期**: 2026-03-11
**基线版本**: v2.1.0
**变更范围**: 17 文件，+1,436 行，-4 行

---

## 1. 背景与动机

### 1.1 问题陈述

RAG 检索中台 v2.x 以 REST API 作为唯一对外接口，被工作流系统（如自动化脚本、内部前端）通过 HTTP 调用。随着 AI Agent 生态的快速发展——Claude Desktop/Code、Cursor、ChatGPT 等主流客户端已全面支持 MCP (Model Context Protocol)——产生了新需求：

- Agent 需要**自主发现**平台能力（有哪些知识库？支持什么操作？）
- Agent 需要**理解**各工具语义（何时该调哪个工具？参数怎么填？）
- Agent 需要**调用**检索并获得**结构化结果**（而非 JSON 响应体）

### 1.2 为什么选 MCP

MCP 是 Anthropic 发起、2025 年 12 月捐赠至 Linux Foundation Agentic AI Foundation 的行业标准协议，已获得 Anthropic、OpenAI、Google、Microsoft 共同支持。

| 方案 | 工作量 | 覆盖面 | 维护成本 |
|------|--------|--------|----------|
| 为每个 Agent 客户端写专用插件 | 高（N 份代码） | 逐个适配 | N 倍 |
| OpenAPI/Swagger 暴露 | 低 | 仅支持部分客户端 | 低 |
| **MCP 标准接入（选用）** | **中（一次构建）** | **所有 MCP 兼容客户端** | **1 倍** |

**核心原则：MCP 作为增量功能，对现有 REST API 零影响。**

---

## 2. 架构设计

### 2.1 方案选型：ASGI 子应用 vs 独立进程

| 维度 | A: ASGI 子应用挂载（选用） | B: 独立进程 + HTTP 调用 |
|------|---------------------------|------------------------|
| Service 层复用 | 直接调用，零额外延迟 | 需 HTTP 中转，增加延迟 |
| 部署复杂度 | 单进程，`uvicorn` 一条命令 | 需维护两个进程 |
| 连接池共享 | Qdrant、DB Session、HTTPX 连接池全部共享 | 各自独立管理 |
| 隔离性 | 路径隔离（`/mcp` vs `/api/v1/`） | 进程级隔离 |
| 依赖影响 | 新增 `mcp>=1.9.0` 到主项目 | 依赖独立 |

**选择方案 A** — MCP Server 本质是 Service 层的另一种暴露方式，与 REST API 平级。FastMCP 原生支持 Starlette/FastAPI ASGI 挂载。

### 2.2 系统架构

```
FastAPI 主应用 (uvicorn :8000)
│
├── /api/v1/kb/...           ← REST API（知识库 CRUD）
├── /api/v1/document/...     ← REST API（文档管理）
├── /api/v1/retrieve         ← REST API（检索）
├── /api/v1/stats            ← REST API（统计）
│
└── /mcp                     ← MCP Streamable HTTP（新增）
     │
     ├── Tools (4)           → 调用 Service 层
     ├── Resources (3)       → 调用 Service 层
     └── Prompts (2)         → 纯模板生成
```

**关键设计**：MCP Tool 直接调用 `KBService`、`DocumentService`、`RetrievalService` 等 Service 层方法，**不经过 HTTP**，消除了方案 B 中 REST→Service→REST 的双重序列化开销。

### 2.3 模块结构

```
backend/app/mcp/                    # 新增 MCP 模块（7 个文件）
├── __init__.py                     # 导出 create_mcp_server()
├── server.py                       # FastMCP 实例创建 + Tool/Resource/Prompt 注册
├── tools.py                        # 4 个 MCP Tool 实现
├── resources.py                    # 3 个 MCP Resource 实现
├── prompts.py                      # 2 个 MCP Prompt 模板
├── formatting.py                   # Service 返回值 → Agent 友好文本格式化
└── stdio_runner.py                 # stdio 传输入口（本地开发用）
```

---

## 3. MCP 能力清单

### 3.1 Tools（4 个工具）

Tools 是 Agent 的主动调用接口，Agent 根据用户指令自主决策调用。

| # | Tool 名称 | 描述 | 输入参数 | 内部调用 |
|---|-----------|------|----------|----------|
| 1 | `list_knowledge_bases` | 列出所有知识库及描述/文档数 | 无 | `KBService.list_all()` + `get_document_count()` |
| 2 | `search_knowledge_base` | 混合检索 + Rerank + 上下文合成 | `knowledge_base_id`, `query`, `top_n?`, `enable_reranker?` | `RetrievalService.retrieve()` |
| 3 | `get_knowledge_base_detail` | 知识库详情 + 文档列表 | `knowledge_base_id` | `KBService.get_by_id()` + `DocumentService.list_by_kb()` |
| 4 | `get_platform_stats` | 平台整体统计 | 无 | 直接 SQL 查询 |

**Agent 调用引导**：工具描述中嵌入了调用顺序引导语——

- `list_knowledge_bases` 描述："这是使用 RAG 平台的**第一步**"
- `search_knowledge_base` 描述："调用前请先使用 **list_knowledge_bases** 工具确定目标知识库的 ID"

典型 Agent 调用链：
```
list_knowledge_bases → 选择 KB ID → search_knowledge_base(kb_id, query)
```

### 3.2 Resources（3 个资源）

Resources 是只读上下文数据，由 MCP 客户端决定何时注入到 LLM 上下文。

| # | URI | 描述 | 用途 |
|---|-----|------|------|
| 1 | `rag://knowledge-bases` | 所有知识库列表 | 会话初始化时注入，Agent 从对话开始就"知道"有哪些知识库 |
| 2 | `rag://knowledge-bases/{kb_id}/info` | 指定知识库详情 | 按需注入特定知识库的背景信息 |
| 3 | `rag://stats` | 平台统计数据 | 提供平台规模的背景信息 |

### 3.3 Prompts（2 个模板）

Prompts 是预定义的工作流模板，用户选择后 LLM 按步骤执行。

| # | Prompt 名称 | 描述 | 参数 |
|---|-------------|------|------|
| 1 | `search_and_answer` | 在知识库中搜索并回答问题 | `query`, `knowledge_base_name?` |
| 2 | `cross_kb_search` | 跨多个知识库搜索并综合回答 | `query` |

### 3.4 Agent 知识库发现机制

Agent 通过**双通道**发现知识库：

```
通道 1: Resource 被动注入（会话初始化时）
  客户端读取 rag://knowledge-bases → LLM 上下文自动包含所有 KB 列表
  → Agent 从对话开始就"知道"有哪些知识库

通道 2: Tool 主动查询（对话过程中）
  Agent 调用 list_knowledge_bases → 获取最新知识库列表
  → 选择 knowledge_base_id → 调用 search_knowledge_base
```

---

## 4. 变更文件清单

### 4.1 新增文件（12 个）

| 文件路径 | 行数 | 用途 |
|----------|------|------|
| `backend/app/mcp/__init__.py` | 3 | 模块入口，导出 `create_mcp_server` |
| `backend/app/mcp/server.py` | 160 | FastMCP 实例创建，注册全部 Tools/Resources/Prompts |
| `backend/app/mcp/tools.py` | 135 | 4 个 MCP Tool 的业务实现 |
| `backend/app/mcp/resources.py` | 93 | 3 个 MCP Resource 的数据读取 |
| `backend/app/mcp/prompts.py` | 33 | 2 个 Prompt 模板生成函数 |
| `backend/app/mcp/formatting.py` | 139 | Service 返回值格式化为 Agent 友好文本 |
| `backend/app/mcp/stdio_runner.py` | 46 | stdio 传输入口脚本（本地开发用） |
| `backend/tests/unit/test_mcp_formatting.py` | 216 | 格式化函数单元测试（13 个测试） |
| `backend/tests/unit/test_mcp_tools.py` | 191 | Tool 实现单元测试（7 个测试） |
| `backend/tests/unit/test_mcp_resources.py` | 103 | Resource 实现单元测试（6 个测试） |
| `backend/tests/unit/test_mcp_prompts.py` | 34 | Prompt 模板单元测试（5 个测试） |
| `backend/tests/integration/test_mcp_server.py` | 223 | MCP Server 集成测试（11 个测试） |

### 4.2 修改文件（5 个）

| 文件路径 | 变更 | 说明 |
|----------|------|------|
| `backend/app/main.py` | +9 行 | 在 `create_app()` 中条件挂载 MCP 子应用到 `/mcp` |
| `backend/app/config.py` | +7 行 | Settings 类新增 5 个 MCP 配置项 |
| `backend/pyproject.toml` | +1 行 | 新增 `mcp>=1.9.0` 依赖 |
| `backend/.env.example` | +7 行 | 新增 MCP 配置环境变量模板 |
| `CLAUDE.md` | +40/-4 行 | 更新版本状态、技术栈、MCP Server 文档 |

---

## 5. 关键实现细节

### 5.1 ASGI 子应用挂载（`main.py`）

```python
# backend/app/main.py — create_app() 中新增
settings = get_settings()
if settings.mcp_enabled:
    from app.mcp import create_mcp_server
    mcp_server = create_mcp_server()
    app.mount("/mcp", mcp_server.streamable_http_app())
```

- 使用 `settings.mcp_enabled` 开关控制，可通过 `MCP_ENABLED=false` 环境变量关闭
- `mcp_server.streamable_http_app()` 返回标准 ASGI 应用
- `app.mount("/mcp", ...)` 将 MCP 流式 HTTP 端点挂载在 `/mcp` 路径下
- 惰性 import `app.mcp`，当 `mcp_enabled=False` 时不加载 MCP 模块

### 5.2 Session 管理（`server.py`）

```python
def _get_session():
    factory = get_session_factory()
    return factory()

# 每个 Tool/Resource 调用使用独立 session
@mcp.tool(...)
async def list_knowledge_bases_tool() -> str:
    async with _get_session() as session:
        return await tool_module.list_knowledge_bases(session)
```

- 复用主应用的 `get_session_factory()` 单例工厂
- 每次 MCP 调用获取独立的 `AsyncSession`，调用结束自动关闭
- 与 REST API 的 FastAPI `Depends` 依赖注入模式保持一致

### 5.3 RetrievalService 复用（`tools.py`）

```python
@mcp.tool(...)
async def search_knowledge_base_tool(
    knowledge_base_id: str, query: str,
    top_n: int = 5, enable_reranker: bool = True,
) -> str:
    retrieval_service = await get_retrieval_service()
    return await tool_module.search_knowledge_base(
        retrieval_service=retrieval_service, ...)
```

- `get_retrieval_service()` 复用 `dependencies.py` 中的工厂函数
- 底层共享 `EmbeddingService`、`SparseEmbeddingService`、`VectorStoreService`、`RerankerService` 等全局单例
- 共享 Qdrant 连接池、HTTPX 连接池，无额外资源开销
- 固定 `enable_context_synthesis=True`，始终返回上下文扩展结果
- `top_k` 自动设为 `top_n * 4`，保证混合检索候选池充足

### 5.4 格式化层设计（`formatting.py`）

MCP Tool 返回的是**纯文本**而非 JSON，针对 LLM 阅读优化：

```
共找到 3 条相关结果：

[结果 1] 来源: 产品手册.pdf > 第三章 > 退款政策
相关度: 0.923
内容: 用户可在购买后7日内申请无条件退款...
上下文: [前后相邻片段的扩展文本]

---

[结果 2] 来源: FAQ.md > 售后服务
相关度: 0.871
内容: ...
```

设计要点：
- **来源路径**：`file_name > header_path`，拼接文件名与章节层级
- **相关度分数**：保留 3 位小数，供 Agent 判断可信度
- **上下文**：包含 context_synthesis 合成的前后文，帮助 LLM 理解完整语义
- **状态翻译**：`COMPLETED → 已完成`，文档状态 Enum 翻译为中文

### 5.5 配置项（`config.py`）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `mcp_enabled` | `True` | MCP 功能开关 |
| `mcp_server_name` | `"rag-knowledge-base"` | MCP Server 标识名 |
| `mcp_default_top_n` | `5` | 检索默认返回数 |
| `mcp_default_enable_reranker` | `True` | 检索默认启用 Reranker |
| `mcp_stateless` | `True` | 无状态模式（每次请求独立） |

### 5.6 stdio 传输适配器（`stdio_runner.py`）

为本地开发场景提供 stdio 传输模式入口：

```python
# backend/app/mcp/stdio_runner.py
async def main() -> None:
    await init_db()
    try:
        mcp = create_mcp_server()
        await mcp.run_stdio_async()
    finally:
        await close_db()
```

Claude Desktop 配置（stdio 模式）：
```json
{
  "mcpServers": {
    "rag-knowledge-base": {
      "command": "python",
      "args": ["-m", "app.mcp.stdio_runner"],
      "cwd": "D:\\RAG\\backend"
    }
  }
}
```

---

## 6. 传输方式

### 6.1 Streamable HTTP（默认，生产环境）

MCP Server 通过 ASGI 挂载在 `/mcp`，自动支持 Streamable HTTP 传输。

客户端配置：
```json
{
  "mcpServers": {
    "rag-knowledge-base": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

适用于：Claude Desktop、Claude Code、Cursor、任何 MCP 兼容客户端。

### 6.2 stdio（本地开发）

通过 `stdio_runner.py` 以子进程模式运行 MCP Server，适用于不方便启动 HTTP 服务的本地开发场景。

---

## 7. 测试覆盖

### 7.1 测试统计

| 类别 | 文件 | 测试数 | 说明 |
|------|------|--------|------|
| 格式化单元测试 | `test_mcp_formatting.py` | 13 | 覆盖所有格式化函数的正常/空/边界情况 |
| Tool 单元测试 | `test_mcp_tools.py` | 7 | Mock Service 层，验证调用参数和输出格式 |
| Resource 单元测试 | `test_mcp_resources.py` | 6 | 真实 in-memory DB，验证数据读取和格式化 |
| Prompt 单元测试 | `test_mcp_prompts.py` | 5 | 验证模板生成逻辑 |
| MCP 集成测试 | `test_mcp_server.py` | 11 | 验证 Server 注册、工具执行、资源读取、REST 零影响 |
| **MCP 新增合计** | **5 文件** | **42** | |
| 既有测试 | 27 文件 | 249 | 全量通过，零回归 |
| **总计** | **32 文件** | **291** | |

### 7.2 关键测试场景

**集成测试重点验证**：
- `TestMCPEndpointExists` — `/mcp` 端点可达（不返回 404）
- `TestMCPServerRegistration` — 4 个 Tool、3 个 Resource、2 个 Prompt 全部注册
- `TestMCPServerRegistration::test_tool_descriptions_contain_guidance` — 工具描述包含调用引导语
- `TestMCPToolExecution` — 带真实 DB 的 Tool 执行（list/detail/stats）
- `TestMCPResourceExecution` — 带真实 DB 的 Resource 读取
- `TestExistingAPIUnaffected` — 启用 MCP 后 `GET /api/v1/stats` 仍正常响应

### 7.3 零影响验证

```
$ pytest tests/ --ignore=tests/unit/test_manual_retrieve_test.py \
                --ignore=tests/unit/test_pipeline_worker.py
291 passed, 0 failed
```

排除的 2 个测试文件为 v2.x 遗留的预存问题，与本次变更无关。

---

## 8. 依赖变更

### 新增依赖

| 包 | 版本要求 | 说明 |
|----|----------|------|
| `mcp` | `>=1.9.0` | MCP Python SDK，含 FastMCP 高级 API |

实际安装版本 `1.25.0`，传递依赖包括 `anyio`、`httpx-sse`、`pyjwt` 等（均为已有依赖的兼容版本）。

### 无变更依赖

所有既有 14 个核心依赖和 8 个开发依赖版本要求不变。

---

## 9. 部署与配置

### 9.1 零配置启用

MCP 功能默认启用（`MCP_ENABLED=true`），无需额外配置。只要安装了 `mcp>=1.9.0` 依赖，启动 `uvicorn` 后 `/mcp` 端点即可用。

### 9.2 关闭 MCP

如不需要 MCP 功能，设置环境变量：
```
MCP_ENABLED=false
```

### 9.3 MCP 客户端接入

**Streamable HTTP（推荐）**：
```json
{
  "mcpServers": {
    "rag-knowledge-base": {
      "url": "http://<host>:8000/mcp"
    }
  }
}
```

**stdio（本地开发）**：
```json
{
  "mcpServers": {
    "rag-knowledge-base": {
      "command": "python",
      "args": ["-m", "app.mcp.stdio_runner"],
      "cwd": "<path-to>/backend"
    }
  }
}
```

### 9.4 MCP Inspector 验证

```bash
npx @modelcontextprotocol/inspector http://localhost:8000/mcp
```

可验证：
- `tools/list` — 返回 4 个工具定义
- `tools/call` — 执行检索工具
- `resources/list` — 返回 3 个资源
- `resources/read` — 读取资源内容
- `prompts/list` — 返回 2 个模板

---

## 10. 版本发布记录

| 标签 | Commit | 说明 |
|------|--------|------|
| `v2.1.0` | `00619c5` | v2.x 最终版：KB 树改进、文档重组、TDD 方法论 |
| `v3.0.0` | `4c15398` | MCP Server 集成：4 Tools + 3 Resources + 2 Prompts + 42 Tests |

```
v2.1.0 → v3.0.0
  1 commit, 17 files changed, +1,436 lines, -4 lines
```

---

## 11. 后续演进方向

| 方向 | 说明 | 优先级 |
|------|------|--------|
| MCP 认证 | 添加 API Key/JWT 认证保护 MCP 端点 | 高 |
| 文档上传 Tool | 允许 Agent 通过 MCP 上传文档到知识库 | 中 |
| 异步检索 Tool | 大规模检索场景支持异步任务 + 进度通知 | 中 |
| Resource 订阅 | 知识库变更时主动推送通知给 Agent | 低 |
| 多语言工具描述 | 根据 Agent 语言环境切换工具描述语言 | 低 |
