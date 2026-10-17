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
    raise NotImplementedError("not implemented: task 002")

def move_keys(config_path, env_path, auth_path):
    """Move every old key into auth.json and out of config.json and .env; one line per key moved, never a value."""
    raise NotImplementedError("not implemented: task 002")
