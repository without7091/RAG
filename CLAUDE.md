# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Production-grade multi-tenant RAG (Retrieval-Augmented Generation) knowledge management platform. This is an **API-first knowledge retrieval middleware** (检索中台) for internal AI applications. It does **NOT** include LLM conversation/QA generation — it focuses purely on high-precision document retrieval and context synthesis.

- **Backend**: Python 3.10.14 + FastAPI async API service
- **Frontend**: Next.js 14+ (App Router) + TypeScript admin dashboard for data governance and monitoring

## Current State

v3.0.0 — MCP (Model Context Protocol) integration for AI Agent interoperability.

- **Backend**: FastAPI service with hybrid search, reranker, document pipeline, **MCP Server** (4 Tools, 3 Resources, 2 Prompts) mounted at `/mcp`
- **Frontend**: Next.js admin dashboard with knowledge base management, document management, retrieval playground
- **MCP**: Streamable HTTP transport at `/mcp`, stdio adapter for local development
- **Docs**: V1 docs in `docs/v1_archive/`, V2 docs in `docs/v2/`

## Git & Version Control

**Repository**: https://github.com/without7091/RAG
**Branch**: `main`

### Git Workflow Rules (IMPORTANT)
- **Every significant change must be committed and pushed** — Claude Code should proactively commit after completing a feature, fix, or refactor
- **Commit messages**: Use clear, descriptive messages in the format `<type>: <description>` (e.g., `feat: add document preview`, `fix: retrieval score normalization`, `refactor: extract chunking module`)
- **Before starting work**: Always `git pull` to sync with remote
- **After completing work**: Stage relevant files, commit, and push. Never use `git add -A` blindly — review what's being staged
- **Never commit**: `.env` files, API keys, `__pycache__`, `node_modules`, `.next/`, `qdrant_local_storage/`
- **Tag releases**: Use `git tag -a vX.Y.Z -m "description"` for version milestones
- **When user requests "上库/push/提交"**: Commit all pending changes and push to origin/main

## Technology Stack

### Backend
- **Language/Framework**: Python 3.10.14, FastAPI (fully async with `async/await`)
- **Environment**: Conda for isolation
- **RAG Orchestration**: LlamaIndex Core
- **Vector DB**: Qdrant (local disk storage at `./qdrant_local_storage`)
- **Embedding**: Qwen3-Embedding-4B via SiliconFlow API (`https://api.siliconflow.cn/v1/embeddings`)
- **Reranker**: Qwen3-Reranker-4B via SiliconFlow API (`https://api.siliconflow.cn/v1/rerank`)
- **Sparse Vectors**: FastEmbed (local model, requires HuggingFace download into `FASTEMBED_CACHE_PATH`)
- **Document Parsing**: MarkItDown or Docling for lossless Markdown conversion
- **MCP**: FastMCP (mcp>=1.9.0) for Model Context Protocol server, mounted at `/mcp` as ASGI sub-app

### Frontend
- **Framework**: Next.js 14+ (App Router), TypeScript
- **UI**: Shadcn/UI, Tailwind CSS, Lucide Icons
- **Code Editor**: Monaco Editor (Light Theme)
- **Layout**: Left navigation tree + right workspace, light color scheme

## Architecture

### Core Pipeline
```
Upload → Parse to Markdown → Generate doc_id (content hash) → Chunk (semantic/structural) →
Embed (Dense + Sparse) → Upsert to Qdrant → Query →
Hybrid Retrieve (Top-K) → Rerank (Top-N) → Context Synthesis (adjacent chunks) → Return with source_nodes
```

### Multi-Tenancy
Each knowledge base (`knowledge_base_id`) maps to an independent Qdrant Collection. API requests include `user_id` for caller identity and `knowledge_base_id` for routing.

### Key API Endpoints
- `POST /api/v1/kb/create` — Create knowledge base (initializes Qdrant Collection with dual-index)
- `POST /api/v1/document/upload` — Upload documents (async parse → chunk → embed → upsert pipeline)
- `POST /api/v1/document/upload-chunks` — Upload pre-chunked documents as JSON (skip parse+chunk)
- `POST /api/v1/retrieve` — Core retrieval: hybrid search → rerank (optional) → context synthesis
- `POST /mcp` — MCP Streamable HTTP endpoint (Agent interoperability)

### MCP Server (`/mcp`)
MCP Server is mounted as an ASGI sub-application, sharing the same process and service layer with REST API.

**Tools** (4):
- `list_knowledge_bases` — List all KBs (entry point for Agent discovery)
- `search_knowledge_base` — Hybrid retrieval + rerank in a specified KB
- `get_knowledge_base_detail` — KB info with document list
- `get_platform_stats` — Platform-wide statistics

**Resources** (3):
- `rag://knowledge-bases` — All KBs list (for context injection)
- `rag://knowledge-bases/{kb_id}/info` — Single KB detail
- `rag://stats` — Platform statistics

**Prompts** (2):
- `search_and_answer` — Search + answer workflow
- `cross_kb_search` — Cross-KB search workflow

**Client Configuration** (Claude Desktop / Claude Code / Cursor):
```json
{
  "mcpServers": {
    "rag-knowledge-base": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

### Data Integrity Pattern
Upsert uses delete-before-insert keyed on `doc_id` (content-based hash) to prevent duplicate/stale data.

### Required Metadata on Every Document
- `doc_id`: Content-based unique hash
- `file_name`: Original filename
- `knowledge_base_name`: Knowledge base identifier
- `upload_timestamp`: Ingestion timestamp

## Key Implementation Reference

`rag_demo.py` demonstrates the proven pattern for:
- Configuring LlamaIndex with SiliconFlow's OpenAI-compatible Embedding API
- Setting `Settings.llm = None` (no LLM needed)
- Initializing Qdrant with `enable_hybrid=True` for native dense+sparse search
- Custom `HuaweiReranker` (extends `BaseNodePostprocessor`) calling the SiliconFlow reranker API
- The full retrieve → rerank flow

## Important Constraints

- All FastAPI endpoints must use `async/await` — never block the main thread on external API calls
- The chunking module must remain loosely coupled (strategy may change)
- Supported upload formats: PDF, PPTX, DOCX, XLSX, MD, TXT
- Markdown-First strategy: all documents convert to `.md` preserving heading hierarchy and table semantics before chunking
- Frontend is a data governance tool for admins, not an end-user chat interface
- Retrieval Playground uses SSE for real-time progress streaming
- **Development Methodology**: **Follow TDD (Test-Driven Development) practices.**
