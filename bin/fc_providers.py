"""Local OpenAI-compatible providers from config.json's `providers` map, for the harnesses: pi's extension file and env,
the reach check and doctor rows, OpenCode's provider, and the price of a turn."""
from __future__ import annotations  # the X | None annotations on /usr/bin/python3 3.9
import fc_config


def pi_extension_text() -> str:
    """The text of ~/.compose/pi-providers.js, rendered from fc_config.PROVIDERS."""
    return ""

def pi_args(model) -> list[str]:
    """["-e", <path>] for a local model, after writing ~/.compose/pi-providers.js when its text changed; else []."""
    return []

def pi_env(model) -> dict:
    """{"COMPOSE_PI_MODEL": "<name>/<id>"} for a local model, else {}."""
    return {}

def cost(model, usage) -> float | None:
    """The turn's price: the PRICES price, else 0.0 for a local model, else usage["cost"]."""
    return None

def reach(name) -> tuple[bool, str]:
    """Whether provider `name` answers a 5 s GET <base_url>/models (any HTTP answer counts), and why."""
    return False, "not implemented"

def doctor_rows() -> list[tuple]:
    """One doctor row per declared provider."""
    return []

def opencode_provider(model) -> dict:
    """The OpenCode provider entry for a local model."""
    return {}
