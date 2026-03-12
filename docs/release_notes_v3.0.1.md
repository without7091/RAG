# RAG v3.0.1 发布说明

> 发布日期：2026-03-12
> 适用范围：MCP Server 缺陷修复（v3.0.0 代码审计）

## 概述

`v3.0.1` 是 MCP 集成（v3.0.0）的补丁版本，修复了代码审计中发现的 5 个缺陷。所有修复集中在 MCP 模块内部，不影响 REST API 和前端。

## 缺陷修复

### 1. MCP 路径重复 — `/mcp/mcp` → `/mcp`

**现象**：MCP 端点实际挂载在 `/mcp/mcp`，而非文档和配置中声明的 `/mcp`。

**原因**：`FastMCP()` 默认 `streamable_http_path="/mcp"`，父应用再将子应用挂载到 `/mcp`，路径叠加导致重复。

**修复**：在 `FastMCP` 构造时显式传入 `streamable_http_path="/"`，使子应用路由在自身根路径，父应用挂载后有效路径为 `/mcp`。

### 2. MCP 请求 500 — "Task group is not initialized"

**现象**：对 MCP 端点发起 HTTP 请求时返回 500，错误信息为 `Task group is not initialized`。

**原因**：MCP 子应用的 ASGI lifespan 未在测试环境中正确初始化，导致 session manager 的 task group 为空。

**修复**：集成测试改用 Starlette `TestClient` 直接测试 MCP 子应用。`TestClient` 会正确管理 ASGI lifespan，触发 task group 初始化。

### 3. MCP Tool Schema 缺少约束

**现象**：`search_knowledge_base` 工具的 JSON Schema 中 `query` 和 `knowledge_base_id` 缺少 `minLength`，`top_n` 缺少 `minimum`，与 REST API 的校验不一致。

**原因**：工具参数使用原生 Python 类型注解，未附带 `Field()` 元数据。

**修复**：使用 `Annotated[str, Field(min_length=1)]` 和 `Annotated[int, Field(ge=1)]` 为参数添加 Schema 约束，MCP 客户端可在调用前进行前端校验。

### 4. MCP 默认值硬编码

**现象**：`search_knowledge_base` 工具的 `top_n` 默认值硬编码为 `5`，忽略配置项 `MCP_DEFAULT_TOP_N`；`enable_reranker` 硬编码为 `True`，忽略 `MCP_DEFAULT_ENABLE_RERANKER`。

**原因**：工具注册时直接使用字面量，未读取 `settings`。

**修复**：在 `_register_tools()` 内部读取 `settings`，将配置值作为参数默认值传入。Schema 中的 `default` 字段会动态反映运行时配置。

### 5. `top_n` 缺少下界校验

**现象**：`search_knowledge_base()` 接受 `top_n=0` 或 `top_n=-1` 不报错，导致 `top_k = effective_top_n * 4` 计算出无意义值传入检索服务。

**修复**：在解析默认值后添加守卫：

```python
if effective_top_n < 1:
    raise ValueError("top_n must be a positive integer (>= 1)")
```

## 变更文件

| 文件 | 变更 |
|------|------|
| `backend/app/mcp/server.py` | 添加 `streamable_http_path="/"`；引入 `Annotated`/`Field`；工具参数使用配置驱动默认值和 Schema 约束 |
| `backend/app/mcp/tools.py` | 添加 `top_n >= 1` 校验守卫 |
| `backend/tests/integration/test_mcp_server.py` | 重写 lifecycle 测试；新增 6 个审计测试用例 |
| `backend/tests/unit/test_mcp_tools.py` | 新增 `top_n` 校验测试用例 |

## 测试与验证

本次版本共 24 个 MCP 相关测试全部通过（18 个既有 + 6 个新增）：

```bash
cd backend && uv run pytest tests/unit/test_mcp_tools.py tests/integration/test_mcp_server.py -v
```

新增测试用例：

- `test_mcp_mount_does_not_duplicate_subpath` — 验证子应用路径不重复
- `test_mcp_http_requests_do_not_fail_with_uninitialized_task_group` — 验证 MCP 请求不会因 task group 未初始化而 500
- `test_search_tool_schema_validates_query_and_top_n` — 验证 Schema 包含 `minLength`/`minimum`
- `test_search_tool_schema_defaults_follow_settings` — 验证 Schema 默认值跟随配置
- `test_rejects_non_positive_top_n[0]` — 验证 `top_n=0` 被拒绝
- `test_rejects_non_positive_top_n[-1]` — 验证 `top_n=-1` 被拒绝

## 升级提示

- 本次修复不涉及数据库结构变更、配置新增或依赖升级；
- 如果之前 MCP 客户端配置的端点为 `http://host:8000/mcp/mcp`，升级后需改回 `http://host:8000/mcp`；
- 已有 REST API 调用不受影响。
