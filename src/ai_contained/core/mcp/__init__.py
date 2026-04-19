"""AI-Contained core MCP server with plugin auto-discovery."""
import importlib.metadata
from fastmcp import FastMCP


def create_server(name: str) -> FastMCP:
    """Create a FastMCP server and auto-load all installed ai_contained plugins."""
    mcp = FastMCP(name)

    for entry_point in importlib.metadata.entry_points(group="ai_contained.plugins"):
        try:
            plugin = entry_point.load()
            plugin(mcp)
            print(f"Loaded plugin: {entry_point.name}")
        except Exception as e:
            print(f"Failed to load plugin '{entry_point.name}': {e}")

    return mcp
