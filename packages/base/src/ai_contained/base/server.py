"""MCP server entry point."""

import argparse
import asyncio
import os

import uvicorn
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from ai_contained.core.mcp import ProviderContext, load_providers


async def setup(mcp: FastMCP) -> None:
    """Register built-in routes and load all installed providers.

    The one place os.environ is read — everything below consumes ctx.environ.

    Must be called before mcp.http_app() — FastMCP silently drops custom_routes
    added after http_app() runs (see tests/test_server.py).
    """

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "healthy"})

    await load_providers(ProviderContext(mcp, os.environ))


async def _serve(host: str, port: int) -> None:
    # Single event loop for setup + serving so loop-bound resources held by
    # providers (e.g. httpx.AsyncClient in trust-client) remain usable for the
    # server's lifetime.
    mcp = FastMCP("ai-contained")
    await setup(mcp)
    server = uvicorn.Server(uvicorn.Config(mcp.http_app(), host=host, port=port, log_level="info"))
    await server.serve()


def main() -> None:
    """Start the MCP HTTP server."""
    parser = argparse.ArgumentParser(description="AI-Contained MCP server")
    parser.add_argument("--host", default=os.getenv("ADDRESS", "0.0.0.0"), help="Address to bind to")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8080")), help="Port to listen on")
    args = parser.parse_args()
    asyncio.run(_serve(args.host, args.port))


if __name__ == "__main__":
    main()
