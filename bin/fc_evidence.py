"""The evidence ledger's read side: the rows of an issue's evidence comments, and the `## Evidence` section of its
description derived from them. fc_ledger writes the rows."""
import json
import re

import fc_linear

BLOCK = re.compile(r"```evidence\n(.*?)\n```", re.S)
COMMENTS = "query($id: String!, $after: String) { issue(id: $id) { comments(first: 100, after: $after) { pageInfo { hasNextPage endCursor } nodes { body createdAt } } } }"

def parse_comment(body):
    """The rows of every `evidence` block in a comment body."""
    out = []
    for block in BLOCK.findall(body):
        for line in block.splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if isinstance(r, dict):
                out.append(r)
    return out

def rows(issue, task_id=None, run_id=None, criterion_id=None):
    """Every evidence row of the issue's comments, once each, oldest first, filtered by task, run, or criterion."""
    if not issue or not fc_linear.linear_ready():
        return []
    out, seen, cursor = [], set(), None
    while True:
        cs = fc_linear.linear_gql(COMMENTS, {"id": issue, "after": cursor})["issue"]["comments"]
        for c in cs["nodes"]:
            for r in parse_comment(c["body"]):
                if r["event_id"] in seen:
                    continue
                seen.add(r["event_id"])
                r["at"] = c["createdAt"]
                out.append(r)
        if not cs["pageInfo"]["hasNextPage"]:
            break
        cursor = cs["pageInfo"]["endCursor"]
    out = [r for r in out if (not task_id or not r.get("task_ids") or task_id in r["task_ids"])
           and (not run_id or r.get("run_id") == run_id)
           and (not criterion_id or not r.get("criterion_id") or criterion_id in r["criterion_id"])]
    out.sort(key=lambda r: r["at"])
    return out

def task_rows(issue, feature, task_id):
    """The task issue's rows and the feature issue's rows naming the task or no task, once each, oldest first."""
    raise NotImplementedError("fc_evidence.task_rows")

def table(rows):
    """The `## Evidence` section text: the verdict line and the 60 newest rows."""
    latest = {}
    for r in rows:
        if r["phase"] == "sufficiency":
            for c in r["criterion_id"]:
                latest[c] = r
    verdict = ", ".join(f'{c.split(":")[0]} {latest[c]["result"]}' for c in latest) or "not judged"
    lines = ["## Evidence", "", "Verdict: " + verdict, "",
             "| id | at | source | phase | result | fails on base | criteria | detail |", "|---|---|---|---|---|---|---|---|"]
    for r in rows[::-1][:60]:
        fob = {True: "yes", False: "no", None: "-"}[r["fails_on_base"]]
        crits = ", ".join(c.split(":")[0] for c in r["criterion_id"]) or "all"
        detail = r["detail"].replace("|", "\\|")
        lines.append(f"| {r['event_id']} | {r['at'][:16].replace('T', ' ')} | {r['source']} | {r['phase']} | {r['result']} | {fob} | {crits} | {detail} |")
    return "\n".join(lines) + "\n"

def refresh(issue, select=None):
    """Rewrite the issue description's `## Evidence` section from its rows, or from `select(issue)`, best effort."""
    if not issue or not fc_linear.linear_ready():
        return None
    import fc_core, fc_plan
    try:
        d = fc_linear.linear_gql("query($id: String!) { issue(id: $id) { id description } }", {"id": issue})["issue"]
        new = fc_plan.replace_section(d["description"] or "", "## Evidence", table(select(issue) if select else rows(issue)))
        if new != (d["description"] or ""):
            fc_linear.linear_gql("mutation($id: String!, $d: String!) { issueUpdate(id: $id, input: {description: $d}) { success } }",
                                 {"id": d["id"], "d": new})
    except Exception as e:
        fc_core.say(f"ledger {issue}: Evidence section not refreshed ({str(e)[:200]})")
