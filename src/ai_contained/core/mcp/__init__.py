"""AI-Contained provider loader for FastMCP."""
import importlib.metadata
from fastmcp import FastMCP
from fastmcp.utilities.logging import get_logger

logger = get_logger("ai_contained")


def load_providers(mcp: FastMCP) -> FastMCP:
    """Auto-discover and load all installed ai-contained providers into a FastMCP instance."""
    for entry_point in importlib.metadata.entry_points(group="ai_contained.provider"):
        try:
            provider = entry_point.load()
            provider(mcp)
            logger.info(f"✅ Loaded AI-Contained provider: {entry_point.name}")
        except Exception as e:
            logger.error(f"❌ Failed to load AI-Contained provider '{entry_point.name}': {e}")
    return mcp
