"""The re-route after implementation: a passed task's route reassessed once per trigger from its real diff, recorded in Linear."""

import json
import os
import re

import fc_config
import fc_core
import fc_ledger
import fc_linear
import fc_models
import fc_policy
import fc_route
import fc_routectx
import fc_routejev
import fc_routerec
import fc_tasks
import fc_worktree

DEPTHS = ("FAST", "STANDARD", "DEEP")
MARK = "rerouted"


def diff_signals(repo, meta, base, branch):
    """The task's real diff: `{"changed": [{"path", "added", "deleted"}], "lines", "outside", "untouched"}`."""
    out = fc_core.sh(["git", "diff", "--numstat", "--no-renames", f"{base}...{branch}"], repo).stdout.splitlines()
    changed = [{"path": p, "added": int(a) if a.isdigit() else 0, "deleted": int(d) if d.isdigit() else 0} for a, d, p in (l.split("\t", 2) for l in out)]
    files, done = meta["files"], {c["path"] for c in changed}
    return {"changed": changed, "lines": sum(c["added"] + c["deleted"] for c in changed),
            "outside": [c["path"] for c in changed if c["path"] not in files], "untouched": [p for p in files if p not in done]}


def diff_callers(repo, base, branch, meta):
    """`{"callers": {path: [caller paths]}}` of the changed symbols outside `files:`, or `{"unavailable": "<why>"}`."""
    out = fc_core.sh(["git", "diff", "-U0", "--no-renames", f"{base}...{branch}"], repo, check=False).stdout.splitlines()
    ranges, path = {}, None
    for line in out:
        if line.startswith(("--- ", "+++ ")):
            if "/dev/null" not in line:
                path = line[6:]
                ranges.setdefault(path, [])
        elif line.startswith("@@"):
            a, b = re.match(r"@@ -(\d+)(?:,(\d+))? ", line).groups()
            a, b = int(a), 1 if b is None else int(b)
            ranges[path].append((a, a + max(b, 1) - 1))
    def trail(*args):
        try:
            run = fc_core.sh(["trail", *args, "--json"], repo, check=False)
        except FileNotFoundError:
            raise LookupError("trail not installed")
        if run.returncode:
            raise LookupError(f"trail exited {run.returncode}")
        try:
            return json.loads(run.stdout)
        except ValueError:
            raise LookupError("trail gave unreadable output")

    callers = {}
    try:
        for path, spans in ranges.items():
            if not (repo / path).exists():
                continue
            try:
                names = []
                for e in trail("skeleton", path)["entries"]:
                    first, last = (int(n) for n in re.fullmatch(r"L(\d+)-L(\d+)", e["span"]).groups())
                    if any(first <= hi and lo <= last for lo, hi in spans):
                        names.append(e["name"])
                hits = set()
                for name in names:
                    found = trail("callers", name)
                    hits.update(h["path"] for m in found["matches"] if m["symbol"]["path"] == path for h in m["hits"])
            except (KeyError, TypeError, AttributeError):
                raise LookupError("trail gave unreadable output")
            callers[path] = sorted(hits - set(meta["files"]) - {path})[:20]
    except LookupError as why:
        return {"unavailable": str(why)}
    return {"callers": callers}


def layer_base(repo, proj, tid, trunk):
    """The branch right below task `tid` in the stack, else `trunk`."""
    b = fc_worktree.task_branch(repo, proj, tid)
    prefix = fc_worktree.task_prefix(repo, proj)
    refs = fc_core.sh(["git", "for-each-ref", "--format=%(refname:short)", "--no-merged=HEAD", f"refs/heads/{prefix}*"], repo, check=False).stdout.split()
    metas = {m["id"]: m for m in fc_tasks.code_tasks(fc_tasks.load_tasks(proj))}
    synced = (proj / "results" / "tasks.json").exists()
    ids = [t for t in (r.removeprefix(prefix) for r in refs if re.fullmatch(rf"{re.escape(prefix)}\d+", r)) if t in metas or not synced]
    order = [fc_worktree.task_branch(repo, proj, t) for t in fc_worktree.layer_order([metas.get(t, {"id": t}) for t in ids])]
    i = order.index(b) if b in order else 0
    return order[i - 1] if i > 0 else trunk


def fired(issue):
    """The `(trigger, run id)` pairs of every `* rerouted:` line across the issue's comment pages."""
    query = "query($id: String!, $after: String) { issue(id: $id) { comments(first: 100, after: $after) { pageInfo { hasNextPage endCursor } nodes { body } } } }"
    found, after = set(), None
    while True:
        data = fc_linear.linear_gql(query, {"id": issue, "after": after})
        if data["issue"] is None:
            raise RuntimeError(f"no issue {issue}")
        comments = data["issue"]["comments"]
        for node in comments["nodes"]:
            for line in node["body"].splitlines():
                m = re.fullmatch(r"[*-] rerouted: (.+) \(run (\S+)\)", line.strip())
                if m:
                    found.update((t, m.group(2)) for t in m.group(1).split(", "))
        if not comments["pageInfo"]["hasNextPage"]:
            return found
        after = comments["pageInfo"]["endCursor"]


def reassess(repo, proj, meta, tasks, triggers, run_id, base, branch):
    """One Jev reassessment of the task's depth, floored at the recorded one, then recorded; returns the route."""
    cfg = fc_core.project_config(proj)
    env = {**fc_core.load_env(cfg.get("env_file", fc_config.ENV_FILE)), **os.environ}
    issues = fc_tasks.linear_cache(proj).get("issues", {})
    rec = fc_routerec.parse_route((issues.get(meta["linear"]) or {}).get("description") or "") or {}
    checks = rec.get("verification requirements") or "none"
    recorded = {"workflow": rec.get("workflow"), "depth": rec.get("depth"), "checks": [] if checks == "none" else checks.split(", ")}
    signals = diff_signals(repo, meta, base, branch)
    state = fc_routectx.route_context(repo, proj, meta, tasks, issues)
    state["diff"] = {**signals, **diff_callers(repo, base, branch, meta)}
    state["recorded"] = recorded
    state["triggers"] = list(triggers)
    state["pin"] = recorded["workflow"] or "test-first"
    policies, note = fc_policy.read_policies(repo)
    paths = [c["path"] for c in signals["changed"]]
    route = fc_routejev.decide(env, cfg, state, fc_policy.glob_matches(policies, paths), [p for p in policies if not p["globs"]], lambda: fc_routectx.dependency_context(repo, meta))
    route["checks"] = list(dict.fromkeys(recorded["checks"] + route["checks"]))
    route["note"] = f"{MARK} after {', '.join(triggers)} (run {run_id})"
    kept = recorded["depth"]
    if kept in DEPTHS and DEPTHS.index(kept) > DEPTHS.index(route["depth"]):
        route["depth"] = kept
        route["note"] += f"; depth {kept} kept from the recorded route"
    route["hash"] = fc_routectx.context_hash(repo, meta, policies)
    route["reason"] = fc_routerec.route_reason(route, state)
    section = fc_routerec.route_section(route)
    section += "\n* " + MARK + ": " + ", ".join(triggers) + " (run " + run_id + ")"
    fc_route.record_route(proj, meta, section)
    return route


def catch_up(repo, proj, tasks, ids, trunk, kinds):
    """One reassessment per passed task for the triggers of `kinds` not yet fired; `{id: why}` for each route not recorded."""
    failed = {}
    if not fc_config.LINEAR_KEY:
        return failed
    by_id = {m["id"]: m for m in tasks}
    for id in ids:
        meta = by_id.get(id)
        if not meta or not meta.get("linear"):
            continue
        result = proj / "results" / f"{id}.json"
        try:
            if not result.exists() or json.loads(result.read_text()).get("status") != "passed":
                continue
            run_id = fc_ledger.run_id(proj, id)
            triggers = [t for t in (["diff"] if "diff" in kinds else []) if (t, run_id) not in fired(meta["linear"])]
            if triggers:
                reassess(repo, proj, meta, tasks, triggers, run_id, layer_base(repo, proj, id, trunk), fc_worktree.task_branch(repo, proj, id))
        except fc_models.PaymentRequired:
            raise
        except Exception as e:
            failed[id] = str(e)
    return failed


def after_run(repo, proj, results, tasks, trunk):
    """`run`'s hook: catch up the passed results; a `PaymentRequired` is returned, never raised."""
    ids = [r["id"] for r in results if r["status"] == "passed"]
    if not ids:
        return None
    try:
        whys = catch_up(repo, proj, tasks, ids, trunk, ("diff",))
    except fc_models.PaymentRequired as e:
        return e
    by_id = {m["id"]: m for m in tasks}
    for id, why in whys.items():
        fc_core.say(f"linear {by_id[id]['linear']}: route not recorded ({why})")
    return None


def before_verify(repo, proj, tasks, trunk):
    """`verify`'s hook before its first stage: catch up the stack, else fail closed."""
    raise NotImplementedError("before_verify")


LEDGER = ("failed tests", "invalid evidence", "unmet requirements")


def ledger_triggers(repo, proj, meta, rows):
    """The `LEDGER` triggers of the task's counted rows, each once in `LEDGER` order."""
    raise NotImplementedError("ledger_triggers")


def after_round(repo, proj, trunk):
    """After a verify round's stages: (the ids whose recorded depth rose, `{id: why}`)."""
    raise NotImplementedError("after_round")
