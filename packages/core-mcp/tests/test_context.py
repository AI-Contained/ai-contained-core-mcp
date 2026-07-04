import pytest
from assertpy import assert_that
from fastmcp import FastMCP

from ai_contained.core.mcp.context import ProviderContext, ProviderNotLoaded


class FakeProvider:
    """Satisfies the Provider protocol structurally — Context only ever uses it as a dict key here.

    In production a provider is a module; __name__ mimics that for the
    error-message test.
    """

    __name__ = "fake_provider"

    async def provide(self, ctx: ProviderContext) -> None:
        raise AssertionError("Context never calls provide() — loading is the loader's job")


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
            provider = FakeProvider()
            expected = object()
            ctx = make_context()
            ctx.add(provider, expected)
            assert_that(await ctx.ensure(provider)).is_same_as(expected)

        async def it_returns_none_state_without_raising() -> None:
            # None is a real state (most providers share nothing) — present-with-None
            # must be distinct from never-loaded.
            provider = FakeProvider()
            ctx = make_context()
            ctx.add(provider, None)
            assert_that(await ctx.ensure(provider)).is_none()

        async def it_raises_for_a_provider_that_has_not_loaded() -> None:
            ctx = make_context()
            with pytest.raises(ProviderNotLoaded):
                await ctx.ensure(FakeProvider())

        async def it_names_the_missing_provider_in_the_error() -> None:
            ctx = make_context()
            with pytest.raises(ProviderNotLoaded, match="fake_provider"):
                await ctx.ensure(FakeProvider())

    def describe_add() -> None:
        async def it_replaces_an_existing_state() -> None:
            # Last add wins — the loader adds once per provider; tests may
            # re-add to substitute.
            provider = FakeProvider()
            expected = object()
            ctx = make_context()
            ctx.add(provider, object())
            ctx.add(provider, expected)
            assert_that(await ctx.ensure(provider)).is_same_as(expected)

        async def it_tracks_states_per_provider() -> None:
            first, second = FakeProvider(), FakeProvider()
            first_state, second_state = object(), object()
            ctx = make_context()
            ctx.add(first, first_state)
            ctx.add(second, second_state)
            assert_that(await ctx.ensure(first)).is_same_as(first_state)
            assert_that(await ctx.ensure(second)).is_same_as(second_state)
