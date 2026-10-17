"""~/.compose/auth.json, the one secured store for every key: {"workspaces": {"default": {"openrouter": ..., "linear": ...},
"<name>": {...}}, "typesafe": ...}. File mode 600 in a 700 directory. Paths are passed in; this module never imports fc_config."""
import json, os
from pathlib import Path
import fc_core


def read_auth(path):
    """auth.json parsed, or {} when the file is missing."""
    path = Path(path)
    return json.loads(path.read_text()) if path.exists() else {}

def write_auth(path, data):
    """Write data atomically (fc_core.atomic_write), the file at mode 600 and its directory at 700."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fc_core.atomic_write(path, json.dumps(data), keep_secrets=True)  # the one file that holds the keys
    os.chmod(path, 0o600)

def workspace_key(auth, workspace, kind):
    """The key of kind (openrouter, linear, typesafe) for workspace, else the default workspace's, else None; typesafe is top level."""
    if kind == "typesafe":
        return auth.get("typesafe")
    spaces = auth.get("workspaces", {})
    return spaces.get(workspace, {}).get(kind) or spaces.get("default", {}).get(kind)

def set_key(path, workspace, kind, value):
    """Store one key in the auth.json at path, keeping every other entry; typesafe goes to the top level."""
    auth = read_auth(path)
    if kind == "typesafe":
        auth["typesafe"] = value
    else:
        auth.setdefault("workspaces", {}).setdefault(workspace, {})[kind] = value
    write_auth(path, auth)

def old_keys(config_path, env_path):
    """[(name, path)] for every key still in config.json or .env: name is where it sits in that file, never its value."""
    config_path, env_path, found = Path(config_path), Path(env_path), []
    if config_path.exists():
        cfg = json.loads(config_path.read_text())
        found += [(k, config_path) for k in ("openrouter_api_key", "linear_api_key") if k in cfg]
        if "TYPESAFE_API_KEY" in cfg.get("env", {}):
            found.append(("env.TYPESAFE_API_KEY", config_path))
        for name, ws in cfg.get("workspaces", {}).items():
            found += [(f"workspaces.{name}.{k}", config_path) for k in ("openrouter_api_key", "linear_api_key") if k in ws]
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            name = line.split("=", 1)[0].strip()
            if name in ("TYPESAFE_API_KEY", "TEXT_MODEL_API_KEY"):
                found.append((name, env_path))
    return found

def move_keys(config_path, env_path, auth_path):
    """Move every old key into auth.json and out of config.json and .env; one line per key moved, never a value."""
    config_path, env_path = Path(config_path), Path(env_path)
    cfg = json.loads(config_path.read_text()) if config_path.exists() else {}
    env_lines = env_path.read_text().splitlines(keepends=True) if env_path.exists() else []
    auth, lines, dirty_cfg = read_auth(auth_path), [], False
    top_openrouter, top_typesafe = "openrouter_api_key" in cfg, "TYPESAFE_API_KEY" in cfg.get("env", {})

    def store(workspace, kind, value, name, path):
        nonlocal auth
        held = auth.get("typesafe") if kind == "typesafe" else auth.get("workspaces", {}).get(workspace, {}).get(kind)
        if not held:
            set_key(auth_path, workspace, kind, value)
            auth = read_auth(auth_path)
        lines.append(f"{name} out of {path}")

    for k, kind in (("openrouter_api_key", "openrouter"), ("linear_api_key", "linear")):
        if k in cfg:
            store("default", kind, cfg[k], k, config_path)
            del cfg[k]
            dirty_cfg = True
    if top_typesafe:
        store(None, "typesafe", cfg["env"]["TYPESAFE_API_KEY"], "env.TYPESAFE_API_KEY", config_path)
        del cfg["env"]["TYPESAFE_API_KEY"]
        dirty_cfg = True
    for name, ws in cfg.get("workspaces", {}).items():
        for k, kind in (("openrouter_api_key", "openrouter"), ("linear_api_key", "linear")):
            if k in ws:
                store(name, kind, ws[k], f"workspaces.{name}.{k}", config_path)
                del ws[k]
                dirty_cfg = True
    moved, kept = [], []
    for line in env_lines:
        if line.split("=", 1)[0].strip() in ("TYPESAFE_API_KEY", "TEXT_MODEL_API_KEY"):
            moved.append(line)
        else:
            kept.append(line)
    for line in moved:
        name, _, value = line.partition("=")
        name = name.strip()
        if name == "TEXT_MODEL_API_KEY" and not top_openrouter:
            store("default", "openrouter", value.strip(), name, env_path)
        elif name == "TYPESAFE_API_KEY" and not top_typesafe:
            store(None, "typesafe", value.strip(), name, env_path)
        else:
            lines.append(f"{name} out of {env_path}")
    if moved:
        fc_core.atomic_write(env_path, "".join(kept), keep_secrets=True)  # the user's own lines stay as they are
    if dirty_cfg:
        fc_core.atomic_write(config_path, json.dumps(cfg, indent=2) + "\n", keep_secrets=True)
        os.chmod(config_path, 0o600)
    return lines
