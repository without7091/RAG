"""stdio entry point for running the MCP server in local development.

Usage:
    python -m app.mcp.stdio_runner

Claude Desktop configuration:
    {
        "mcpServers": {
            "rag-knowledge-base": {
                "command": "python",
                "args": ["-m", "app.mcp.stdio_runner"],
                "cwd": "D:\\RAG\\backend"
            }
        }
    }
"""

import asyncio
import logging
import os
import sys

# Disable LlamaIndex telemetry for air-gapped environments
os.environ.setdefault("LLAMA_INDEX_DISABLE_TELEMETRY", "true")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)


async def main() -> None:
    from app.db.session import close_db, init_db
    from app.mcp.server import create_mcp_server

    await init_db()
    try:
        mcp = create_mcp_server()
        await mcp.run_stdio_async()
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
