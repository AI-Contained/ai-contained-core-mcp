"""AI-Contained provider loader for FastMCP — the composition root.

This module is the only place in any container that reads os.environ.

Provider selection keeps the long-standing env contract::

    ALLOWED_PROVIDERS   comma-separated entry-point names. Unset or empty
                        means all installed providers are allowed.
    DENIED_PROVIDERS    comma-separated names to skip. Deny wins over allow.

This supports one monolithic image serving multiple containers with
different functionality — each container selects its slice via env.

Loading is a plain loop, in ALLOWED_PROVIDERS order (discovery order when
unset)::

    for provider in enabled:
        ctx.add(provider, await provider.provide(ctx))

A provider that depends on another must be listed after it — ensure() is a
lookup, and a missing dependency fails the boot with an error naming the
provider to add or reorder. The caller serves only after the loop
completes; health checks must not pass before this point.
"""

from collections.abc import Mapping

from fastmcp import FastMCP

from ai_contained.core.mcp.context import (
    Provider as Provider,
)
from ai_contained.core.mcp.context import (
    ProviderContext as ProviderContext,
)
from ai_contained.core.mcp.context import (
    ProviderNotLoaded as ProviderNotLoaded,
)
from ai_contained.core.mcp.context import (
    ProviderState as ProviderState,
)

ALLOWED_PROVIDERS_ENV = "ALLOWED_PROVIDERS"
DENIED_PROVIDERS_ENV = "DENIED_PROVIDERS"
ENTRY_POINT_GROUP = "ai_contained.provider"


async def load_providers(mcp: FastMCP, environ: Mapping[str, str]) -> ProviderContext:
    """Run every enabled provider's provide() in order and return the ProviderContext.

    Args:
        mcp: The server to wire providers onto. Must not be serving yet.
        environ: The process environment (pass ``os.environ`` in production).

    Returns:
        The ProviderContext holding every loaded provider's state.

    Raises:
        ProviderNotLoaded: a provider ensured a dependency that is not
            enabled or is listed after it.

    """
    raise NotImplementedError
