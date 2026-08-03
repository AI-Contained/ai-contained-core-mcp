"""Harness — the test harness for AI-Contained providers.

A Harness composes *real* providers through the same ``ProviderContext``
production ``load_providers()`` uses. Substitution happens only at true
system edges:

- subprocesses  -> ``exec()`` shims (fake binaries on PATH)
- the human     -> ``elicit`` (a scripted Elicitor)
- the network   -> in-process transports (peer identity simulated in one
  documented place: ``raw_client()``)

Everything between those edges is production code wired by production
``provide()`` functions.

Rules for this module — enforced in review:

1. This module never imports from a provider package and never grows a
   method that names a domain concept (AWS, trust, accounts, ...).
   Domain conveniences are free functions in each provider's own
   ``testing`` module, taking a Harness as their first argument.
2. No assertions beyond the Elicitor drain check, no test base classes,
   no lifecycle beyond one async context manager. Harness is something
   pytest fixtures *use*, not a framework tests are written *in*.
3. ``env`` is construction-time configuration — runtime behavior changes
   go through the exec-shim rules (read at each spawn) or the Elicitor,
   never through env mutation.
"""

import json
import os
import shutil
import sys
import tempfile
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any

import httpx
from fastmcp import FastMCP
from fastmcp.client import Client

from ai_contained.core.mcp.context import Environ, Provider, ProviderContext, ProviderState
from ai_contained.core.mcp.testing import Elicitor, WrapCallToolResult

# The result type tool calls resolve to. From the consumer's point of view
# WrapCallToolResult is an internal detail: construct nothing, just read
# .is_error / .content / .json().
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


# The harness's one executable: committed, reviewed source. exec() only
# ever creates symlinks to it — tests never mint executable code on writable
# filesystems, so noexec /tmp (docker's tmpfs default) is fully compatible.
_SHIM_PATH = Path(__file__).parent / "_shim.py"


class ExecShim:
    """A fake executable on the Harness's PATH, configured through a rules file.

    The shim reads its rules at *each* invocation, so reconfiguring mid-test
    is deterministic regardless of when any provider snapshotted its env.
    Matching is longest-prefix-wins over argv.
    """

    def __init__(self, name: str, bin_dir: Path, state_dir: Path, prefix: tuple[str, ...] = ()) -> None:
        """Symlink ``bin_dir/name`` to the committed shim (once per name); views share files via ``on()``."""
        self._name = name
        self._prefix = prefix
        self._rules_path = state_dir / f"{name}.rules.json"
        self._calls_path = state_dir / f"{name}.calls.jsonl"
        self._rules: dict[tuple[str, ...], list[ExecResponse]] = {}

        link = bin_dir / name
        if not link.exists():
            link.symlink_to(_SHIM_PATH)

    def returns(self, *responses: ExecResponse) -> None:
        """Set what this rule answers: responses consumed in order, the last repeating forever.

        ``returns(ExecResponse(stdout="pending", exit_code=1), ExecResponse(stdout="done"))``
        serves "pending" once, then "done" for every call after — the shape of
        polling loops like SSO login. Calling returns() again replaces the
        whole sequence. At least one response is required.
        """
        if not responses:
            raise TypeError("returns() requires at least one ExecResponse")
        self._rules[self._prefix] = list(responses)
        self._flush()

    def on(self, *argv_prefix: str) -> "ExecShim":
        """Return a view scoped to invocations whose argv starts with ``argv_prefix``.

        ``shim.on("sts", "get-caller-identity").returns(...)`` adds a prefix
        rule with its own response sequence.
        """
        view = ExecShim.__new__(ExecShim)
        view._name = self._name
        view._prefix = argv_prefix
        view._rules_path = self._rules_path
        view._calls_path = self._calls_path
        view._rules = self._rules  # shared — all views write the same rule set
        return view

    @property
    def calls(self) -> list[ExecCall]:
        """Every invocation so far, in order. Parsed from the shim's call log on access."""
        if not self._calls_path.exists():
            return []
        records = [json.loads(line) for line in self._calls_path.read_text().splitlines()]
        return [ExecCall(argv=r["argv"], env=r["env"]) for r in records]

    def _flush(self) -> None:
        """Atomically rewrite the rules file — a concurrently spawning shim never sees a partial write."""
        content = json.dumps(
            {"rules": [{"prefix": list(p), "responses": [asdict(r) for r in rs]} for p, rs in self._rules.items()]}
        )
        tmp = self._rules_path.with_suffix(".tmp")
        tmp.write_text(content)
        tmp.replace(self._rules_path)


class ToolProxy:
    """Callable handle for one MCP tool: ``await proxy(**kwargs) -> ToolResult``.

    Never raises on tool errors (``raise_on_error=False``) — inspect
    ``.is_error`` on the result. Replaces the ``tool_client`` decorator and
    inline ``WrapCallToolResult(**vars(...))`` construction.
    """

    def __init__(self, client: Client[Any], name: str) -> None:
        """Bind the proxy to a connected client and a tool name."""
        self._client = client
        self._name = name

    async def __call__(self, **kwargs: Any) -> ToolResult:
        """Call the tool with ``kwargs`` as its arguments."""
        result = await self._client.call_tool(self._name, kwargs, raise_on_error=False)
        return WrapCallToolResult(**vars(result))


class HarnessClient:
    """An MCP client connected to the Harness's server, elicitation wired to ``harness.elicit``."""

    def __init__(self, client: Client[Any]) -> None:
        """Wrap a connected fastmcp client."""
        self._client = client

    def tool(self, name: str) -> ToolProxy:
        """Return a proxy for the named tool."""
        return ToolProxy(self._client, name)


class Harness(AbstractAsyncContextManager["Harness"]):
    """One per test: a process-in-miniature running real providers.

    ::

        async with Harness(env={"COLOR": "off"}) as h:
            await h.install(trust_server.provide)
            await h.install(aws_secrets.provide)   # ensures trust_server — already installed
            await h.install(trust_client.provide)
            await h.install(aws_cli.provide)       # ensures trust_client — already installed
            async with h.client() as c:
                aws_read = c.tool("aws_read")

    Teardown asserts the Elicitor queue is drained and removes the tmpdir.
    """

    def __init__(self, env: Environ | None = None) -> None:
        """Create an empty harness; ``env`` entries overlay the harness defaults.

        PATH contains *only* the shim bin dir: a spawn the test didn't stub
        fails loudly instead of falling through to a real system binary.
        """
        if not os.access(_SHIM_PATH, os.X_OK):
            raise RuntimeError(
                f"{_SHIM_PATH} is not executable — the install dropped its exec bit; chmod 755 it or reinstall"
            )
        self._tmpdir = Path(tempfile.mkdtemp(prefix="harness-"))
        self._bin_dir = self._tmpdir / "bin"
        self._shim_dir = self._tmpdir / "shims"
        self._bin_dir.mkdir()
        self._shim_dir.mkdir()
        self._shims: dict[str, ExecShim] = {}
        # The shim's `#!/usr/bin/env python3` resolves via PATH, which contains
        # only the bin dir — so the interpreter is symlinked in alongside.
        (self._bin_dir / "python3").symlink_to(sys.executable)

        self.env: dict[str, str] = {
            "PATH": str(self._bin_dir),
            "HARNESS_SHIM_STATE": str(self._shim_dir),
            **(env or {}),
        }
        self.mcp = FastMCP("harness")
        self.elicit = Elicitor()
        self._ctx = ProviderContext(self.mcp, self.env)

    async def install(self, provider: Provider, env: Environ | None = None) -> ProviderState | None:
        """Merge ``env`` into ``self.env``, run the provider, add() its state, return it.

        Same loop step as production load_providers() — install order is
        load order, so install a dependency before its consumer (the
        ProviderNotLoaded error says which one is missing).
        """
        if env:
            self.env.update(env)
        state = await provider(self._ctx)
        self._ctx.add(provider, state)
        return state

    def add(self, provider: Provider, state: ProviderState | None) -> None:
        """Stand in a hand-built state for ``provider`` — its real ``provide()`` never runs.

        The substitution seam for the rare isolated test; a later install()
        of the same provider would replace it (last add wins).
        """
        self._ctx.add(provider, state)

    def write(self, name: str, content: str) -> str:
        """Write ``content`` to ``<tmpdir>/<name>`` (parents created) and return the absolute path."""
        path = self._tmpdir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return str(path)

    def exec(self, name: str) -> ExecShim:
        """Return the shim for executable ``name``, creating it on the Harness's PATH on first use."""
        if name not in self._shims:
            self._shims[name] = ExecShim(name, self._bin_dir, self._shim_dir)
        return self._shims[name]

    def client(self) -> AbstractAsyncContextManager[HarnessClient]:
        """Connect an MCP client to the harness's server (in-process transport)."""

        @asynccontextmanager
        async def connect() -> AsyncGenerator[HarnessClient, None]:
            async with Client(transport=self.mcp, elicitation_handler=self.elicit) as client:
                yield HarnessClient(client)

        return connect()

    def raw_client(self) -> httpx.AsyncClient:
        """Raw HTTP client to the harness's server, with FAKE peer address 127.0.0.1.

        No socket is involved: ASGITransport dispatches in-process, and
        ``client=`` forges the (ip, port) pair the app sees — so handlers
        that authorize by peer IP (e.g. trust registration) accept the
        caller when 127.0.0.1 is allowlisted. Container-boundary behavior
        (real DNS, real isolation) is out of scope by design.

        Builds the ASGI app on call — install every provider and mount all
        custom routes first; FastMCP drops custom_routes added after
        http_app() runs.
        """
        transport = httpx.ASGITransport(app=self.mcp.http_app(), client=("127.0.0.1", 50000))
        return httpx.AsyncClient(transport=transport, base_url="http://ignored")

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Tear down: remove the tmpdir; assert the Elicitor drained — unless the body already failed."""
        shutil.rmtree(self._tmpdir, ignore_errors=True)
        if exc_type is None:
            remaining = len(self.elicit._queue)
            assert not remaining, f"{remaining} elicitation step(s) were never triggered"
