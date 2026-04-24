"""AI-Contained provider loader for FastMCP."""
import importlib.metadata
import os
from fastmcp import FastMCP
from fastmcp.utilities.logging import get_logger

logger = get_logger("ai_contained")


def _parse_env_list(env_var: str) -> list[str]:
    return [i for i in os.getenv(env_var, "").split(",") if i]


def _is_allowed(name: str, allowed: list[str], denied: list[str]) -> bool:
    if name in denied:
        return False
    elif name in allowed:
        return True
    elif len(allowed) == 0:  # no allow list means all providers are allowed
        return True
    return False


def load_providers(mcp: FastMCP) -> FastMCP:
    """Auto-discover and load all installed ai-contained providers into a FastMCP instance."""
    allowed = _parse_env_list("ALLOWED_PROVIDERS")
    denied = _parse_env_list("DENIED_PROVIDERS")
    for entry_point in importlib.metadata.entry_points(group="ai_contained.provider"):
        name = entry_point.name
        version = f"v{entry_point.dist.version}"
        if not _is_allowed(name, allowed, denied):
            logger.info(f"⏭️  Skipped AI-Contained provider: {name} {version}")
            continue
        try:
            provider = entry_point.load()
            provider(mcp)
            logger.info(f"✅ Loaded AI-Contained provider: {name} {version}")
        except Exception as e:
            logger.error(f"❌ Failed to load AI-Contained provider: {name} {version} — {e}")
            raise
    return mcp
