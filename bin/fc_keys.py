"""Key presence (never values), the Linear rule (an API key or the claude.ai Linear connector), and saving entered keys."""
import shutil
import subprocess
from pathlib import Path
import fc_core, fc_auth, fc_config


def key_status(auth, workspace, framelink_env):
    """{"openrouter": bool, "typesafe": bool, "linear": bool, "figma": bool}: whether a non-empty key is set."""
    keys = {k: bool(fc_auth.workspace_key(auth, workspace, k)) for k in ("openrouter", "typesafe", "linear")}
    try:
        lines = Path(framelink_env).read_text().splitlines()
    except OSError:
        lines = []
    keys["figma"] = any(line.startswith("FIGMA_API_KEY=") and line[len("FIGMA_API_KEY="):].strip() for line in lines)
    return keys

def linear_connected():
    """True when `claude mcp list` shows the claude.ai Linear line Connected, False when missing or another status, None without claude."""
    try:
        out = subprocess.run(["claude", "mcp", "list"], capture_output=True, text=True).stdout
    except FileNotFoundError:
        return None
    for line in out.splitlines():
        if line.startswith("claude.ai Linear"):
            return "Connected" in line.rsplit(" - ", 1)[-1]
    return False

def linear_state(status, connected):
    """"key", "connector", "unknown", or "missing" from key_status's dict and linear_connected's value."""
    if status["linear"]:
        return "key"
    if connected:
        return "connector"
    return "unknown" if connected is None else "missing"

def save_key(kind, value, workspace, framelink_env):
    """Store one entered key (auth.json at fc_config.AUTH_PATH, or FIGMA_API_KEY in framelink_env); a line naming it, never its value."""
    raise NotImplementedError("not implemented: task 017")

def skipped_line(kind, workspace):
    """What stops working without the key of kind, and the command to set it later."""
    raise NotImplementedError("not implemented: task 017")
