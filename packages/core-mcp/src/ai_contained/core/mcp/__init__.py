"""AI-Contained provider loader for FastMCP — the composition root.

os.environ is read only by the caller, which hands it to ProviderContext;
everything below consumes ctx.environ.

Provider selection keeps the long-standing env contract::

    ALLOWED_PROVIDERS   comma-separated entry-point names. Unset or empty
                        means all installed providers are allowed.
    DENIED_PROVIDERS    comma-separated names to skip. Deny wins over allow.

This supports one monolithic image serving multiple containers with
different functionality — each container selects its slice via env.

Loading order is not guaranteed by discovery, so a provider that depends on
another may load before it. Rather than requiring operators to sequence
providers correctly in env, loading self-converges: a provider whose
ctx.ensure() raises ProviderNotLoaded is deferred and retried after the
rest of the enabled set has had a turn, repeating until a full pass makes
no further progress. This only works if a provider resolves all of its own
dependencies via ensure() before registering any tool, route, or resource —
otherwise a retry would re-run those registrations. A dependency that is
genuinely missing (denied, not installed, or a real cycle) still fails the
load loudly, once retrying can no longer make progress. The caller serves
only after loading completes; health checks must not pass before this point.
"""

import importlib.metadata

from fastmcp.utilities.logging import get_logger

from ai_contained.core.mcp.context import Environ as Environ
from ai_contained.core.mcp.context import Provider as Provider
from ai_contained.core.mcp.context import ProviderContext as ProviderContext
from ai_contained.core.mcp.context import ProviderNotLoaded as ProviderNotLoaded
from ai_contained.core.mcp.context import ProviderState as ProviderState

logger = get_logger("ai_contained")


def _env_split_csv(environ: Environ, env_var: str) -> list[str]:
    return [provider_name for provider_name in environ.get(env_var, "").split(",") if provider_name]


def _is_allowed(provider_name: str, allowed: list[str], denied: list[str]) -> bool:
    if provider_name in denied:
        return False
    elif provider_name in allowed:
        return True
    elif len(allowed) == 0:  # no allow list means all providers are allowed
        return True
    return False


async def load_providers(ctx: ProviderContext) -> None:
    """Auto-discover installed ai-contained providers, run each provide(), and add() its state.

    The caller builds the context — the only place os.environ is read::

        ctx = ProviderContext(mcp, os.environ)
        await load_providers(ctx)
    """
    allowed = _env_split_csv(ctx.environ, "ALLOWED_PROVIDERS")
    denied = _env_split_csv(ctx.environ, "DENIED_PROVIDERS")
    logger.debug(f"Loading providers (allowed={allowed or '*'}, denied={denied or 'none'})")

    pending: list[tuple[str, str, importlib.metadata.EntryPoint]] = []
    for entry_point in importlib.metadata.entry_points(group="ai_contained.provider"):
        provider_name = entry_point.name
        version = f"v{entry_point.dist.version}" if entry_point.dist is not None else "v???"
        if not _is_allowed(provider_name, allowed, denied):
            logger.info(f"⏭️  Skipped AI-Contained provider: {provider_name} {version}")
            continue
        pending.append((provider_name, version, entry_point))

    last_error: ProviderNotLoaded | None = None
    while pending:
        deferred: list[tuple[str, str, importlib.metadata.EntryPoint]] = []
        progressed = False
        for provider_name, version, entry_point in pending:
            try:
                provider: Provider = entry_point.load()
                ctx.add(provider, await provider(ctx))
                logger.info(f"✅ Loaded AI-Contained provider: {provider_name} {version}")
                progressed = True
            except ProviderNotLoaded as e:
                deferred.append((provider_name, version, entry_point))
                last_error = e
            except Exception as e:
                logger.error(f"❌ Failed to load AI-Contained provider: {provider_name} {version} — {e}")
                raise
        if not progressed:
            assert last_error is not None
            raise last_error
        pending = deferred
