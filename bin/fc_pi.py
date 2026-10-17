"""pi's openrouter-fast provider in models.json, pi's own auth.json overrides, and the TEXT_MODEL lines in ~/.compose/.env."""
import json, os
from pathlib import Path
import fc_core


PI_MODELS = Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi" / "agent") / "models.json"  # read once, at import
PROVIDER = {"baseUrl": "https://openrouter.ai/api/v1", "api": "openai-completions", "apiKey": "$OPENROUTER_API_KEY",
            "models": [{"id": "z-ai/glm-5.3-flash@preset/glm-5-3-flash-fast", "cost": {"input": 0.15, "output": 0.5, "cacheRead": 0, "cacheWrite": 0}}]}
TEXT_MODEL_DEFAULTS = {"TEXT_MODEL": "inception/mercury-2.5", "TEXT_MODEL_BASE_URL": "https://openrouter.ai/api/v1"}
PI_AUTH = PI_MODELS.parent / "auth.json"

def provider_declared(path):
    """True when the models.json at path has providers.openrouter-fast with the GLM preset model."""
    try:
        models = json.loads(Path(path).read_text())["providers"]["openrouter-fast"]["models"]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    return isinstance(models, list) and any(isinstance(m, dict) and m.get("id") == PROVIDER["models"][0]["id"] for m in models)

def text_model_set(env_path):
    """True when the .env at env_path has TEXT_MODEL and TEXT_MODEL_BASE_URL lines with values."""
    try:
        lines = Path(env_path).read_text().splitlines()
    except OSError:
        return False
    found = set()
    for line in lines:
        key, sep, value = line.partition("=")
        if sep and value.strip() and key.strip() in TEXT_MODEL_DEFAULTS:
            found.add(key.strip())
    return set(TEXT_MODEL_DEFAULTS) <= found

def pi_auth_overrides(path):
    """Which of "openrouter", "openrouter-fast" are top-level entries of pi's auth.json at path, in that order; [] when unreadable."""
    try:
        auth = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return []
    return [name for name in ("openrouter", "openrouter-fast") if isinstance(auth, dict) and name in auth]

def declare_provider(path):
    """Add providers.openrouter-fast = PROVIDER to the models.json at path, keeping the rest; one line saying what it did."""
    raise NotImplementedError("not implemented: task 016")

def write_text_model(env_path):
    """Append the TEXT_MODEL_DEFAULTS lines the .env lacks, never changing existing ones; one line saying what it did."""
    raise NotImplementedError("not implemented: task 016")
