# v2 技术报告（二）：检索链路、可观测性与对外调用要点

## 1. 报告摘要

当前 v2 的检索链路已经从 v1 的“混合检索 + 精排 + 上下文合成”，演进为：

> **查询改写 → fanout 检索 → 候选合并 → 可选重排 → 可选上下文合成 → JSON / SSE 返回**

这个变化有两个直接价值：

- **对调用方更友好**：接口能直接暴露阶段状态、调试信息和最终结果；
- **对平台方更可诊断**：可以看到 query rewrite 是否生效、候选池规模、最终合并路径。

---

## 2. 当前检索接口契约

接口路径：

- `POST /api/v1/retrieve`

核心请求字段：

| 字段 | 必填 | 默认值 | 说明 |
|---|---:|---:|---|
| `user_id` | 是 | 无 | 当前仅做请求字段保留，后端主链路未消费 |
| `knowledge_base_id` | 是 | 无 | 目标知识库 |
| `query` | 是 | 无 | 用户问题 |
| `top_k` | 否 | `20` | 每轮召回规模，范围 `1~100` |
| `top_n` | 否 | `3` | 最终返回条数，范围 `1~50` |
| `min_score` | 否 | `null` | 手工覆盖最小得分阈值 |
| `enable_reranker` | 否 | `true` | 是否开启精排 |
| `enable_context_synthesis` | 否 | `true` | 是否扩展邻近 chunk 上下文 |
| `enable_query_rewrite` | 否 | `false` | 是否开启查询改写 |
| `query_rewrite_debug` | 否 | `false` | 是否返回 query plan / candidate stats |
| `stream` | 否 | `true` | 是否使用 SSE 流式模式 |

核心响应字段：

| 字段 | 说明 |
|---|---|
| `source_nodes` | 最终返回的检索结果列表 |
| `total_candidates` | 进入排序阶段的候选数 |
| `top_k_used` / `top_n_used` | 实际使用参数 |
| `min_score_used` | 实际生效阈值 |
| `enable_reranker_used` | 是否实际启用重排 |
| `enable_context_synthesis_used` | 是否实际启用上下文合成 |
| `debug` | 仅 `query_rewrite_debug=true` 时返回 |

---

## 3. v2 检索执行过程

### 3.1 阶段 1：确定最小得分阈值

当前实现会优先按如下顺序确定 `min_score`：

1. 请求显式传入的 `min_score`
2. 如果启用 reranker，则使用全局配置 `reranker_min_score`
3. 否则退回到 `0.0`

这意味着：

- 开启重排时，系统默认会进行一次低分过滤；
- 调用方如果想完全控制阈值，应该显式传入 `min_score`。

### 3.2 阶段 2：构建 Query Plan

当 `enable_query_rewrite=false` 时：

- 检索直接使用原始 query；
- debug 中的原因会是 `disabled_by_flag`。

当 `enable_query_rewrite=true` 时：

- `QueryRewriteService` 会先规范化 query；
- 根据配置和 query 形态决定 `bypass / expand / decompose`；
- 调用 chat completion 生成：
  - `strategy`
  - `canonical_query`
  - `queries`
- 如果 LLM 失败，会降级回原始 query；
- 如果策略是 `decompose` 且 LLM 没给出子问题，会走启发式拆分。

当前 v2 的 query rewrite 不是“必须成功”的强依赖，而是“失败可退化”的增强模块。

### 3.3 阶段 3：多 query fanout 检索

对 `final_queries` 中的每一个 query，系统都会执行一次完整召回：

1. Dense embedding
2. Sparse embedding
3. BM25 sparse 向量生成
4. 调用 Qdrant `hybrid_search`

Qdrant 侧当前采用：

- `dense`
- `sparse`
- `bm25`

三路 `prefetch`，再用 `RRF` 融合。

### 3.4 阶段 4：候选合并

多 query fanout 结束后，v2 会对候选进行去重与合并：

- 优先以 `doc_id:chunk_index` 作为候选主键；
- 如果缺少这两个字段，则退回到 `text` 的 SHA1；
- 记录每个候选命中了哪些 query；
- 保留最大得分；
- 额外加入很小的 coverage bonus，鼓励“被多个 query 同时命中”的 chunk。

这个合并层是 v2 相比 v1 的重要增强，因为它使“查询改写后的多路召回”能被统一收敛到一个候选池。

### 3.5 阶段 5：确定 rerank 池大小

如果只有一个 query：

- rerank 池大小等于 `top_k`

如果存在多个 query：

- rerank 池大小取 `min(query_rewrite_rerank_pool_size, max(top_k, top_k * query_count))`

这避免了 query rewrite 打开后候选池无限膨胀。

### 3.6 阶段 6：可选重排

当 `enable_reranker=true`：

- 使用原始 query 和候选文本列表调用 Reranker；
- 按 reranker 返回的 `index/score` 重建最终结果。

当 `enable_reranker=false`：

- 直接按合并后的候选得分截断到 `top_n`。

### 3.7 阶段 7：阈值过滤与上下文合成

排序后，v2 会：

1. 使用 `min_score_used` 做最终过滤；
2. 调用 `synthesize_context()`，按 `context_synthesis_window_size` 读取相邻 chunk；
3. 把扩展后的上下文写入 `context_text`。

调用方最终拿到的是：

- `text`：命中的核心 chunk
- `context_text`：经过窗口扩展后的上下文文本

---

## 4. 返回结果的结构含义

### 4.1 `source_nodes`

每个 `source_node` 当前包含：

- `text`
- `score`
- `doc_id`
- `file_name`
- `knowledge_base_id`
- `chunk_index`
- `header_path`
- `context_text`
- `metadata`

其中 `metadata` 不只是原始 payload，还包含 v2 新增的调试维度：

- `matched_queries`
- `query_scores`
- `merge_score`

这对于外部系统做结果解释、检索调优非常有帮助。

### 4.2 `debug`

仅在 `query_rewrite_debug=true` 时返回，分成两部分：

#### `query_plan`

- `enabled`
- `strategy`
- `canonical_query`
- `generated_queries`
- `final_queries`
- `reasons`
- `fallback_used`
- `model`

#### `candidate_stats`

- `query_count`
- `raw_candidate_count`
- `merged_candidate_count`
- `rerank_pool_size`

这使 v2 可以回答以下问题：

- 改写是否真的发生？
- 最终检索用了几个 query？
- fanout 召回后丢掉了多少重复候选？
- 进入 rerank 的池子有多大？

---

## 5. SSE 模式

### 5.1 事件类型

当前流式模式固定使用以下事件：

| 事件名 | 说明 |
|---|---|
| `status` | 阶段进度 |
| `result` | 最终结果 |
| `error` | 流式执行过程中的异常 |

### 5.2 当前状态阶段

可能出现的 `step` 值如下：

- `query_rewrite`（仅启用 query rewrite 时）
- `embedding_query`
- `hybrid_search`
- `reranking` 或 `skipping_reranker`
- `context_synthesis` 或 `skipping_context_synthesis`
- `building_response`

其中 `reranking/skipping_reranker` 事件会附带 `candidates` 字段。

### 5.3 典型事件流

```text
event: status
data: {"step":"query_rewrite"}

event: status
data: {"step":"embedding_query"}

event: status
data: {"step":"hybrid_search"}

event: status
data: {"step":"reranking","candidates":18}

event: status
data: {"step":"context_synthesis"}

event: status
data: {"step":"building_response"}

event: result
data: {...RetrieveResponse...}
```

---

## 6. v2 相比 v1 的检索差异

| 项目 | v1 | v2 |
|---|---|---|
| 查询入口 | 单 query 为主 | 原始 query + canonical query + generated queries fanout |
| 候选合并 | 主要依赖单轮召回排序 | 支持跨 query 去重与合并 |
| 返回结构 | 结果导向 | 结果 + 调试信息 + 运行状态 |
| 前端反馈 | 只能等待结果 | 可逐步展示执行阶段 |
| 降级策略 | 上游失败对链路影响更大 | query rewrite 失败可自动回退到原 query |

需要注意的是：

- v2 没有替换 v1 的混合检索骨干；
- v2 主要增强了“检索前”和“检索后”的可观测与可调优能力。

---

## 7. 对外调用建议

### 7.1 面向系统接入

推荐外部系统优先使用：

- `stream=false`：用于普通服务调用、批处理、网关聚合
- `stream=true`：用于需要实时进度展示的前端或调试工具

### 7.2 参数建议

- 常规问答场景：
  - `top_k=20`
  - `top_n=3`
  - `enable_reranker=true`
  - `enable_context_synthesis=true`
- 结构复杂、复合问题场景：
  - 额外打开 `enable_query_rewrite=true`
  - 联调阶段打开 `query_rewrite_debug=true`
- 高吞吐低延迟场景：
  - 可关闭 `enable_query_rewrite`
  - 也可视情况关闭 `enable_context_synthesis`

### 7.3 对接注意点

- 当前 `stream` 默认值是 `true`，外部服务如果只接受 JSON，必须显式传 `false`；
- `user_id` 当前是保留字段，不参与权限控制与排序；
- 如果调用方要做结果溯源，优先使用 `doc_id + chunk_index + header_path` 组合。

---

## 8. 当前链路的优势与局限

### 优势

- 混合检索骨干成熟；
- query rewrite 失败可降级，不阻断主流程；
- SSE 对调试和前端体验非常友好；
- debug 字段已经具备“检索解释”的雏形。

### 局限

- OpenAPI 对流式模式表达不完整；
- `user_id` 还未真正进入多租户或权限模型；
- SSE 仍缺少心跳、重连建议、事件版本化；
- query rewrite 目前仍是单服务内存缓存，不是分布式共享缓存。

---

## 9. 面向 v3 的建议

v3 如果继续优化检索链路，建议优先做四件事：

1. **补齐契约**：把 JSON 模式与 SSE 模式在 OpenAPI/文档里彻底拆开；
2. **补齐安全**：把 `user_id` 升级为真实身份/租户上下文；
3. **补齐观测**：为每次检索生成 request_id / trace_id；
4. **补齐控制面**：支持 query rewrite、reranker、context synthesis 的策略级开关与限流。

从当前代码状态看，这四项最能把 v2 的检索能力顺利推入 v3 的平台化阶段。
