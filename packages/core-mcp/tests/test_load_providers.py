import importlib.metadata
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest
from assertpy import assert_that
from fastmcp import FastMCP

from ai_contained.core.mcp import ProviderContext, ProviderNotLoaded, load_providers


class MockProvider:
    def __init__(self, name: str) -> None:
        self.name = name
        self.__name__ = name  # modules have __name__; error messages use it
        self._calls: list[ProviderContext] = []

        async def provide(ctx: ProviderContext) -> None:
            self._calls.append(ctx)

        self.provide = provide

        entry_point = MagicMock()
        entry_point.name = name
        entry_point.load.return_value = self.provide  # entry points reference the callable ("pkg.module:provide")
        self._entry_point: MagicMock = entry_point

    def times_called(self) -> int:
        return len(self._calls)


class Installed:
    """Controls which providers importlib.metadata discovers."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._mp = monkeypatch

    def set_providers(self, *providers: MockProvider) -> None:
        def fake_entry_points(group: str | None = None) -> list[MagicMock]:
            return [provider._entry_point for provider in providers]

        self._mp.setattr(importlib.metadata, "entry_points", fake_entry_points)


@dataclass
class ProviderSet:
    filesystem: MockProvider
    shell: MockProvider
    git: MockProvider


def make_context(environ: dict[str, str] | None = None) -> ProviderContext:
    return ProviderContext(FastMCP("test"), environ or {})


def describe_load_providers() -> None:
    @pytest.fixture
    def installed(monkeypatch: pytest.MonkeyPatch) -> Installed:
        return Installed(monkeypatch)

    @pytest.fixture
    def providers(installed: Installed) -> ProviderSet:
        fs = MockProvider("filesystem")
        shell = MockProvider("shell")
        git = MockProvider("git")
        installed.set_providers(fs, shell, git)
        return ProviderSet(filesystem=fs, shell=shell, git=git)

    def describe_with_no_env_vars() -> None:
        async def it_loads_all_discovered_providers(providers: ProviderSet) -> None:
            await load_providers(make_context())

            assert_that(providers.filesystem.times_called()).is_equal_to(1)
            assert_that(providers.shell.times_called()).is_equal_to(1)
            assert_that(providers.git.times_called()).is_equal_to(1)

    def describe_ALLOWED_PROVIDERS() -> None:
        async def it_loads_only_the_allowed_provider(providers: ProviderSet) -> None:
            await load_providers(make_context({"ALLOWED_PROVIDERS": providers.filesystem.name}))

            assert_that(providers.filesystem.times_called()).is_equal_to(1)
            assert_that(providers.shell.times_called()).is_equal_to(0)
            assert_that(providers.git.times_called()).is_equal_to(0)

        async def it_loads_multiple_allowed_providers(providers: ProviderSet) -> None:
            environ = {"ALLOWED_PROVIDERS": f"{providers.filesystem.name},{providers.shell.name}"}

            await load_providers(make_context(environ))

            assert_that(providers.filesystem.times_called()).is_equal_to(1)
            assert_that(providers.shell.times_called()).is_equal_to(1)
            assert_that(providers.git.times_called()).is_equal_to(0)

        async def it_loads_nothing_when_no_providers_match(providers: ProviderSet) -> None:
            await load_providers(make_context({"ALLOWED_PROVIDERS": "non-existent"}))

            assert_that(providers.filesystem.times_called()).is_equal_to(0)
            assert_that(providers.shell.times_called()).is_equal_to(0)
            assert_that(providers.git.times_called()).is_equal_to(0)

        async def it_is_case_sensitive(providers: ProviderSet) -> None:
            await load_providers(make_context({"ALLOWED_PROVIDERS": "Filesystem"}))

            assert_that(providers.filesystem.times_called()).is_equal_to(0)
            assert_that(providers.shell.times_called()).is_equal_to(0)
            assert_that(providers.git.times_called()).is_equal_to(0)

        async def it_does_not_load_when_name_has_surrounding_whitespace(providers: ProviderSet) -> None:
            await load_providers(make_context({"ALLOWED_PROVIDERS": f" {providers.filesystem.name} "}))

            assert_that(providers.filesystem.times_called()).is_equal_to(0)
            assert_that(providers.shell.times_called()).is_equal_to(0)
            assert_that(providers.git.times_called()).is_equal_to(0)

        async def it_treats_comma_only_value_as_unset(providers: ProviderSet) -> None:
            await load_providers(make_context({"ALLOWED_PROVIDERS": ","}))

            assert_that(providers.filesystem.times_called()).is_equal_to(1)
            assert_that(providers.shell.times_called()).is_equal_to(1)
            assert_that(providers.git.times_called()).is_equal_to(1)

    def describe_DENIED_PROVIDERS() -> None:
        async def it_skips_the_denied_provider(providers: ProviderSet) -> None:
            await load_providers(make_context({"DENIED_PROVIDERS": providers.shell.name}))

            assert_that(providers.filesystem.times_called()).is_equal_to(1)
            assert_that(providers.shell.times_called()).is_equal_to(0)
            assert_that(providers.git.times_called()).is_equal_to(1)

        async def it_skips_multiple_denied_providers(providers: ProviderSet) -> None:
            environ = {"DENIED_PROVIDERS": f"{providers.shell.name},{providers.git.name}"}

            await load_providers(make_context(environ))

            assert_that(providers.filesystem.times_called()).is_equal_to(1)
            assert_that(providers.shell.times_called()).is_equal_to(0)
            assert_that(providers.git.times_called()).is_equal_to(0)

        async def it_loads_all_when_no_providers_match_deny_list(providers: ProviderSet) -> None:
            await load_providers(make_context({"DENIED_PROVIDERS": "non-existent"}))

            assert_that(providers.filesystem.times_called()).is_equal_to(1)
            assert_that(providers.shell.times_called()).is_equal_to(1)
            assert_that(providers.git.times_called()).is_equal_to(1)

    def describe_ALLOWED_and_DENIED_together() -> None:
        async def it_applies_deny_after_allow(providers: ProviderSet) -> None:
            environ = {
                "ALLOWED_PROVIDERS": f"{providers.filesystem.name},{providers.shell.name}",
                "DENIED_PROVIDERS": providers.shell.name,
            }

            await load_providers(make_context(environ))

            assert_that(providers.filesystem.times_called()).is_equal_to(1)
            assert_that(providers.shell.times_called()).is_equal_to(0)
            assert_that(providers.git.times_called()).is_equal_to(0)

    def describe_error_handling() -> None:
        async def it_raises_and_halts_when_provide_fails(installed: Installed) -> None:
            bad = MockProvider("bad")

            async def fail(ctx: ProviderContext) -> None:
                raise RuntimeError("provide failed")

            bad._entry_point.load.return_value = fail
            good = MockProvider("good")
            installed.set_providers(bad, good)

            with pytest.raises(RuntimeError, match="provide failed"):
                await load_providers(make_context())

            assert_that(good.times_called()).is_equal_to(0)

    def describe_the_provide_contract() -> None:
        async def it_passes_the_same_context_to_every_provider(providers: ProviderSet) -> None:
            ctx = make_context({"COLOR": "off"})

            await load_providers(ctx)

            assert_that(providers.filesystem._calls[0]).is_same_as(ctx)
            assert_that(providers.shell._calls[0]).is_same_as(ctx)

        async def it_adds_each_providers_state(installed: Installed) -> None:
            expected = object()
            provider = MockProvider("stateful")

            async def provide(ctx: ProviderContext) -> object:
                return expected

            provider._entry_point.load.return_value = provide
            installed.set_providers(provider)
            ctx = make_context()

            await load_providers(ctx)

            assert_that(await ctx.ensure(provide)).is_same_as(expected)

        async def it_lets_a_later_provider_ensure_an_earlier_one(installed: Installed) -> None:
            dependency = MockProvider("dependency")
            consumer = MockProvider("consumer")
            received: list[object | None] = []

            async def provide(ctx: ProviderContext) -> None:
                received.append(await ctx.ensure(dependency.provide))

            consumer._entry_point.load.return_value = provide
            installed.set_providers(dependency, consumer)

            await load_providers(make_context())

            assert_that(received).is_length(1)

        async def it_loads_regardless_of_discovery_order(installed: Installed) -> None:
            # The actual production bug this guards against: discovery order put the
            # consumer before its dependency. Loading must self-converge via retry,
            # not require the operator to sequence ALLOWED_PROVIDERS correctly.
            dependency = MockProvider("dependency")
            consumer = MockProvider("consumer")
            received: list[object | None] = []

            async def provide(ctx: ProviderContext) -> None:
                received.append(await ctx.ensure(dependency.provide))

            consumer._entry_point.load.return_value = provide
            installed.set_providers(consumer, dependency)  # consumer discovered first

            await load_providers(make_context())

            assert_that(received).is_length(1)
            assert_that(dependency.times_called()).is_equal_to(1)

        async def it_raises_when_a_dependency_is_never_enabled(installed: Installed) -> None:
            # Not a discovery-order problem: the dependency genuinely never loads
            # (e.g. denied), so retrying must not loop forever — it must fail loudly.
            consumer = MockProvider("consumer")
            missing_dependency = MockProvider("missing")

            async def provide(ctx: ProviderContext) -> None:
                await ctx.ensure(missing_dependency.provide)

            consumer._entry_point.load.return_value = provide
            installed.set_providers(consumer)  # missing_dependency never installed/enabled

            with pytest.raises(ProviderNotLoaded):
                await load_providers(make_context())
