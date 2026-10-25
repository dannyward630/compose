"""`compose reconcile list | check | show`: sort every open ticket of a messy Linear project once, check the sheet, and render it as one proposal."""
import json, sys
from pathlib import Path

import fc_core, fc_config, fc_linear, fc_linear_cmd

SORTS = ("keep", "cancel", "merge", "verify")
LABELS = ("Epic", "Feature", "Story")
RUNNING = ("In Progress", "In Review")
INVENTORY_QUERY = ('query($after: String, $project: ID) { issues(first: 100, after: $after, filter: {project: {id: {eq: $project}}, '
                   'state: {type: {nin: ["completed", "canceled"]}}}) { pageInfo { hasNextPage endCursor } nodes { identifier title state { name } labels { nodes { name } } parent { identifier } } } }')

def sheet_path(project_id):
    return Path.home() / ".compose" / "reconcile" / f"{project_id}.json"

def inventory(repo):
    """The project and every issue of it that is not completed or canceled, all pages, ordered by issue number."""
    project = fc_linear_cmd.linear_project(repo)
    nodes, after = [], None
    while True:
        page = fc_linear.linear_gql(INVENTORY_QUERY, {"after": after, "project": project["id"]})["issues"]
        nodes += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    nodes.sort(key=lambda n: int(n["identifier"].rsplit("-", 1)[-1]))
    return project, [{"id": n["identifier"], "title": n["title"], "state": n["state"]["name"], "labels": [l["name"] for l in n["labels"]["nodes"]],
                      "parent": (n.get("parent") or {}).get("identifier")} for n in nodes]

def render_tree(issues):
    ids = {i["id"] for i in issues}
    kids = {}
    for i in issues:
        kids.setdefault(i["parent"] if i["parent"] in ids else None, []).append(i)
    out = []
    def walk(parent, depth):
        for i in kids.get(parent, []):
            out.append(f"{'  ' * depth}{i['id']} {i['state']} {','.join(i['labels']) or '-'} {i['title']}")
            walk(i["id"], depth + 1)
    walk(None, 0)
    return "\n".join(out)

def read_text_file(what, path):
    p = Path(path).expanduser()
    if not p.is_file():
        sys.exit(f"{what}: no file {path}")
    return p.read_text()

def load_sheet(path):
    """The sheet normalized, with every reason and body path read into its text."""
    raw = json.loads(read_text_file("sheet", path))
    return {"keep": list(raw.get("keep") or []), "verify": list(raw.get("verify") or []), "tickets": [dict(t) for t in raw.get("tickets") or []],
            "reasons": {k: read_text_file(f"reason {k}", p) for k, p in (raw.get("reasons") or {}).items()},
            "new": [{**n, "body": read_text_file(f"new ticket {n.get('key')} body", n["body"]) if n.get("body") else ""} for n in raw.get("new") or []]}

def explicit(sheet):
    """Every entry the sheet sorts by hand, in order: the keep and verify lists first, then the tickets."""
    return [{"id": i, "sort": "keep"} for i in sheet["keep"]] + [{"id": i, "sort": "verify"} for i in sheet["verify"]] + list(sheet["tickets"])

def expand(sheet, issues):
    """id to its effective entry; a subtree cancel reaches each open descendant not sorted on its own, marked with the root it came from."""
    out = {}
    for e in explicit(sheet):
        out.setdefault(e["id"], e)
    kids = {}
    for i in issues:
        kids.setdefault(i["parent"], []).append(i["id"])
    for e in explicit(sheet):
        if e["sort"] == "cancel" and e.get("subtree"):
            todo = list(kids.get(e["id"], []))
            while todo:
                c = todo.pop(0)
                if c not in out:
                    out[c] = {"id": c, "sort": "cancel", "reason": e.get("reason"), "under": e["id"]}
                todo += kids.get(c, [])
    return out

def entry_problems(e, by_id, got, sheet):
    i, sort = e["id"], e.get("sort")
    if sort not in SORTS:
        return [f"{i} has sort {sort!r}, not one of {' '.join(SORTS)}"]
    out = []
    if sort == "verify" and any(e.get(k) for k in ("title", "drop_ready", "deep_dive")):
        out.append(f"{i} is sorted verify: it takes no changes")
    elif sort != "keep" and any(e.get(k) for k in ("title", "drop_ready", "deep_dive")):
        out.append(f"{i} is sorted {sort}: title, drop_ready and deep_dive belong to keep")
    if sort == "cancel" and not e.get("reason"):
        out.append(f"{i} is canceled without a reason")
    if e.get("reason") and not sheet["reasons"].get(e["reason"], "").strip():
        out.append(f"reason {e['reason']} has no text")
    if sort == "keep" and e.get("drop_ready"):
        if "Ready" not in by_id.get(i, {}).get("labels", []):
            out.append(f"{i} drops Ready but does not carry it")
        if not e.get("reason"):
            out.append(f"{i} drops Ready without a reason")
    if sort == "merge":
        into = e.get("into")
        if not into:
            out.append(f"{i} is merged without a ticket to merge into")
        elif into == i:
            out.append(f"{i} merges into itself")
        elif got.get(into, {}).get("sort") == "cancel":
            out.append(f"{i} merges into {into}, which this sheet cancels")
        elif got.get(into, {}).get("sort") not in ("keep", "verify"):
            out.append(f"{i} merges into {into}, which this sheet does not keep or verify")
    return out

def check_sheet(sheet, issues):
    """Every problem with the sheet against the open tickets, empty when it is good."""
    by_id = {i["id"]: i for i in issues}
    problems, seen = [], set()
    for e in explicit(sheet):
        if e["id"] in seen:
            problems.append(f"{e['id']} is sorted twice")
        elif e["id"] not in by_id:
            problems.append(f"{e['id']} is not an open ticket of this project")
        seen.add(e["id"])
    got = expand(sheet, issues)
    for e in explicit(sheet):
        if e["id"] in by_id:
            problems += entry_problems(e, by_id, got, sheet)
    problems += [f"{i['id']} is open and not sorted" for i in issues if i["id"] not in got]
    kept, keys = {i for i, e in got.items() if e["sort"] == "keep"}, set()
    for n in sheet["new"]:
        if n.get("parent") not in kept and n.get("parent") not in keys:
            problems.append(f"new {n.get('key')} has parent {n.get('parent')}, which is neither a kept open ticket nor an earlier new ticket")
        if n.get("label") not in LABELS:
            problems.append(f"new {n.get('key')} has label {n.get('label')!r}, not one of {', '.join(LABELS)}")
        keys.add(n.get("key"))
    return problems

def counts(got):
    return {s: sum(1 for e in got.values() if e["sort"] == s) for s in SORTS}

def summary(got, sheet):
    c = counts(got)
    return f"{len(got)} open tickets sorted ({c['keep']} kept, {c['verify']} to verify, {c['cancel']} canceled, {c['merge']} merged), {len(sheet['new'])} new"

def grouped(entries, reasons, line):
    """Bullets grouped by reason, each group under its reason text."""
    groups = {}
    for e in entries:
        groups.setdefault(e.get("reason"), []).append(e)
    return "\n\n".join((reasons[k].strip() + "\n\n" if k in reasons else "") + "\n".join(line(e) for e in es) for k, es in groups.items())

def render_proposal(stored):
    sheet, issues = stored, stored["issues"]
    by_id = {i["id"]: i for i in issues}
    got = expand(sheet, issues)
    t = lambda i: f"{i} {by_id[i]['title']}"
    of = lambda sort: [e for e in got.values() if e["sort"] == sort]
    under = lambda root: sum(1 for e in got.values() if e.get("under") == root)
    def cancel_line(e):
        n = under(e["id"])
        return f"- {t(e['id'])}" + (f", and the {n} open ticket{'s' if n != 1 else ''} under it" if n else "")
    stops = [e for e in of("cancel") + of("merge") if by_id[e["id"]]["state"] in RUNNING]
    keeps = of("keep")
    sections = [
        ("Cancel", grouped([e for e in of("cancel") if "under" not in e], sheet["reasons"], cancel_line)),
        ("Merge", grouped(of("merge"), sheet["reasons"], lambda e: f"- {t(e['id'])}, into {t(e['into'])}")),
        ("Running work this stops", "\n".join(f"- {t(e['id'])} ({by_id[e['id']]['state']})" for e in stops)),
        ("Rename", "\n".join(f'- {e["id"]}: "{by_id[e["id"]]["title"]}" becomes "{e["title"]}"' for e in keeps if e.get("title"))),
        ("Ready removed (needs shaping)", grouped([e for e in keeps if e.get("drop_ready")], sheet["reasons"], lambda e: f"- {t(e['id'])}")),
        ("Label deep-dive", "\n".join(f"- {t(e['id'])}" for e in keeps if e.get("deep_dive"))),
        ("New tickets", "\n".join(f"- {n['key']} {n['title']} ({n['label']} under {n['parent']}, needs shaping" + (", deep-dive" if n.get("deep_dive") else "") + ")" for n in sheet["new"])),
        ("Left for you to verify", "\n".join(f"- {t(e['id'])}" for e in of("verify"))),
        ("Keep", "\n".join(f"- {t(e['id'])}" for e in keeps if not (e.get("title") or e.get("drop_ready") or e.get("deep_dive")))),
    ]
    c = counts(got)
    head = f"{len(got)} open tickets: {c['keep']} kept, {c['verify']} left for you to verify, {c['cancel']} canceled, {c['merge']} merged; {len(sheet['new'])} new."
    return "\n\n".join([head] + [f"## {name}\n\n{body}" for name, body in sections if body]) + "\n"

def read_stored(project):
    p = sheet_path(project["id"])
    return json.loads(p.read_text()) if p.exists() else None

def verb_list(a):
    print(render_tree(inventory(a.repo)[1]))

def verb_check(a):
    if not a.file:
        sys.exit("reconcile check needs --file <sheet>")
    project, issues = inventory(a.repo)
    sheet = load_sheet(a.file)
    stored = read_stored(project)
    if stored and 0 < len(stored["applied"]) < len(expand(stored, stored["issues"])):
        sys.exit(f"a reconcile is half applied ({len(stored['applied'])} of {len(expand(stored, stored['issues']))}): "
                 f'finish it with compose reconcile apply --go "<their words>" first')
    problems = check_sheet(sheet, issues)
    if problems:
        sys.exit("\n".join(problems))
    path = sheet_path(project["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    fc_core.atomic_write(path, json.dumps({**sheet, "project": {"id": project["id"], "name": project["name"]}, "checked_at": fc_core.now(),
                                           "issues": issues, "go": [], "applied": {}, "created": {}}, indent=1))
    print(f"checked: {summary(expand(sheet, issues), sheet)}; compose reconcile show prints the proposal")

def verb_show(a):
    project = fc_linear_cmd.linear_project(a.repo)
    stored = read_stored(project)
    if not stored:
        sys.exit(f"no checked reconcile for {project['name']}: compose reconcile check --file <sheet> first")
    print(render_proposal(stored), end="")

def cmd_reconcile(a):
    if not fc_config.LINEAR_KEY:
        sys.exit(fc_config.needs_linear_key("compose reconcile"))
    verb = globals().get(f"verb_{a.action}")
    if not verb:
        sys.exit(f"reconcile {a.action}: not available yet")
    try:
        verb(a)
    except (RuntimeError, OSError) as e:
        sys.exit(f"reconcile {a.action}: {e}")
