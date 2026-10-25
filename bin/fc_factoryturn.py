"""The build loop's decision step: what is in flight, and which ready stories to start next."""
import json, os, re, subprocess, sys
from pathlib import Path
import fc_core, fc_herdr, fc_plan, fc_readiness, fc_reconcile, fc_tasks

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
    """Walk the entries in order and start up to free ready stories. judge(id, write=True) is the caller's readiness check; the caller binds the repo."""
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
            r = judge(e["id"], write=True)
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

LEAD_READS = ("SKILL.md, sections/0h.md, sections/0a.md, sections/0e.md, sections/0f.md, sections/0g.md, sections/4.md, sections/5.md, "
              "sections/6.md, sections/6a.md, sections/7.md, sections/8.md and ~/.claude/skills/herdr/SKILL.md")
HOW = {"build": "Its tasks are cut: run them through the 3b gate.",
       "cut": "It has no tasks yet: start the planner for this story only (0j, story), then run its tasks through the 3b gate."}

def lead_prompt(story, feature, title, kind):
    """The prompt that hands one story to a feature's team lead."""
    return (f"factory: build story {story} of feature {feature} ({title}). {HOW[kind]} Build only this story: verify and stack it "
            "as SKILL.md says, report done when it passes, and never start another story on your own.")

def lead_brief(slug, wt, feature, prompt):
    """The first brief of a new team lead: who it is, what to read, then the prompt."""
    return (f"You are the team lead of project {slug} in {wt}, building feature {feature} for the compose factory.\n"
            f"Read {LEAD_READS}, then continue from 0e.\n{prompt}\n")

def slug_for(title, taken):
    """A short kebab project name from a title: at most 4 words within 24 characters, numbered while taken."""
    words = [w for w in re.sub(r"[^a-z0-9]+", "-", title.lower()).split("-") if w][:4] or ["feature"]
    while len(words) > 1 and len("-".join(words)) > 24:
        words.pop()
    base = "-".join(words)[:24].strip("-")
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    return slug

def _linear(proj):
    try:
        got = json.loads((Path(proj) / "linear.json").read_text())
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}

def project_for(repo, feature):
    """(slug, worktree, project dir) of the feature's compose project, or None."""
    for slug, (wt, proj) in sorted(fc_core.all_projects(Path(repo)).items()):
        if _linear(proj).get("feature") == feature:
            return slug, Path(wt), Path(proj)
    return None

def after_project(repo, plan, feature):
    """The project of the first blocker that is built (verified) but not merged, by id number, or None."""
    blockers = (plan["features"].get(feature) or {}).get("blockers") or []
    for b in sorted(blockers, key=lambda b: fc_plan.issue_num(b["id"])):
        if fc_plan.base_built(b["state"], b["labels"]) and not fc_tasks.blocker_finished(b["state"], b["labels"]):
            got = project_for(repo, b["id"])
            if got:
                return got[0]
    return None

def compose_cli(args, stdin=None):
    """Run one compose command as the engineering manager; its stdout, or RuntimeError with its stderr."""
    env = {k: v for k, v in os.environ.items() if k != "COMPOSE_ROLE"}
    p = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "compose.py"), *map(str, args)], input=stdin,
                       capture_output=True, text=True, env=env)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout).strip() or f"compose {args[0]} exited {p.returncode}")
    return p.stdout

def prompt_lead(name, text):
    """Send a prompt to a live team lead; whether herdr took it."""
    return fc_herdr.herdr("agent", "prompt", name, text) is not None

def dispatch(repo, plan, entry, kind, state, now):
    """Hand a ready story to its feature's team lead, making the project and starting the lead when missing. Returns the event line."""
    feature, story = entry["feature"], entry["id"]
    title = (plan["features"].get(feature) or {}).get("title") or feature
    found = project_for(repo, feature)
    if not found:
        slug = slug_for(title, set(fc_core.all_projects(Path(repo))))
        after = after_project(repo, plan, feature)
        compose_cli(["init", "--repo", str(repo), "--project", slug] + (["--after", after] if after else []))
        found = project_for(repo, feature) or next(((s, Path(w), Path(p)) for s, (w, p) in fc_core.all_projects(Path(repo)).items() if s == slug), None)
        if not found:
            raise RuntimeError(f"compose init made no project {slug}")
        fc_core.atomic_write(found[2] / "linear.json", json.dumps({"feature": feature, "stories": [story]}, indent=2) + "\n")
    slug, wt, proj = found
    meta = _linear(proj)
    if isinstance(meta.get("stories"), list) and story not in meta["stories"]:
        meta["stories"].append(story)
        fc_core.atomic_write(proj / "linear.json", json.dumps(meta, indent=2) + "\n")
    prompt = lead_prompt(story, feature, title, kind)
    lead = fc_reconcile.live_leads(repo).get(slug)
    if lead:
        if not prompt_lead(lead, prompt):
            raise RuntimeError(f"could not prompt {lead}")
    else:
        compose_cli(["crew", "start", "--repo", str(wt), "--project", slug, "--role", "orchestrator", "--title", "orchestrator", "--brief", "-"],
                    stdin=lead_brief(slug, wt, feature, prompt))
    state["dispatched"][story] = {"feature": feature, "project": slug, "kind": kind, "at": now}
    return (f"event factory=dispatched story={story} project={slug} kind={kind}  "
            f"(its team lead builds it; relay it: compose watch --project {slug} --from orchestrator)")
