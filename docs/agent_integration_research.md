# RAG 检索中台 Agent 集成调研报告

> **版本**: V1.0
> **日期**: 2026-03-08
> **定位**: 方案设计、技术选型与实现难度评估
> **范围**: MCP Server、OpenAPI Tool Use、Agent SDK 集成、现有 API 改造评估

---

## 目录

- [1. 调研背景与问题定义](#1-调研背景与问题定义)
- [2. Agent 集成技术全景](#2-agent-集成技术全景)
- [3. 方案一：MCP Server（推荐）](#3-方案一mcp-server推荐)
- [4. 方案二：OpenAPI Tool Use（零改造）](#4-方案二openapi-tool-use零改造)
- [5. 方案三：Agent SDK 原生集成](#5-方案三agent-sdk-原生集成)
- [6. 现有系统 Agent 就绪度评估](#6-现有系统-agent-就绪度评估)
- [7. 方案对比与选型建议](#7-方案对比与选型建议)
- [8. 推荐实施路径](#8-推荐实施路径)
- [附录 A：MCP 生态系统支持情况](#附录-amcp-生态系统支持情况)
- [附录 B：关键文件索引](#附录-b关键文件索引)

---

## 1. 调研背景与问题定义

### 1.1 当前定位

本平台定位为**检索中台**（Retrieval Middleware），是 API-first 的知识检索服务，当前主要被**工作流系统**通过 HTTP API 调用。核心接口：

- `POST /api/v1/retrieve` — 混合检索 + Rerank + 上下文合成
- `POST /api/v1/kb/create` — 创建知识库
- `POST /api/v1/document/upload` + `POST /api/v1/document/vectorize` — 文档入库
- `GET /api/v1/stats` — 平台统计

### 1.2 目标问题

将来 AI Agent 需要**自主决策**何时查询知识库、查询哪个知识库、如何组合查询参数。这与当前"工作流调用"的区别在于：

| 维度 | 工作流调用 | Agent 调用 |
|------|-----------|-----------|
| 调用时机 | 预编排、固定节点 | LLM 自主判断 |
| 参数选择 | 硬编码或模板 | LLM 根据上下文动态生成 |
| 结果处理 | 固定后处理逻辑 | LLM 理解结果并决定下一步 |
| 错误处理 | 预定义分支 | LLM 自主重试或换策略 |
| 工具发现 | 无需（已编排好） | Agent 需要知道有哪些工具可用 |

**核心需求**：让 Agent 能够**发现**本平台的能力、**理解**各工具的语义、**调用**并获得结构化结果。

### 1.3 现有系统概况

| 组件 | 技术栈 | 状态 |
|------|--------|------|
| 后端 | Python 3.10 + FastAPI (全异步) | v2.0.0 完备 |
| 向量库 | Qdrant (本地磁盘存储) | 每个 KB 独立 Collection |
| 检索 | 三路混合检索 (Dense + Sparse + BM25) + RRF 融合 + Reranker | 生产就绪 |
| 前端 | Next.js 14+ (Admin Dashboard) | 数据治理工具 |
| 认证 | 无 | 内部中间件定位 |
| MCP/Agent | 无任何实现 | 全部待建 |

---

## 2. Agent 集成技术全景

### 2.1 三种主流集成范式

```
┌─────────────────────────────────────────────────────────┐
│                    Agent 集成范式                         │
├────────────────┬──────────────────┬─────────────────────┤
│  MCP Server    │ OpenAPI Tool Use │ Agent SDK 原生集成    │
│  (标准协议)     │ (零/低改造)       │ (深度集成)            │
├────────────────┼──────────────────┼─────────────────────┤
│ 新建 MCP 服务   │ 复用现有 REST API │ 嵌入 Agent 框架代码   │
│ 包装现有 API    │ 自动生成工具定义   │ 直接调用 Service 层   │
│ 标准化协议通信   │ Agent 自动发现    │ 绕过 HTTP 开销       │
└────────────────┴──────────────────┴─────────────────────┘
```

### 2.2 关键协议/框架

| 技术 | 定位 | 主要客户端 | 传输方式 |
|------|------|-----------|---------|
| **MCP** (Model Context Protocol) | 开放标准协议 | Claude Desktop/Code, VSCode Copilot, Cursor, ChatGPT, 各种 Agent 框架 | stdio / Streamable HTTP |
| **OpenAPI Tool Use** | Claude API / OpenAI API 内置 | 任何支持 function calling 的 LLM | HTTP (通过 Agent 代码调用) |
| **LlamaIndex Agent** | 框架内置 Agent 工具 | LlamaIndex 生态 | 进程内调用 |
| **LangChain Tool** | 框架内置工具抽象 | LangChain 生态 | 进程内/HTTP |

### 2.3 MCP 协议简介

MCP (Model Context Protocol) 是由 Anthropic 发起的**开放标准协议**，解决"AI 应用如何连接外部系统"的问题。类比 USB-C 为电子设备提供了统一接口，MCP 为 AI 应用提供了连接数据源、工具和工作流的标准化方式。

截至 2026 年 3 月，MCP 已获得以下主流客户端支持：Claude Desktop、Claude Code、Claude.ai (Web)、ChatGPT、VSCode Copilot、Cursor、Continue.dev 等。这意味着构建一个 MCP Server，即可被所有这些客户端直接使用。

MCP 提供三类能力原语：

| 能力 | 说明 | 控制方 | 本平台映射 |
|------|------|--------|-----------|
| **Tools** | LLM 可主动调用的函数，带 JSON Schema 输入输出 | Model（LLM 决定何时调用） | `search_knowledge_base`, `list_knowledge_bases` 等 |
| **Resources** | 被动数据源，提供只读上下文信息 | Application（应用决定何时读取） | 知识库列表、文档列表、平台统计 |
| **Prompts** | 预构建的指令模板，引导用户完成特定任务 | User（用户显式触发） | "在指定知识库中搜索"、"跨库检索" 等 |

MCP 支持两种标准传输机制：

- **stdio**：客户端启动 MCP Server 为子进程，通过 stdin/stdout 通信。适用于本地桌面客户端（Claude Desktop, Cursor）。
- **Streamable HTTP**（2025-03-26 规范）：MCP Server 作为独立 HTTP 服务，客户端通过 POST/GET 通信，支持 SSE 流式响应。适用于远程部署、多客户端共享场景。替代了旧版 HTTP+SSE 传输。

---

## 3. 方案一：MCP Server（推荐）

### 3.1 方案概述

在现有 FastAPI 后端之外，新建一个独立的 MCP Server 进程，通过 HTTP 调用后端 API，对外暴露 MCP 标准接口。**后端零改造**。

### 3.2 传输方式选型

| 传输方式 | 架构 | 适用场景 | 本平台评估 |
|---------|------|---------|-----------|
| **stdio** | 客户端启动子进程，通过 stdin/stdout 通信 | 本地桌面客户端（Claude Desktop, Cursor） | 需要新建独立进程，进程内调用后端 API |
| **Streamable HTTP** | 独立 HTTP 服务，客户端通过 POST/GET 通信 | 远程服务、多客户端共享 | **最适合**，可直接部署为独立 HTTP 服务 |

**选型建议**：采用 **Streamable HTTP** 传输为主，同时提供 stdio 适配。原因：
1. 本平台本身就是 HTTP 服务，MCP Server 可直接调用后端 API
2. 支持多个 Agent 客户端同时连接
3. 可独立部署和扩展
4. stdio 模式可同时支持 Claude Desktop 等本地客户端

### 3.3 MCP Tool 设计

基于现有 API 设计 4 个 MCP Tools：

#### Tool 1: `search_knowledge_base`（核心工具）

```python
@mcp.tool()
async def search_knowledge_base(
    query: str,                    # 检索查询
    knowledge_base_id: str,        # 知识库 ID
    top_n: int = 3,                # 返回结果数
    enable_reranker: bool = True,  # 是否启用精排
) -> str:
    """在指定知识库中检索相关内容。

    根据查询语句在知识库中进行混合检索（向量+稀疏+BM25），
    可选精排重排序，返回最相关的文档片段及其来源信息。
    适用于：回答用户问题时需要查找参考资料、验证事实、获取专业知识。
    """
    # 内部调用 POST /api/v1/retrieve (stream=false)
```

- 对应后端：`POST /api/v1/retrieve`（`backend/app/api/v1/retrieve.py:19`）
- 映射逻辑：直接 HTTP 调用，强制 `stream=false`，提取 `source_nodes` 格式化为 Agent 可读文本
- 关键：MCP 层强制设置 `stream: false`，规避 SSE 默认行为

#### Tool 2: `list_knowledge_bases`

```python
@mcp.tool()
async def list_knowledge_bases() -> str:
    """列出所有可用的知识库及其文档数量。

    返回知识库 ID、名称、描述和文档数量。
    适用于：用户询问"有哪些知识库"或需要确定在哪个知识库中检索时调用。
    """
    # 内部调用 GET /api/v1/kb/list
```

- 对应后端：`GET /api/v1/kb/list`（`backend/app/api/v1/kb.py`）

#### Tool 3: `get_knowledge_base_stats`

```python
@mcp.tool()
async def get_knowledge_base_stats() -> str:
    """获取平台整体统计信息。

    返回知识库总数、文档总数、切片总数等汇总信息。
    适用于：用户询问平台数据规模或运行状态时调用。
    """
    # 内部调用 GET /api/v1/stats
```

- 对应后端：`GET /api/v1/stats`（`backend/app/api/v1/stats.py`）

#### Tool 4: `list_documents`（可选）

```python
@mcp.tool()
async def list_documents(knowledge_base_id: str) -> str:
    """列出指定知识库中的所有文档。

    返回文档名称、状态、切片数量等信息。
    适用于：用户需要了解某个知识库包含哪些文档时调用。
    """
    # 内部调用 GET /api/v1/document/list/{kb_id}
```

- 对应后端：`GET /api/v1/document/list/{kb_id}`（`backend/app/api/v1/document.py`）

### 3.4 MCP Resource 设计

Resources 提供被动数据上下文，由 Application 端决定何时读取：

```python
@mcp.resource("rag://knowledge-bases")
async def get_knowledge_bases() -> str:
    """所有知识库的列表"""
    # 调用 GET /api/v1/kb/list

@mcp.resource("rag://stats")
async def get_platform_stats() -> str:
    """平台统计数据"""
    # 调用 GET /api/v1/stats
```

### 3.5 MCP Prompt 设计

Prompts 提供预构建的交互模板，由用户显式触发：

```python
@mcp.prompt()
async def search_and_answer(query: str, knowledge_base_id: str) -> str:
    """在知识库中搜索并回答问题"""
    return f"""请使用 search_knowledge_base 工具在知识库 {knowledge_base_id} 中
    搜索以下问题的相关信息，然后基于搜索结果给出准确回答：

    问题：{query}

    要求：
    1. 先调用检索工具获取相关文档片段
    2. 基于检索结果回答，引用来源文件名
    3. 如果检索结果不足以回答，明确说明
    """
```

### 3.6 实现架构

```
┌──────────────────────────────────────────────────────────┐
│                    Agent 客户端                           │
│  (Claude Desktop / Claude Code / Cursor / 自研 Agent)     │
└──────────────┬───────────────────────────────────────────┘
               │ MCP Protocol (Streamable HTTP / stdio)
               ▼
┌──────────────────────────────────────────────────────────┐
│                  MCP Server (新增)                        │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────────┐  │
│  │   Tools      │ │  Resources   │ │    Prompts       │  │
│  │ search_kb    │ │ kb-list      │ │ search_and_answer│  │
│  │ list_kbs     │ │ stats        │ │                  │  │
│  │ list_docs    │ │              │ │                  │  │
│  │ get_stats    │ │              │ │                  │  │
│  └──────┬──────┘ └──────┬───────┘ └──────────────────┘  │
│         │               │                                │
│         ▼               ▼                                │
│  ┌──────────────────────────────────────────────────┐    │
│  │          HTTP Client (httpx)                     │    │
│  │      调用现有 REST API (localhost:8000)            │    │
│  └──────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
               │ HTTP (内部调用)
               ▼
┌──────────────────────────────────────────────────────────┐
│              现有 FastAPI 后端 (零改造)                     │
│  POST /api/v1/retrieve    GET /api/v1/kb/list            │
│  GET  /api/v1/stats       GET /api/v1/document/list/...  │
└──────────────────────────────────────────────────────────┘
```

**核心设计**：MCP Server 是一个**独立的薄包装层**，不包含任何业务逻辑，仅负责：
1. 暴露 MCP 标准接口（tools/list, tools/call 等）
2. 将 MCP 调用转换为 HTTP 请求发往后端
3. 将后端 JSON 响应格式化为 Agent 友好的文本

### 3.7 实现难度评估

| 维度 | 评估 | 说明 |
|------|------|------|
| **后端改造** | **零改造** | MCP Server 是独立进程，通过 HTTP 调用现有 API |
| **新增代码量** | ~200-400 行 | 一个 Python 文件 + 配置 |
| **核心依赖** | `mcp[cli]` (Python MCP SDK) + `httpx` | 非常轻量 |
| **部署复杂度** | 低 | 独立进程，可与后端同机部署 |
| **测试难度** | 低 | MCP Inspector 官方调试工具可直接测试 |
| **维护成本** | 低 | 后端 API 不变则 MCP Server 无需改动 |

### 3.8 代码实现参考

```python
# rag_mcp_server.py — 完整实现骨架
from mcp.server.fastmcp import FastMCP
import httpx

mcp = FastMCP("rag-knowledge-base")
RAG_API_BASE = "http://localhost:8000/api/v1"

@mcp.tool()
async def search_knowledge_base(
    query: str,
    knowledge_base_id: str,
    top_n: int = 3,
    enable_reranker: bool = True,
) -> str:
    """在指定知识库中检索相关内容。返回最相关的文档片段及来源信息。"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{RAG_API_BASE}/retrieve", json={
            "user_id": "mcp_agent",
            "knowledge_base_id": knowledge_base_id,
            "query": query,
            "top_n": top_n,
            "enable_reranker": enable_reranker,
            "stream": False,  # 关键：Agent 调用必须用 JSON 模式
        }, timeout=60.0)
        resp.raise_for_status()
        data = resp.json()

    # 格式化为 Agent 可读文本
    results = []
    for i, node in enumerate(data["source_nodes"], 1):
        result = f"[结果 {i}] 来源: {node['file_name']}"
        if node.get("header_path"):
            result += f" > {node['header_path']}"
        result += f"\n相关度: {node['score']:.3f}"
        result += f"\n内容: {node['text']}"
        if node.get("context_text"):
            result += f"\n扩展上下文: {node['context_text']}"
        results.append(result)

    if not results:
        return "未找到相关内容。"
    return f"共找到 {len(results)} 条相关结果：\n\n" + "\n\n---\n\n".join(results)

@mcp.tool()
async def list_knowledge_bases() -> str:
    """列出所有可用的知识库及其文档数量。"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{RAG_API_BASE}/kb/list", timeout=10.0)
        resp.raise_for_status()
        data = resp.json()

    if not data["knowledge_bases"]:
        return "当前没有知识库。"

    lines = [f"共 {data['total']} 个知识库：\n"]
    for kb in data["knowledge_bases"]:
        lines.append(
            f"- **{kb['knowledge_base_name']}** (ID: {kb['knowledge_base_id']})"
            f"  文档数: {kb['document_count']}"
            f"  {kb.get('description', '')}"
        )
    return "\n".join(lines)

if __name__ == "__main__":
    mcp.run(transport="stdio")  # 或 mcp.run(transport="streamable-http", port=8001)
```

### 3.9 客户端配置示例

**Claude Desktop / Claude Code** (`claude_desktop_config.json`)：
```json
{
  "mcpServers": {
    "rag-knowledge-base": {
      "command": "uv",
      "args": ["--directory", "D:\\RAG\\mcp_server", "run", "rag_mcp_server.py"]
    }
  }
}
```

**Streamable HTTP 模式**（远程部署）：
```json
{
  "mcpServers": {
    "rag-knowledge-base": {
      "url": "http://your-server:8001/mcp"
    }
  }
}
```

### 3.10 MCP 方案总结

| 优势 | 具体表现 |
|------|---------|
| 后端零改造 | 独立进程，不触碰核心检索逻辑 |
| 一次构建多处复用 | Claude/ChatGPT/VSCode/Cursor 等所有 MCP 客户端自动可用 |
| 行业标准 | 开放协议，生态快速扩张 |
| 渐进式集成 | 先 stdio 验证，再 Streamable HTTP 远程部署 |
| 低维护成本 | 后端 API 不变则 MCP Server 无需改动 |

---

## 4. 方案二：OpenAPI Tool Use（零改造）

### 4.1 原理

Claude API 和 OpenAI API 都支持 **function calling / tool use**，可以直接将 REST API 端点描述为工具定义。Agent 应用层负责：
1. 将 API 端点转换为 tool 定义（JSON Schema）
2. 在 prompt 中注入工具描述
3. 解析 LLM 的 tool_use 响应
4. 执行 HTTP 调用
5. 将结果回传 LLM

### 4.2 实现方式

```python
# 使用 Claude API 的 tool use
import anthropic

client = anthropic.Anthropic()

tools = [
    {
        "name": "search_knowledge_base",
        "description": "在指定知识库中检索相关内容。根据查询语句进行混合检索，返回最相关的文档片段。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "检索查询语句"},
                "knowledge_base_id": {"type": "string", "description": "知识库 ID"},
                "top_n": {"type": "integer", "description": "返回结果数量", "default": 3},
                "enable_reranker": {"type": "boolean", "description": "是否启用精排", "default": True},
            },
            "required": ["query", "knowledge_base_id"],
        },
    },
    {
        "name": "list_knowledge_bases",
        "description": "列出所有可用的知识库，返回 ID、名称、描述和文档数量。",
        "input_schema": {"type": "object", "properties": {}},
    },
]

# Agent 循环
response = client.messages.create(
    model="claude-sonnet-4-20250514",
    tools=tools,
    messages=[{"role": "user", "content": "帮我在产品文档库中搜索退款政策"}],
)

# 处理 tool_use -> 调用后端 API -> 回传结果 -> LLM 生成最终回答
```

### 4.3 优劣势

| 优势 | 劣势 |
|------|------|
| **真正零改造** — 后端无需任何修改 | 需要在 Agent 应用层编写工具定义和调用逻辑 |
| 不依赖 MCP 协议 | 每个 Agent 应用需要重复编写相同的工具定义 |
| 灵活度高，可精细控制 | 缺乏标准化，不同 Agent 框架实现不统一 |
| 适合快速验证 | 无法通过 Claude Desktop 等 MCP 客户端直接使用 |

### 4.4 OpenAPI 自动生成的问题

本平台基于 FastAPI，自动生成 OpenAPI spec（`/openapi.json`）。理论上可以直接用于 Agent 工具发现。但存在以下已知问题（见 `docs/v2_technical_report_04_v3_risk_register_and_recommendations.md`）：

1. **Retrieve 端点 SSE 未表达**：OpenAPI 把 retrieve 描述为 `application/json` 响应，未表达 `stream=true` 时返回 SSE 流的行为
2. **错误码不完整**：仅声明 200/422，缺少 400/404/409/500/502
3. **`stream` 默认值为 `true`**：Agent 不设 `stream: false` 会收到 SSE 流而非 JSON

**如果走 OpenAPI 自动生成方案**，需要修复这些问题（属于 API 规范优化，非结构性改动）。

### 4.5 实现难度评估

| 维度 | 评估 | 说明 |
|------|------|------|
| **后端改造** | **零改造**（可选修复 OpenAPI spec） | 完全在 Agent 应用层实现 |
| **新增代码量** | 取决于 Agent 应用 | 工具定义 ~50 行，调用逻辑 ~100 行 |
| **适用范围** | 仅限 API 级 tool calling | 不支持 MCP 客户端直连 |
| **重复成本** | 每个 Agent 需重写 | 无标准化共享机制 |

---

## 5. 方案三：Agent SDK 原生集成

### 5.1 原理

将 RAG 平台的检索能力直接封装为 Agent 框架的原生工具，在同一进程内调用，绕过 HTTP 开销。

### 5.2 LlamaIndex Agent 集成

项目已依赖 `llama-index-core>=0.12.0`，其 venv 中包含 `FunctionAgent`、`ReactAgent` 等 Agent 类（`backend/.venv/Lib/site-packages/llama_index/core/agent/workflow/`），但当前未使用。

```python
from llama_index.core.agent.workflow import FunctionAgent
from llama_index.core.tools import FunctionTool

# 直接封装 RetrievalService 为 LlamaIndex 工具
async def search_kb(query: str, knowledge_base_id: str) -> str:
    retrieval_service = get_retrieval_service()  # 复用现有依赖注入
    result = await retrieval_service.retrieve(
        request=RetrieveRequest(
            user_id="agent",
            knowledge_base_id=knowledge_base_id,
            query=query,
            stream=False,
        )
    )
    return format_results(result)

search_tool = FunctionTool.from_defaults(fn=search_kb, name="search_knowledge_base")
agent = FunctionAgent(tools=[search_tool], llm=llm)
```

### 5.3 优劣势

| 优势 | 劣势 |
|------|------|
| 零 HTTP 开销，最低延迟 | 紧耦合，Agent 必须运行在同一进程 |
| 可直接访问 Service 层 | 无法被外部 Agent 客户端发现 |
| 利用已有 LlamaIndex 依赖 | 不同 Agent 框架需要不同适配 |
| 适合构建平台自有 Agent 功能 | 部署复杂度增加 |

### 5.4 实现难度评估

| 维度 | 评估 | 说明 |
|------|------|------|
| **后端改造** | **低** | 需要暴露 Service 层的公共接口 |
| **新增代码量** | ~100-200 行 | 工具封装 + Agent 初始化 |
| **架构影响** | 中等 | Agent 和 RAG 在同一进程，需考虑资源隔离 |
| **适用场景** | 平台自有 Agent 功能 | 如 V3.0 的 Agentic RAG |

---

## 6. 现有系统 Agent 就绪度评估

### 6.1 已就绪

| 维度 | 状态 | 说明 |
|------|------|------|
| **JSON 响应格式** | 完备 | Pydantic 强类型，`source_nodes` 含完整溯源信息（text, score, doc_id, file_name, header_path, context_text） |
| **JSON 模式支持** | 可用 | `stream=false` 返回完整 JSON 响应 |
| **REST API 完整** | 覆盖全功能 | KB CRUD + 文档管理 + 检索 + 统计，全部 async |
| **错误响应统一** | 标准化 | `{"detail": "..."}` 格式，HTTP 状态码语义正确 |
| **多知识库隔离** | 原生支持 | 每个 KB 独立 Qdrant Collection |
| **检索参数丰富** | 灵活 | `top_k`, `top_n`, `enable_reranker`, `min_score`, `enable_context_synthesis`, `enable_query_rewrite` 等可调 |

### 6.2 需优化

| 维度 | 问题 | 影响 | 改造量 |
|------|------|------|--------|
| **`stream` 默认值** | 默认 `true`（SSE），Agent 需显式设 `false` | Agent 不设该参数会收到 SSE 流 | 极低（1 行改默认值，或在 MCP 层强制） |
| **OpenAPI spec** | Retrieve 端点的 SSE 模式和错误码未完整表达 | OpenAPI 自动工具生成不准确 | 中等（添加 response model 注解） |
| **无 `request_id`** | 响应中无请求关联 ID | Agent 日志追踪困难 | 低（添加 header 或响应字段） |
| **无认证** | 无 API Key / JWT | 多 Agent 场景无法区分调用者身份 | 中等（添加 middleware） |
| **`user_id` 无实际用途** | 传入但不参与任何业务逻辑 | Agent 标识无法追踪审计 | 低（添加日志记录即可） |

### 6.3 MCP 方案下无需改造的维度

以下维度在 **MCP Server 方案**下完全由 MCP 层处理，后端零改造：

- **工具发现**：MCP Server 的 `tools/list` 协议操作自动暴露所有可用工具
- **工具语义描述**：MCP Tool 的 `description` 和 `inputSchema` 为 LLM 提供调用决策依据
- **参数验证**：MCP SDK 的 JSON Schema 验证在调用前拦截非法参数
- **结果格式化**：MCP Server 层将后端 JSON 响应转换为 Agent 友好的纯文本
- **SSE 规避**：MCP Server 层强制设置 `stream=false`，完全屏蔽 SSE 行为

---

## 7. 方案对比与选型建议

### 7.1 全维度对比

| 维度 | MCP Server | OpenAPI Tool Use | Agent SDK 原生 |
|------|-----------|-----------------|---------------|
| **后端改造量** | 零 | 零 (可选优化 OpenAPI) | 低 |
| **新增代码** | ~300 行独立服务 | ~150 行/每个 Agent | ~200 行 |
| **标准化程度** | ★★★★★ 开放标准 | ★★★ 厂商特定 | ★★ 框架特定 |
| **客户端生态** | Claude/ChatGPT/VSCode/Cursor... | 仅支持 function calling 的 LLM | 仅特定框架 |
| **多 Agent 复用** | ★★★★★ 一次构建多处复用 | ★★ 每个 Agent 需重写 | ★★ 框架绑定 |
| **工具发现** | 自动（MCP 协议内置） | 手动定义 | 手动定义 |
| **远程部署** | Streamable HTTP 原生支持 | REST API 原生支持 | 不支持（同进程） |
| **本地桌面** | stdio 传输支持 | 不支持 | 不支持 |
| **延迟** | 中（HTTP 中转） | 中（HTTP 直调） | 低（进程内） |
| **部署独立性** | ★★★★★ 独立进程 | ★★★★★ 无需部署 | ★★ 耦合 |
| **未来适应性** | ★★★★★ 生态快速扩张 | ★★★ 稳定但有限 | ★★★ 框架演进风险 |

### 7.2 选型建议

**推荐组合**：**MCP Server（主力） + OpenAPI Tool Use（补充）**

```
优先级 1：MCP Server (Streamable HTTP + stdio)
  → 覆盖 Claude Desktop/Code, Cursor, VSCode, ChatGPT 等标准 MCP 客户端
  → 一次构建，所有 MCP 兼容客户端自动可用

优先级 2：OpenAPI Tool Use 模式
  → 为直接使用 Claude API / OpenAI API 的自研 Agent 提供工具定义示例
  → 不需要额外部署，复用现有 API

优先级 3（V3.0 远期）：Agent SDK 原生集成
  → 配合 Agentic RAG 路线，在平台内部实现 Agent 能力
  → 复用 LlamaIndex Agent 组件
```

### 7.3 选型理由

1. **MCP 是行业标准**：已获 Claude、ChatGPT、VSCode Copilot、Cursor 等主流客户端支持，投资回报率最高
2. **零改造后端**：MCP Server 作为独立薄层包装现有 API，不触碰核心检索逻辑，风险极低
3. **渐进式集成**：可以先用 stdio 模式在 Claude Desktop 上验证效果，再部署 Streamable HTTP 服务
4. **与 V3.0 路线兼容**：V3.0 的 Agentic RAG 可以复用 MCP Tool 定义，Agent SDK 原生集成是自然延伸
5. **本平台 API 成熟度高**：现有 JSON 响应格式、多知识库隔离、丰富的检索参数已经天然适合被 Agent 消费

---

## 8. 推荐实施路径

### Phase 1: MCP Server 基础版（后端零改造）

**目标**：让 Claude Desktop/Code 和 Cursor 能直接通过 MCP 使用知识库检索

**工作内容**：
1. 创建 `mcp_server/` 目录
2. 实现 `rag_mcp_server.py`：4 个 Tools + 2 个 Resources + 1 个 Prompt
3. 配置 `pyproject.toml`，依赖 `mcp[cli]` + `httpx`
4. 编写 Claude Desktop 配置文档

**核心文件**：
- `mcp_server/rag_mcp_server.py` — MCP Server 主文件 (~300 行)
- `mcp_server/pyproject.toml` — 独立项目配置

**验证方法**：
1. 使用 MCP Inspector (`npx @modelcontextprotocol/inspector`) 测试工具发现和调用
2. 在 Claude Desktop 中配置并测试自然语言检索
3. 验证所有 4 个 Tools 的输入输出正确性

### Phase 2: Streamable HTTP 部署

**目标**：支持远程 Agent 客户端连接

**工作内容**：
1. 将 MCP Server 切换为 Streamable HTTP 传输
2. 配置 CORS 和基础认证
3. 编写 Docker Compose 配置（MCP Server + 后端一起部署）

### Phase 3: OpenAPI 规范优化（可选）

**目标**：让直接使用 Claude API / OpenAI API 的 Agent 能准确发现工具

**工作内容**：
1. 修复 Retrieve 端点的 OpenAPI 响应描述
2. 添加完整的错误码文档
3. 提供 Tool Use 工具定义示例文档

**涉及文件**：
- `backend/app/api/v1/retrieve.py` — 添加 `responses` 参数到路由装饰器
- `backend/app/schemas/retrieve.py` — 添加错误响应 schema

### Phase 4: V3.0 Agentic RAG（远期）

与现有 V3.0 路线图对齐：
- 在平台内部引入 LlamaIndex Agent，实现查询路由、多步反思
- MCP Tool 定义可直接复用
- Agent SDK 原生集成用于平台内部 Agent 功能

---

## 附录 A：MCP 生态系统支持情况

| 客户端 | MCP 支持 | 传输方式 | 状态 |
|--------|---------|---------|------|
| Claude Desktop | 支持 | stdio | 已发布 |
| Claude Code (CLI) | 支持 | stdio | 已发布 |
| Claude.ai (Web) | 支持 | Connectors | 已发布 |
| ChatGPT | 支持 | Streamable HTTP | 已发布 |
| VSCode Copilot | 支持 | stdio | 已发布 |
| Cursor | 支持 | stdio | 已发布 |
| Continue.dev | 支持 | stdio | 已发布 |

## 附录 B：关键文件索引

| 文件 | 用途 |
|------|------|
| `backend/app/api/v1/retrieve.py` | 检索端点，MCP `search_knowledge_base` 的底层调用目标 |
| `backend/app/api/v1/kb.py` | 知识库 CRUD，MCP `list_knowledge_bases` 的底层调用目标 |
| `backend/app/api/v1/stats.py` | 统计端点，MCP `get_knowledge_base_stats` 的底层调用目标 |
| `backend/app/api/v1/document.py` | 文档管理，MCP `list_documents` 的底层调用目标 |
| `backend/app/schemas/retrieve.py` | Retrieve 请求/响应 Schema（Agent 需理解的核心数据结构） |
| `backend/app/schemas/kb.py` | KB Schema |
| `backend/app/services/retrieval_service.py` | 检索服务核心编排（Agent SDK 原生集成的直接调用目标） |
| `backend/app/config.py` | 配置中心 |
| `backend/app/main.py` | 应用入口，OpenAPI 配置位于此处 |
| `docs/v2_api_integration_guide.md` | 现有 API 集成指南 |
| `docs/v2_technical_report_04_v3_risk_register_and_recommendations.md` | 风险登记（包含 OpenAPI 不完整等问题记录） |
| `docs/rag_evolution_research.md` | RAG 技术演进研究（Agentic RAG 章节与本报告互补） |
