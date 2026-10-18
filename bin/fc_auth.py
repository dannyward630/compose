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
    """Move every old key into auth.json and out of config.json and .env; one line per key moved, never a value.
    The first key moved for a slot wins (or the one auth.json already holds): an old key equal to its slot's key is
    removed with its line, one that differs stays exactly where it is with no line, so old_keys and doctor still see it."""
    config_path, env_path = Path(config_path), Path(env_path)
    cfg = json.loads(config_path.read_text()) if config_path.exists() else {}
    env_lines = env_path.read_text().splitlines(keepends=True) if env_path.exists() else []
    auth, lines, dirty_cfg = read_auth(auth_path), [], False

    def store(workspace, kind, value, name, path):
        """Claim the slot for value unless a different key already holds it; True when name is recorded as moved out."""
        nonlocal auth
        held = auth.get("typesafe") if kind == "typesafe" else auth.get("workspaces", {}).get(workspace, {}).get(kind)
        if held and held != value:
            return False
        if not held:
            set_key(auth_path, workspace, kind, value)
            auth = read_auth(auth_path)
        lines.append(f"{name} out of {path}")
        return True

    for k, kind in (("openrouter_api_key", "openrouter"), ("linear_api_key", "linear")):
        if k in cfg and store("default", kind, cfg[k], k, config_path):
            del cfg[k]
            dirty_cfg = True
    if "TYPESAFE_API_KEY" in cfg.get("env", {}) and store(None, "typesafe", cfg["env"]["TYPESAFE_API_KEY"], "env.TYPESAFE_API_KEY", config_path):
        del cfg["env"]["TYPESAFE_API_KEY"]
        dirty_cfg = True
    for name, ws in cfg.get("workspaces", {}).items():
        for k, kind in (("openrouter_api_key", "openrouter"), ("linear_api_key", "linear")):
            if k in ws and store(name, kind, ws[k], f"workspaces.{name}.{k}", config_path):
                del ws[k]
                dirty_cfg = True
    new_env, env_dirty = [], False
    for line in env_lines:
        name = line.split("=", 1)[0].strip()
        if name in ("TYPESAFE_API_KEY", "TEXT_MODEL_API_KEY"):
            ws, kind = ("default", "openrouter") if name == "TEXT_MODEL_API_KEY" else (None, "typesafe")
            if store(ws, kind, line.partition("=")[2].strip(), name, env_path):
                env_dirty = True
                continue
        new_env.append(line)
    if env_dirty:
        fc_core.atomic_write(env_path, "".join(new_env), keep_secrets=True)  # the user's own lines stay as they are
    if dirty_cfg:
        fc_core.atomic_write(config_path, json.dumps(cfg, indent=2) + "\n", keep_secrets=True)
        os.chmod(config_path, 0o600)
    return lines
