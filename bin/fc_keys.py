"""Key presence (never values), the Linear rule (an API key or the claude.ai Linear connector), and saving entered keys."""
import shutil
from pathlib import Path
import fc_core, fc_auth, fc_config


def key_status(auth, workspace, framelink_env):
    """{"openrouter": bool, "typesafe": bool, "linear": bool, "figma": bool}: whether a non-empty key is set."""
    raise NotImplementedError("not implemented: task 007")

def linear_connected():
    """True when `claude mcp list` shows the claude.ai Linear line Connected, False when missing or another status, None without claude."""
    raise NotImplementedError("not implemented: task 007")

def linear_state(status, connected):
    """"key", "connector", "unknown", or "missing" from key_status's dict and linear_connected's value."""
    raise NotImplementedError("not implemented: task 007")

def save_key(kind, value, workspace, framelink_env):
    """Store one entered key (auth.json at fc_config.AUTH_PATH, or FIGMA_API_KEY in framelink_env); a line naming it, never its value."""
    raise NotImplementedError("not implemented: task 017")

def skipped_line(kind, workspace):
    """What stops working without the key of kind, and the command to set it later."""
    raise NotImplementedError("not implemented: task 017")
