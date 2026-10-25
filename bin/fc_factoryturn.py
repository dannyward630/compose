"""The build loop's decision step: what is in flight, and which ready stories to start next."""
import fc_plan, fc_readiness

JUDGE_LIMIT = 6
OPEN = ("todo", "backlog")
FREED = ("in review", "done", "canceled")
SHAPING = "needs-shaping"

def story_of(plan, ident):
    """The plan's story with this id, or None."""
    for f in plan["features"].values():
        for s in f.get("stories") or []:
            if s["id"] == ident:
                return s
    return None

def classify(labels, r):
    """What a judged story is ready for: "build" (tasks cut and labeled Ready), "cut" (specced, no tasks yet), or None."""
    if not r["ready"] or SHAPING in labels:
        return None
    if r["has_tasks"]:
        return "build" if "Ready" in labels else None
    return "cut"

def in_flight(plan, state):
    """Ids of stories being built: In Progress in Linear, or dispatched here and not yet In Review, Done or Canceled."""
    live = set()
    for f in plan["features"].values():
        for s in f.get("stories") or []:
            if s["state"].lower() == "in progress" or (s["id"] in state["dispatched"] and s["state"].lower() not in FREED):
                live.add(s["id"])
    return sorted(live, key=fc_plan.issue_num)

def _why(missing, labels):
    if missing:
        return "; ".join(f"{m['item']}: {m['question']}" for m in missing)[:200]
    return ("labeled " + SHAPING) if SHAPING in labels else "not specced"

def pick(entries, plan, state, free, judge):
    """Walk the entries in order and start up to free ready stories. judge(repo, id, write=True) is the caller's readiness check."""
    flying = set(in_flight(plan, state))
    out = {"picks": [], "ready_waiting": False, "offer": None, "failed": [], "specced": set()}
    candidate, judged = None, 0
    for e in entries:
        if judged >= JUDGE_LIMIT or (len(out["picks"]) == free and (out["ready_waiting"] or candidate)):
            break
        if e["id"] in flying or e["state"].lower() not in OPEN or e["waits_on"]:
            continue
        if e["kind"] == "feature":
            candidate = candidate or {"id": e["id"], "layer": "stories", "why": "no stories yet"}
            continue
        labels = (story_of(plan, e["id"]) or {}).get("labels", [])
        judged += 1
        try:
            r = judge(None, e["id"], write=True)
        except fc_readiness.NotAStory as ex:
            out["failed"].append((e["id"], str(ex)))
            continue
        if r.get("error"):
            out["failed"].append((e["id"], r["error"]))
            continue
        if r.get("specced"):
            out["specced"].add(e["id"])
        kind = classify(labels, r)
        if kind:
            if len(out["picks"]) < free:
                out["picks"].append((e, kind))
            else:
                out["ready_waiting"] = True
        elif r.get("specced") is False or SHAPING in labels:
            candidate = candidate or {"id": e["id"], "layer": "story", "why": _why(r.get("missing") or [], labels)}
    if not out["picks"] and not out["ready_waiting"]:
        out["offer"] = candidate
    return out
