"""Story and project tier pins, kept in results/tier.json, and the model an implementer starts on."""
import json

import fc_budget, fc_core, fc_routecost, fc_tasks, fc_tiers


def read(proj):
    """The parsed results/tier.json, or {} when it is missing or unreadable."""
    try:
        return json.loads((proj / "results" / "tier.json").read_text())
    except (OSError, ValueError):
        return {}


def pin(proj, meta):
    """The tier pin that rules a task: the task's own, else its story's, else the project's, else None."""
    if meta.get("tier"):
        return meta["tier"]
    parent = (fc_tasks.linear_cache(proj).get("issues") or {}).get(meta.get("linear"), {}).get("parentId")
    pins = read(proj)
    return ((pins.get("stories") or {}).get(parent) if parent else None) or pins.get("project")


def start_model(proj, meta):
    """The model an implementer starts on: the task's own unless it chose auto, else the one its route depth and pin pick."""
    if not meta.get("model_auto"):
        return meta["model"]
    return fc_tiers.implementer_model(fc_budget.hold(proj, fc_tiers.start_tier(fc_routecost.route(proj, meta)[1], pin(proj, meta))))


def cmd_tier(a):
    """Set or clear one tier pin, a story's with --story else the project's, in results/tier.json."""
    proj = fc_core.project_dir(a)
    pins = read(proj)
    target = f"story {a.story}" if a.story else f"project {proj.name}"
    if a.value == "clear":
        if a.story:
            (pins.get("stories") or {}).pop(a.story, None)
        else:
            pins.pop("project", None)
        print(f"tier pin cleared for {target}")
    else:
        if a.story:
            pins.setdefault("stories", {})[a.story] = a.value
        else:
            pins["project"] = a.value
        print(f"tier {a.value} for {target}")
    fc_core.atomic_write(proj / "results" / "tier.json", json.dumps(pins, indent=2))


def lines(proj):
    """The status line naming the tier pins, or [] when there is none."""
    pins = read(proj)
    parts = [f"project {pins['project']}"] if pins.get("project") else []
    parts += [f"{s} {v}" for s, v in sorted((pins.get("stories") or {}).items())]
    return ["  tier pins  " + ", ".join(parts)] if parts else []
