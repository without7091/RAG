# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Production-grade multi-tenant RAG (Retrieval-Augmented Generation) knowledge management platform. This is an **API-first knowledge retrieval middleware** (检索中台) for internal AI applications. It does **NOT** include LLM conversation/QA generation — it focuses purely on high-precision document retrieval and context synthesis.

- **Backend**: Python 3.10.14 + FastAPI async API service
- **Frontend**: Next.js 14+ (App Router) + TypeScript admin dashboard for data governance and monitoring

## Current State

v1.0.0 — Complete working platform with backend and frontend.

- **Backend**: Fully functional FastAPI service with hybrid search (dense + BM42 sparse), reranker, document upload pipeline, knowledge base CRUD
- **Frontend**: Next.js admin dashboard with knowledge base management, document management, retrieval playground
- **Docs**: API documentation, technical reports

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

### Key API Endpoints (planned)
- `POST /api/v1/kb/create` — Create knowledge base (initializes Qdrant Collection with dual-index)
- `POST /api/v1/document/upload` — Upload documents (async parse → chunk → embed → upsert pipeline)
- `POST /api/v1/retrieve` — Core retrieval: hybrid search → rerank → context synthesis

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
