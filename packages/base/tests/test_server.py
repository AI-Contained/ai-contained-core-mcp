"""Tests for setup() — verifies provider routes and tools are registered."""

import importlib.metadata
from unittest.mock import MagicMock

import pytest
from assertpy import assert_that  # type: ignore[import-untyped]
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from ai_contained.base.server import setup
from ai_contained.core.mcp import ProviderContext


class FakeProvider:
    """A fake provider that exposes one custom route and one MCP tool."""

    name = "fake_provider"

    async def provide(self, ctx: ProviderContext) -> None:
        @ctx.mcp.custom_route("/fake_custom_route", methods=["GET"])
        async def handler(request: Request) -> JSONResponse:
            return JSONResponse({"ok": True})

        @ctx.mcp.tool(name="fake_custom_tool")
        async def tool() -> str:
            return "hello"

    @property
    def entry_point(self) -> MagicMock:
        ep = MagicMock()
        ep.name = self.name
        ep.load.return_value = self.provide
        return ep


def install_providers(monkeypatch: pytest.MonkeyPatch, *providers: FakeProvider) -> None:
    eps = [p.entry_point for p in providers]
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda group=None: eps if group == "ai_contained.provider" else [],
    )
    monkeypatch.delenv("ALLOWED_PROVIDERS", raising=False)
    monkeypatch.delenv("DENIED_PROVIDERS", raising=False)


def describe_setup() -> None:

    async def it_registers_builtin_routes_and_provider_routes_and_tools(
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        install_providers(monkeypatch, FakeProvider())
        mcp = FastMCP("test")

        await setup(mcp)

        routes = [getattr(r, "path", None) for r in mcp.http_app().routes]
        tools = [t.name for t in await mcp.list_tools()]

        assert_that(routes).contains("/health", "/fake_custom_route")
        assert_that(tools).contains("fake_custom_tool")
