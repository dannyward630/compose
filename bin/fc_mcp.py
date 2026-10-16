"""Which MCP servers and skills each teammate role keeps; the rest become `--disallowedTools` patterns. Stdlib only."""
from __future__ import annotations

ROLE_MCP = {}


def servers_for(role) -> tuple:
    raise NotImplementedError("fc_mcp.servers_for")


def keeps_skills(role) -> bool:
    raise NotImplementedError("fc_mcp.keeps_skills")


def installed_servers() -> list[str]:
    raise NotImplementedError("fc_mcp.installed_servers")


def disallowed(role, servers, frame0=False) -> list[str]:
    raise NotImplementedError("fc_mcp.disallowed")
