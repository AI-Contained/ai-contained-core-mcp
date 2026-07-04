"""ProviderContext — what a provider is given; ProviderState — what it gives back.

The provider contract
---------------------
Every provider package exposes a single module-level entry point::

    async def provide(ctx: ProviderContext) -> ProviderState | None

A provider's *state* is whatever live objects it shares with dependent
providers (a TrustRegistry, a TrustServer, ...) — exactly what used to live
in module-level singletons. Most providers share nothing and return None.

Loading is a plain loop: load_providers() runs each enabled provider's
provide() in listed order and add()s its state. A provider that depends on
another calls ``await ctx.ensure(other)`` — a lookup, not a load. If the
dependency hasn't loaded yet (not installed, not enabled, or listed after
its consumer), ensure() raises immediately: dependency problems are boot
failures, never first-request surprises.

Rules:

- Parse ``ctx.environ`` into typed config at the top of ``provide()``; pass
  the raw mapping onward only to components that build child-process
  environments. ``os.environ`` is read nowhere except the composition root.
- Wiring-time only: components receive their dependencies by constructor
  and never hold a ProviderContext.
- No module-level mutable state. No test-only parameters.
"""

from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol

from fastmcp import FastMCP

# What a provider shares with its dependents. An alias for readability in
# signatures — each provider returns its own concrete class (or None).
ProviderState = object


class Provider(Protocol):
    """Structural type for a provider: any object (typically a module) with a ``provide`` entry point."""

    provide: Callable[["ProviderContext"], Awaitable[ProviderState | None]]


class ProviderNotLoaded(Exception):
    """ensure() was called for a provider whose state has not been added yet.

    Either the provider is not enabled in this container, or it is listed
    after the provider that depends on it — both are fixed in the
    container's configuration, not in code.
    """


def _name_of(provider: Provider) -> str:
    """Display name for error messages — providers are modules, so __name__ is normally present."""
    return getattr(provider, "__name__", repr(provider))


class ProviderContext:
    """Everything a provider is given at load time: the server, the env, and its dependencies."""

    def __init__(self, mcp: FastMCP, environ: Mapping[str, str]) -> None:
        """Create the context load_providers() (or a test Stack) hands to each provide() call.

        Args:
            mcp: The server providers wire themselves onto. Must not be serving yet.
            environ: The container's launch environment (``os.environ`` in production).

        """
        self.mcp = mcp
        self.environ = environ
        self._states: dict[Provider, ProviderState | None] = {}

    def add(self, provider: Provider, state: ProviderState | None) -> None:
        """Record a provider's state, making it available to ensure().

        Called by load_providers() with each provide() return value, and by
        tests standing in a hand-built state for a provider that shouldn't
        actually load.
        """
        self._states[provider] = state

    async def ensure(self, provider: Provider) -> ProviderState | None:
        """Return ``provider``'s state; raise if it hasn't loaded.

        A lookup, not a load — async only so the contract can absorb a
        different loading strategy later without touching every provider.

        Raises:
            ProviderNotLoaded: no state has been added for ``provider``.

        """
        if provider not in self._states:
            raise ProviderNotLoaded(
                f"{_name_of(provider)} has not loaded — enable it and list it before its dependents"
            )
        return self._states[provider]
