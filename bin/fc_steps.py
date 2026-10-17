"""The setup steps table: one row per step, read by doctor, the plain setup path, and the Textual app.
A row is (name, check, install, level, needs_claude, mode); level is required, default, or designer; mode is run, interactive,
manual (never run), write (compose's own writer; install is `compose setup`), or key."""
import json, re, shutil
from pathlib import Path
import fc_core, fc_auth, fc_config, fc_worktree, fc_checks, fc_pi, fc_keys


FRAMELINK_ENV = Path.home() / ".config" / "figma-context-mcp" / ".env"
FRAMELINK_ADD = f"claude mcp add framelink-figma --scope user -- npx -y figma-developer-mcp --stdio --env {FRAMELINK_ENV} --no-telemetry"
HERDR_MIN = "0.9.3"  # `herdr agent start` and `agent prompt` (herdr_start_crew, pi_herdr_turn): the version they were proven on
TREEHOUSE_MIN = "3.1.2"  # `treehouse get --lease --json --lease-holder` (slot_on): the version it was proven on
STEPS = ()  # task 009: the rows, in setup order

def user_mcp_servers():
    """The MCP servers Claude Code has at user scope, read from ~/.claude.json without starting any (moved from fc_init)."""
    raise NotImplementedError("not implemented: task 009")

def version_of(tool):
    """`<tool> --version` as a tuple of ints, or None (moved from fc_init)."""
    raise NotImplementedError("not implemented: task 009")

def check(row, checkout):
    """(ok, detail) for one row: detail names a floor miss, a dangling link, or a key's absence, never a key value."""
    raise NotImplementedError("not implemented: task 009")
