# core-mcp

The base provider loader for [AI-Contained](https://github.com/AI-Contained) MCP servers. Provides auto-discovery of installed providers via Python entry points.

## Usage

```python
from fastmcp import FastMCP
from ai_contained.core.mcp import load_providers

mcp = FastMCP("my-server")
load_providers(mcp)
```

`load_providers` discovers all packages registered under the `ai-contained.provider` entry point group and loads them into the provided `FastMCP` instance.

## Installation

```bash
pip install "ai-contained-core-mcp @ https://github.com/AI-Contained/core-mcp/archive/refs/tags/v0.0.2.zip"
```

## Creating a Provider

1. Create a package with a `register(mcp)` function
2. Register it in `pyproject.toml`:

```toml
[project.entry-points."ai_contained.provider"]
myprovider = "my_package:register"
```

3. Install it - `load_providers` will discover it automatically.

See [ai-contained-provider-template](https://github.com/AI-Contained/ai-contained-provider-template) for a reference implementation.
