"""Key presence (never values), and saving entered keys."""
import os
from pathlib import Path
import fc_core, fc_auth, fc_config, fc_prompt


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

KEYS = (("openrouter", "OpenRouter key", "required", "openrouter.ai/keys"),
        ("typesafe", "TypeSafe key", "required", "your TypeSafe account"),
        ("linear", "Linear key", "required", "linear.app/settings/api"),
        ("figma", "Figma token", "optional", "Figma settings, personal access tokens"))

def ask_keys(workspace, framelink_env, designer, dry=False):
    """Ask for each key with hidden input after the steps; returns the kinds saved, in order."""
    set_ = key_status(fc_auth.read_auth(fc_config.AUTH_PATH), workspace, framelink_env)
    fc_prompt.note(f"Keys for workspace {workspace}", [])
    home = str(Path.home())
    short = lambda p: str(p).replace(home, "~", 1)
    saved = []
    for kind, label, mark, hint in KEYS:
        if kind == "figma" and not designer:
            continue
        print(f"│  {label} ({mark}), from {hint} [{'set' if set_[kind] else 'not set'}]")
        while True:
            value = fc_prompt.password(f"{label} (Enter keeps it)" if set_[kind] else f"{label} (Enter skips)")
            if value:
                if dry:
                    what = "the Figma token" if kind == "figma" else f"{kind} key"
                    print(f"│  would save {what} to {short(framelink_env if kind == 'figma' else fc_config.AUTH_PATH)}")
                else:
                    print("│  " + save_key(kind, value, workspace, framelink_env))
                saved.append(kind)
                break
            if set_[kind] or mark == "optional":
                break
            for line in skipped_line(kind, workspace).splitlines():
                print("│  " + line)
            if fc_prompt.confirm("Continue without it?", False):
                break
    return saved
