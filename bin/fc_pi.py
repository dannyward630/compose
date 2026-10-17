"""pi's openrouter-fast provider in models.json, pi's own auth.json overrides, and the TEXT_MODEL lines in ~/.compose/.env."""
import json, os
from pathlib import Path
import fc_core


PI_MODELS = Path(os.environ.get("PI_CODING_AGENT_DIR") or Path.home() / ".pi" / "agent") / "models.json"  # read once, at import
PROVIDER = {}  # task 008: the providers.openrouter-fast entry; its apiKey is the literal "$OPENROUTER_API_KEY"
TEXT_MODEL_DEFAULTS = {}  # task 008: {"TEXT_MODEL": ..., "TEXT_MODEL_BASE_URL": ...}
PI_AUTH = PI_MODELS.parent / "auth.json"

def provider_declared(path):
    """True when the models.json at path has providers.openrouter-fast with the GLM preset model."""
    raise NotImplementedError("not implemented: task 008")

def text_model_set(env_path):
    """True when the .env at env_path has TEXT_MODEL and TEXT_MODEL_BASE_URL lines with values."""
    raise NotImplementedError("not implemented: task 008")

def pi_auth_overrides(path):
    """Which of "openrouter", "openrouter-fast" are top-level entries of pi's auth.json at path, in that order; [] when unreadable."""
    raise NotImplementedError("not implemented: task 008")

def declare_provider(path):
    """Add providers.openrouter-fast = PROVIDER to the models.json at path, keeping the rest; one line saying what it did."""
    raise NotImplementedError("not implemented: task 016")

def write_text_model(env_path):
    """Append the TEXT_MODEL_DEFAULTS lines the .env lacks, never changing existing ones; one line saying what it did."""
    raise NotImplementedError("not implemented: task 016")
