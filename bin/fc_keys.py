"""Key presence (never values), and saving entered keys."""
import os
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

def save_key(kind, value, workspace, framelink_env):
    """Store one entered key (auth.json at fc_config.AUTH_PATH, or FIGMA_API_KEY in framelink_env); a line naming it, never its value."""
    if not value:
        return skipped_line(kind, workspace)
    if kind == "figma":
        env = Path(framelink_env)
        kept = [line for line in env.read_text().splitlines() if not line.startswith("FIGMA_API_KEY=")] if env.exists() else []
        env.parent.mkdir(parents=True, exist_ok=True)
        fc_core.atomic_write(env, "\n".join([*kept, f"FIGMA_API_KEY={value}"]) + "\n", keep_secrets=True)
        os.chmod(env, 0o600)
        return "Figma token saved to the Framelink env file"
    fc_auth.set_key(fc_config.AUTH_PATH, workspace, kind, value)
    return f"{kind} key saved to auth.json for workspace {workspace}"

def skipped_line(kind, workspace):
    """What stops working without the key of kind, and the command to set it later."""
    later = f"pbpaste | compose workspace key {workspace}"
    if kind == "openrouter":
        return (f"No OpenRouter key: without it run and verify have no model. Add one later:\n"
                f"  {later}")
    if kind == "linear":
        return (f"No Linear key: without it compose linear, sync, and the CLI's Linear moves cannot run. Add one later:\n"
                f"  {later} --linear")
    if kind == "typesafe":
        return (f"No TypeSafe key: without it verify and change cannot check your code. Add one later:\n"
                f"  {later} --typesafe")
    if kind == "figma":
        return ("No Figma token: without it the designer cannot build your designs. Add one later, on a terminal:\n"
                "  compose setup")
