"""compose quick: pin check-only on tasks, a story's tasks, or the feature's code tasks, then route the pinned ones."""
import json, re, sys
from pathlib import Path

import fc_config, fc_core, fc_linear, fc_policy, fc_route, fc_tasks


def cmd_quick(a):
    """Pin `route: check-only` on each task `a.ids` names that is not dispatched, protected, or under a policy, then route them."""
    if not fc_config.LINEAR_KEY:
        sys.exit("quick: no Linear key for this workspace, so no pin was written")
    proj = fc_core.project_dir(a)
    repo = Path(a.repo).resolve()
    cache = fc_tasks.linear_cache(proj)
    issues, tasks = cache.get("issues") or {}, cache["tasks"]
    by_id = {t["id"]: t for t in tasks}
    by_linear = {t["linear"]: t for t in tasks}
    chosen = {}
    for i in a.ids:
        if i == cache["feature"].get("id"):
            for t in fc_tasks.code_tasks(tasks):
                chosen[t["id"]] = t
        elif i in by_linear:
            chosen[by_linear[i]["id"]] = by_linear[i]
        elif i in by_id:
            chosen[i] = by_id[i]
        elif i in issues:  # a story: its tasks are the ones whose synced issue names it as parent
            for t in tasks:
                if (issues.get(t["linear"]) or {}).get("parentId") == i:
                    chosen[t["id"]] = t
        else:
            print(f"{i} skipped: no such task")
    policies = fc_policy.read_policies(repo)[0]
    pinned = []
    for m in sorted(chosen.values(), key=lambda t: t["id"]):
        if m["linear_state"] not in ("Todo", "Backlog"):
            print(f"{m['id']} skipped: already dispatched ({m['linear_state']})")
        elif m["protected"]:
            print(f"{m['id']} skipped: protected test {', '.join(m['protected'])}")
        elif matched := fc_policy.glob_matches(policies, m["files"]):
            print(f"{m['id']} skipped: policy {', '.join(p['name'] for p in matched)} applies")
        else:
            issue = fc_linear.linear_gql("query($id: String!) { issue(id: $id) { id description } }", {"id": m["linear"]})["issue"]
            block = re.search(r"^```compose\n(.*?)^```", issue.get("description") or "", re.M | re.S)
            lines = [l for l in block.group(1).splitlines() if not l.startswith("route:")] + ["route: check-only"]
            new = issue["description"][:block.start(1)] + "\n".join(lines) + "\n" + issue["description"][block.end(1):]
            fc_linear.linear_gql("mutation($id: String!, $in: IssueUpdateInput!) { issueUpdate(id: $id, input: $in) { success } }",
                                 {"id": m["linear"], "in": {"description": new}})
            issues[m["linear"]]["description"] = new
            m["route"] = "check-only"
            pinned.append(m)
            print(f"{m['id']} pinned check-only")
    if pinned:
        fc_core.atomic_write(proj / "results" / "tasks.json", json.dumps(cache, indent=2))
        fc_route.route_tasks(repo, proj, pinned, recalculate=True)
