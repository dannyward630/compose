"""The credit preflight of a run: whether the OpenRouter key can pay for the tasks that start at once, checked before anything is
cloned, so a run does not stall on a 402 an hour in. Imports only lower modules."""

import json, os, urllib.request

import fc_config, fc_core, fc_models

DEFAULT_TASK_COST = 0.25  # dollars a task is assumed to cost on a model that has no finished task on record
RECENT = 20  # finished tasks of a model whose cost is averaged

def via_openrouter(model):
    """Whether a model's calls are billed to the OpenRouter key (`fc_models.pi_turn` books them by the same test)."""
    return "openrouter" in str(model)

def recent_costs(repo, model):
    """Dollars of the model's latest finished tasks, newest first, at most RECENT, from the result files of every project of the repo."""
    found = []
    for _, proj in fc_core.all_projects(repo).values():
        for f in (proj / "results").glob("[0-9]*.json"):
            try:
                r = json.loads(f.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(r, dict) and r.get("model") == model and (r.get("cost") or 0) > 0:
                found.append((f.stat().st_mtime, r["cost"]))
    return [c for _, c in sorted(found, reverse=True)[:RECENT]]

def task_cost(repo, model):
    """(dollars one task of this model is expected to cost, whether it comes from finished tasks): their mean, else DEFAULT_TASK_COST."""
    costs = recent_costs(repo, model)
    return (sum(costs) / len(costs), True) if costs else (DEFAULT_TASK_COST, False)

def remaining():
    """Dollars left on the OpenRouter key, or None when it has no limit, no key is set, or OpenRouter does not answer (no verdict then)."""
    if not fc_config.OPENROUTER_KEY:
        return None
    req = urllib.request.Request("https://openrouter.ai/api/v1/auth/key", headers={"Authorization": "Bearer " + fc_config.OPENROUTER_KEY})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            left = (json.load(r).get("data") or {}).get("limit_remaining")
    except (OSError, ValueError, AttributeError):
        return None
    return left if isinstance(left, (int, float)) else None

def check(repo, tasks, parallel, force=False):
    """The line that stops a run whose OpenRouter key cannot pay for `parallel` tasks at once, else None. The need is the
    estimated cost of the dearest `parallel` OpenRouter tasks (task_cost per model). `force`, no OpenRouter task, a key with no
    limit, and COMPOSE_NO_PREFLIGHT=1 all make no call and give no verdict."""
    if force or os.environ.get("COMPOSE_NO_PREFLIGHT"):
        return None
    models = sorted({m["model"] for m in tasks if via_openrouter(m["model"])})
    if not models:
        return None
    price = {model: task_cost(repo, model) for model in models}
    costs = sorted((price[m["model"]][0] for m in tasks if m["model"] in price), reverse=True)[:max(1, parallel)]
    need, left = sum(costs), remaining()
    if left is None or left >= need:
        return None
    basis = ("the mean of their last finished tasks" if all(known for _, known in price.values())
             else f"the mean of their last finished tasks, else ${DEFAULT_TASK_COST:.2f}")
    return (f"the OpenRouter key has ${left:.2f} of credit left, and {len(costs)} task(s) at once need about ${need:.2f} "
            f"(${need / len(costs):.2f} each on average, {basis}). Add credit at {fc_models.TOP_UP['openrouter']} or raise the key's limit, "
            "then run again; --force starts anyway")
