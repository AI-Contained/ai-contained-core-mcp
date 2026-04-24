import pytest
from unittest.mock import MagicMock
from fastmcp import FastMCP


@pytest.fixture
def mcp():
    return FastMCP("test")


def make_ep(name):
    """Create a mock entry point that records whether it was registered."""
    calls = []

    def register(mcp):
        calls.append(mcp)

    register.calls = calls

    ep = MagicMock()
    ep.name = name
    ep.load.return_value = register
    return ep
