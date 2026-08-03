import pytest
from assertpy import assert_that
from fastmcp import FastMCP

from ai_contained.core.mcp.context import Provider, ProviderContext, ProviderNotLoaded


def make_provider() -> Provider:
    """A provider is just an async callable; each call returns a distinct one to key states by."""

    async def fake_provider(ctx: ProviderContext) -> None:
        raise AssertionError("the context never calls a provider — loading is the loader's job")

    return fake_provider


def make_context(environ: dict[str, str] | None = None) -> ProviderContext:
    return ProviderContext(FastMCP("test"), environ or {})


def describe_ProviderContext() -> None:
    def it_exposes_the_environ_mapping() -> None:
        ctx = make_context({"COLOR": "off"})
        assert_that(ctx.environ["COLOR"]).is_equal_to("off")

    def it_exposes_the_mcp_server() -> None:
        mcp = FastMCP("test")
        ctx = ProviderContext(mcp, {})
        assert_that(ctx.mcp).is_same_as(mcp)

    def describe_ensure() -> None:
        async def it_returns_the_added_state() -> None:
            provider = make_provider()
            expected = object()
            ctx = make_context()
            ctx.add(provider, expected)
            assert_that(await ctx.ensure(provider)).is_same_as(expected)

        async def it_returns_none_state_without_raising() -> None:
            # None is a real state (most providers share nothing) — present-with-None
            # must be distinct from never-loaded.
            provider = make_provider()
            ctx = make_context()
            ctx.add(provider, None)
            assert_that(await ctx.ensure(provider)).is_none()

        async def it_raises_for_a_provider_that_has_not_loaded() -> None:
            ctx = make_context()
            with pytest.raises(ProviderNotLoaded):
                await ctx.ensure(make_provider())

        async def it_names_the_missing_provider_in_the_error() -> None:
            ctx = make_context()
            with pytest.raises(ProviderNotLoaded, match="fake_provider"):
                await ctx.ensure(make_provider())

    def describe_add() -> None:
        async def it_replaces_an_existing_state() -> None:
            # Last add wins — the loader adds once per provider; tests may
            # re-add to substitute.
            provider = make_provider()
            expected = object()
            ctx = make_context()
            ctx.add(provider, object())
            ctx.add(provider, expected)
            assert_that(await ctx.ensure(provider)).is_same_as(expected)

        async def it_tracks_states_per_provider() -> None:
            first, second = make_provider(), make_provider()
            first_state, second_state = object(), object()
            ctx = make_context()
            ctx.add(first, first_state)
            ctx.add(second, second_state)
            assert_that(await ctx.ensure(first)).is_same_as(first_state)
            assert_that(await ctx.ensure(second)).is_same_as(second_state)
