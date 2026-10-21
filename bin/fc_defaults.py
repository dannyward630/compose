"""The product owner's models block as setup's default, the OpenRouter preset steps, and setup's implementer probe."""
import copy, json

import fc_config
import fc_models


DEFAULT_MODELS = {
    "implementer": "pi:openrouter-fast/z-ai/glm-5.3-flash@preset/glm-5-3-flash-fast",
    "fallback": None,
    "crew": {
        "groundwork": "claude:claude-opus-5-5",
        "default": "claude:claude-sonnet-5-5",
        "small": "claude:claude-haiku-5-5",
        "planner": {"model": "claude:claude-opus-5-5", "effort": "high",
                    "fallback": {"model": "pi:openai/gpt-6-astra", "effort": "high"}},
        "wayfinder": {"model": "claude:claude-fable-5-1", "effort": "high",
                      "fallback": [{"model": "pi:openai/gpt-6-astra", "effort": "high"},
                                   {"model": "claude:claude-opus-5-5", "effort": "high"}]},
        **{role: {"model": "claude:claude-opus-5-5", "effort": "high"}
           for role in ("orchestrator", "designer", "designer-plan", "explore", "research", "perf", "toolsmith")},
    },
}

PRESET_STEPS = (
    "OpenRouter needs a preset before the default implementer can run:",
    "1. Create the preset glm-5-3-flash-fast at https://openrouter.ai/settings/presets for model z-ai/glm-5.3-flash, with providers in order: Together, then CoreWeave.",
    "2. To run a different implementer model, change models.implementer in ~/.compose/config.json.",
)


def merge_models(cfg):
    """(cfg, lines): every missing DEFAULT_MODELS key added under cfg["models"], nothing already there changed; one line per key added."""
    cfg = copy.deepcopy(cfg)
    models = cfg.setdefault("models", {})
    lines = []
    for key, value in DEFAULT_MODELS.items():
        if key not in models:
            models[key] = copy.deepcopy(value)
            lines.append(f"models.{key} = {value if isinstance(value, str) else json.dumps(value)}")
    crew = models.setdefault("crew", {})
    for role, value in DEFAULT_MODELS["crew"].items():
        if role not in crew:
            crew[role] = copy.deepcopy(value)
            lines.append(f"models.crew.{role} = {value if isinstance(value, str) else json.dumps(value)}")
    return cfg, lines


def probe_implementer(cfg):
    """(True, [pass line]) or (False, [provider's message, *PRESET_STEPS]) from fc_models.model_available on cfg's implementer."""
    model = cfg.get("models", {}).get("implementer", DEFAULT_MODELS["implementer"])
    ok, why = fc_models.model_available(model)
    if ok:
        return True, [f"implementer {model}: {why}"]
    if fc_config.provider_of(model) is not None:
        return False, [why]
    return False, [why, *PRESET_STEPS]
