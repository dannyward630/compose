"""What Jev is shown to route a task: the cheap context first, dependency analysis only on the retry, and the hash that
tells a recorded route is still current."""

import json, re

import fc_tasks


def route_context(repo, proj, meta, tasks, issues):
    """The Jev state for one task: task, criteria, files, other_files, story, bug, pin."""
    mine = issues.get(meta["linear"]) or {}
    parent = issues.get(mine.get("parentId"))
    rep = re.search(r"## Reproduction\n(.*?)(?:\n## |\Z)", meta["body"], re.S)
    text = (rep.group(1) if rep else "").strip()
    case = re.search(r"^case:\s*(\S+)", text, re.M) if text else None
    name = case.group(1) if case else None
    confirmed = False
    if name and (proj / "verify.json").exists() and (proj / "results" / "prove.json").exists():
        e2e = json.loads((proj / "verify.json").read_text()).get("e2e") or []
        rows = json.loads((proj / "results" / "prove.json").read_text()).get("cases") or []
        confirmed = any(c.get("name") == name for c in e2e) and \
            any(r.get("name") == name and r.get("verdict") == "feature_missing" for r in rows)
    open_states = ("done", "canceled", "cancelled")
    other = [t for t in tasks if t["id"] != meta["id"] and (t.get("linear_state") or "").lower() not in open_states]
    return {"task": meta["title"], "criteria": fc_tasks.parse_criteria(meta["body"]),
            "files": [{"path": f, "top": f.split("/")[0] if "/" in f else ".", "exists": (repo / f).exists()} for f in meta["files"]],
            "other_files": sorted({f for t in other for f in t["files"]}),
            "story": None if not parent else {"title": parent["title"], "criteria": fc_tasks.parse_criteria(parent["description"])},
            "bug": {"label": any(l.lower() == "bug" for l in mine.get("labels") or ()), "documented": bool(text), "confirmed": confirmed},
            "pin": meta.get("route")}


def dependency_context(repo, meta):
    """{"callers": {path: [file, ...]}} for the task's existing files, or {"unavailable": "<why>"}."""
    raise NotImplementedError("dependency_context")


def context_hash(repo, meta, policies):
    """16 hex chars of sha256 over the task body (Route left out), its files, their blobs at HEAD and the policies."""
    raise NotImplementedError("context_hash")
