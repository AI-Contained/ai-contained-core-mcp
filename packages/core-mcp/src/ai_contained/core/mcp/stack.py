"""Stack — the test kernel for AI-Contained providers.

A Stack composes *real* providers through the same ``Context.ensure()``
engine production boot uses. Substitution happens only at true system edges:

- subprocesses  -> ``exec()`` shims (generated fake binaries on PATH)
- the human     -> ``elicit`` (a scripted Elicitor)
- the network   -> in-process ASGI transport (peer identity simulated in
  one documented place: ``ai_contained.trust.testing.loopback``)

Everything between those edges is production code wired by production
``provide()`` functions.

Kernel law — enforced in review, stated here so it is quotable:

1. This module never imports from a provider package and never grows a
   method that names a domain concept (AWS, trust, accounts, ...).
   Domain conveniences are free functions in each provider's own
   ``testing`` module, taking a Stack as their first argument.
2. No assertions, no test base classes, no lifecycle beyond one async
   context manager. Stack is something pytest fixtures *use*, not a
   framework tests are written *in*.
3. ``env`` is construction-time configuration, snapshotted per install() —
   runtime behavior changes go through the exec-shim rules (read at each
   spawn) or the Elicitor, never through env mutation.
"""

from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Self

from fastmcp import FastMCP

from ai_contained.core.mcp.context import Provider
from ai_contained.core.mcp.testing import Elicitor, WrapCallToolResult

# The result type tool calls resolve to. WrapCallToolResult is an internal
# detail of the kernel from the consumer's point of view: construct nothing,
# just read .is_error / .content / .json().
ToolResult = WrapCallToolResult


@dataclass(frozen=True)
class ExecResponse:
    """One scripted response from a fake executable."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0


@dataclass(frozen=True)
class ExecCall:
    """One recorded invocation of a fake executable."""

    argv: list[str] = field(default_factory=list)  # arguments after the program name
    env: dict[str, str] = field(default_factory=dict)  # environment the shim ran with


class ExecShim:
    """A fake executable on the Stack's PATH, configured through a rules file.

    The generated binary reads its rules at *each* invocation, so
    reconfiguring mid-test is deterministic regardless of when any provider
    snapshotted its env. Matching is longest-prefix-wins over argv.
    """

    def returns(self, stdout: str = "", stderr: str = "", exit_code: int = 0) -> None:
        """Set the default response (the empty-prefix rule)."""
        raise NotImplementedError

    def on(self, *argv_prefix: str) -> "ExecShim":
        """Return a view scoped to invocations whose argv starts with ``argv_prefix``.

        ``shim.on("sts", "get-caller-identity").returns(stdout=...)`` adds a
        prefix rule; ``queue()`` on the view scripts a sequence for it.
        """
        raise NotImplementedError

    def queue(self, *responses: ExecResponse) -> None:
        """Script a consumed-in-order sequence of responses (e.g. SSO login flows).

        When the queue is exhausted, matching falls back to the rule's
        ``returns()`` response.
        """
        raise NotImplementedError

    @property
    def calls(self) -> list[ExecCall]:
        """Every invocation so far, in order. Parsed from the shim's call log on access."""
        raise NotImplementedError


class ToolProxy:
    """Callable handle for one MCP tool: ``await proxy(**kwargs) -> ToolResult``.

    Never raises on tool errors (``raise_on_error=False``) — inspect
    ``.is_error`` on the result. Replaces the ``tool_client`` decorator and
    inline ``WrapCallToolResult(**vars(...))`` construction.
    """

    async def __call__(self, **kwargs: Any) -> ToolResult:
        """Call the tool with ``kwargs`` as its arguments."""
        raise NotImplementedError


class StackClient:
    """An MCP client connected to the Stack's server, elicitation wired to ``stack.elicit``."""

    def tool(self, name: str) -> ToolProxy:
        """Return a proxy for the named tool."""
        raise NotImplementedError


class Stack(AbstractAsyncContextManager["Stack"]):
    """One per test: a process-in-miniature running real providers.

    ::

        async with Stack(env={"COLOR": "off"}) as s:
            trust_testing.loopback(s)
            await s.install(trust_server)
            await s.install(aws_secrets)   # ensures trust_server — already installed
            await s.install(trust_client)
            await s.install(aws_cli)       # ensures trust_client — already installed
            async with s.client() as c:
                aws_read = c.tool("aws_read")

    Teardown asserts the Elicitor queue is drained and removes the tmpdir.
    """

    env: dict[str, str]  # starts with PATH=<tmpdir>/bin:...; snapshotted per install()
    mcp: FastMCP
    elicit: Elicitor

    def __init__(self, env: Mapping[str, str] | None = None) -> None:
        """Create an empty stack; ``env`` entries overlay the kernel defaults."""
        raise NotImplementedError

    async def install(self, provider: Provider, env: Mapping[str, str] | None = None) -> object | None:
        """Merge ``env`` into ``self.env``, run ``provider.provide()``, add() its state, return it.

        Same loop step as production load_providers() — install order is
        load order, so install a dependency before its consumer (the
        ProviderNotLoaded error says which one is missing).
        """
        raise NotImplementedError

    def add(self, provider: Provider, state: object | None) -> None:
        """Stand in a hand-built state for ``provider`` — its real ``provide()`` never runs.

        The substitution seam for the rare isolated test; a later install()
        of the same provider would replace it (last add wins).
        """
        raise NotImplementedError

    def write(self, name: str, content: str) -> str:
        """Write ``content`` to ``<tmpdir>/<name>`` and return the absolute path."""
        raise NotImplementedError

    def exec(self, name: str) -> ExecShim:
        """Return the shim for executable ``name``, generating it on the Stack's PATH on first use."""
        raise NotImplementedError

    def client(self) -> AbstractAsyncContextManager[StackClient]:
        """Connect an MCP client to the stack's server (in-process transport)."""
        raise NotImplementedError

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Tear down: assert the Elicitor queue is drained, close clients, remove the tmpdir."""
        raise NotImplementedError
