"""The product owner's models block as setup's default, the OpenRouter preset steps, and setup's implementer probe."""
import fc_models


DEFAULT_MODELS = {}  # task 015: implementer, fallback, crew
PRESET_STEPS = ()  # task 015: the lines telling the user how to create the preset and where to change the model

def merge_models(cfg):
    """(cfg, lines): every missing DEFAULT_MODELS key added under cfg["models"], nothing already there changed; one line per key added."""
    raise NotImplementedError("not implemented: task 015")

def probe_implementer(cfg):
    """(True, [pass line]) or (False, [provider's message, *PRESET_STEPS]) from fc_models.model_available on cfg's implementer."""
    raise NotImplementedError("not implemented: task 015")
