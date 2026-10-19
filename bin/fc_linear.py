import json, sys, urllib.error, urllib.request
import fc_core, fc_config, fc_tasks


LINEAR_TREE_FIELDS = """identifier title description state { name } parent { identifier }
  inverseRelations(first: 250) { nodes { type issue { identifier } } }"""
LINEAR_FEATURE = "query($id: String!) { issue(id: $id) { %s } }" % LINEAR_TREE_FIELDS
LINEAR_CHILDREN = """query($id: String!, $after: String) { issue(id: $id) { children(first: 50, after: $after) {
  pageInfo { hasNextPage endCursor } nodes { %s } } } }""" % LINEAR_TREE_FIELDS

def linear_children(ident):
    """Every child of an issue with the sync fields, all pages."""
    nodes, after = [], None
    while True:
        page = linear_gql(LINEAR_CHILDREN, {"id": ident, "after": after})["issue"]["children"]
        nodes += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return nodes
        after = page["pageInfo"]["endCursor"]

def linear_sync_payload(proj):
    """The payload `sync` takes on stdin, read from Linear (read-only) for the feature in linear.json: the feature, its
    children, and theirs. A project scoped to stories fetches only those stories' children."""
    link = json.loads((proj / "linear.json").read_text()) if (proj / "linear.json").exists() else {}
    if not link.get("feature"):
        sys.exit(f'{proj / "linear.json"}: needs {{"feature": "<issue id, e.g. ENG-123>"}}, the Linear feature this project builds')
    if not fc_config.LINEAR_KEY:
        sys.exit(f"sync needs a Linear key for workspace {fc_config.WORKSPACE!r}: pbpaste | compose workspace key {fc_config.WORKSPACE} --linear; "
                 f"or pipe the JSON to compose sync --stdin --project {proj.name} ({fc_tasks.SYNC_SHAPE})")
    stories = set(link.get("stories") or [])
    try:
        feature = linear_gql(LINEAR_FEATURE, {"id": link["feature"]})["issue"]
        if not feature:
            sys.exit(f"sync: Linear has no issue {link['feature']}")
        issues = []
        for child in linear_children(link["feature"]):
            if stories and child["identifier"] not in stories:
                continue
            issues += [child, *linear_children(child["identifier"])]
    except (RuntimeError, OSError) as e:  # urllib errors name the status, never the key
        sys.exit(f"sync: Linear failed ({str(e)[:200]}); compose sync --stdin still works ({fc_tasks.SYNC_SHAPE})")
    return {"feature": {"id": feature["identifier"], "title": feature["title"], "description": feature["description"] or ""},
            "issues": [{"id": i["identifier"], "title": i["title"], "description": i["description"] or "", "status": i["state"]["name"],
                        "parentId": i["parent"]["identifier"] if i["parent"] else None,
                        "blockedBy": [r["issue"]["identifier"] for r in i["inverseRelations"]["nodes"] if r["type"] == "blocks"]}
                       for i in issues]}


# ---------- Linear: the CLI keeps the state table true, so the team lead spends no model turn on it ----------
# The key is the active workspace's `linear_api_key`; it goes in a header,
# never argv or a results file. Every call is best effort: a Linear outage prints one line and the run goes on.
LINEAR_URL = "https://api.linear.app/graphql"
LINEAR_ISSUE = """query($id: String!) { issue(id: $id) { id identifier state { name type }
  team { states { nodes { id name type } } } parent { identifier } children { nodes { identifier state { name type } } } } }"""
_linear_warned = []

def linear_gql(query, variables):
    req = urllib.request.Request(LINEAR_URL, data=json.dumps({"query": query, "variables": variables}).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": fc_config.LINEAR_KEY})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            parsed = json.loads(e.read().decode(errors="replace"))
        except ValueError:
            parsed = None
        e.close()
        if isinstance(parsed, dict) and parsed.get("errors"):
            raise RuntimeError("; ".join(x.get("message", "?") for x in parsed["errors"])[:300])
        raise
    if out.get("errors"):
        raise RuntimeError("; ".join(e.get("message", "?") for e in out["errors"])[:300])
    return out["data"]

def linear_issue(ident):
    issue = linear_gql(LINEAR_ISSUE, {"id": ident})["issue"]
    if not issue:
        raise RuntimeError(f"no issue {ident}")
    return issue

def linear_move(issue, state):
    """Move an issue to the team state named `state` (case-insensitive). No-op when it is already there."""
    if (issue["state"]["name"] or "").lower() == state.lower():
        return False
    match = [n for n in issue["team"]["states"]["nodes"] if n["name"].lower() == state.lower()]
    if not match:
        raise RuntimeError(f"{issue['identifier']}: the team has no {state!r} state")
    linear_gql("mutation($id: String!, $s: String!) { issueUpdate(id: $id, input: {stateId: $s}) { success } }",
               {"id": issue["id"], "s": match[0]["id"]})
    fc_core.say(f"linear {issue['identifier']} -> {state}")
    return True

def linear_comment(issue, body):
    linear_gql("mutation($id: String!, $b: String!) { commentCreate(input: {issueId: $id, body: $b}) { success } }",
               {"id": issue["id"], "b": body})

def linear_ready():
    """True when the workspace has a Linear key; otherwise say once how to set it, and the caller skips Linear."""
    if fc_config.LINEAR_KEY:
        return True
    if not _linear_warned:
        _linear_warned.append(1)
        fc_core.say(f"linear skipped: workspace {fc_config.WORKSPACE!r} has no Linear key; set it: pbpaste | compose workspace key {fc_config.WORKSPACE} --linear")
    return False

def linear_note(meta, body):
    """A routine comment on a task's issue (held, released). A failure is said and never stops the command."""
    if not meta or not meta.get("linear") or not linear_ready():
        return
    try:
        linear_comment(linear_issue(meta["linear"]), body)
    except Exception as e:  # noqa: BLE001
        fc_core.say(f"linear {meta['linear']}: comment failed ({str(e)[:200]})")

LINEAR_BLOCKERS = "query($id: String!) { issue(id: $id) { inverseRelations { nodes { id type issue { id identifier } } } } }"

def linear_blocked_by(issue, want):
    """Make exactly the issues in `want` (identifiers) block `issue`."""
    rels = [r for r in linear_gql(LINEAR_BLOCKERS, {"id": issue["id"]})["issue"]["inverseRelations"]["nodes"] if r["type"] == "blocks"]
    have = {r["issue"]["identifier"]: r["id"] for r in rels}
    for ident, rid in have.items():
        if ident not in want:
            linear_gql("mutation($id: String!) { issueRelationDelete(id: $id) { success } }", {"id": rid})
    for ident in want:
        if ident not in have:
            linear_gql("mutation($a: String!, $b: String!) { issueRelationCreate(input: {issueId: $a, relatedIssueId: $b, type: blocks}) { success } }",
                       {"a": linear_issue(ident)["id"], "b": issue["id"]})

def linear_restore(ident, fields):
    """Put an issue's title, description, state, and blockers back as `fields` names them."""
    issue = linear_issue(ident)
    text = {k: fields[k] for k in ("title", "description") if k in fields}
    if text:
        linear_gql("mutation($id: String!, $in: IssueUpdateInput!) { issueUpdate(id: $id, input: $in) { success } }", {"id": issue["id"], "in": text})
    if "status" in fields:
        linear_move(issue, fields["status"])
    if "blockedBy" in fields:
        linear_blocked_by(issue, fields["blockedBy"])

def rollup_state(children):
    """The state table for a story or epic: Done when every child is Done, In Review when every child is In Review or
    Done, In Progress once any child started, else None (leave it). Canceled children do not count."""
    children = [c for c in children if c["state"].get("type") != "canceled"]
    names = [(c["state"]["name"] or "").lower() for c in children]
    if names and all(n == "done" for n in names):
        return "Done"
    if names and all(n in ("in review", "done") for n in names):
        return "In Review"
    if any(c["state"]["type"] in ("started", "completed") for c in children):
        return "In Progress"
    return None

def linear_roll_up(proj, ident, verified=False, moved=None):
    """Roll `ident` and its parents up the table. `moved` ({identifier: state name}) holds the states this step just set;
    they stand over the read, which can still return a child's state from before its move. The feature reaches In Review
    only when verify passed, and the CLI never marks the feature Done (that needs the project branch merged)."""
    feature = json.loads((proj / "linear.json").read_text()).get("feature")
    moved = dict(moved or {})
    while ident:
        issue = linear_issue(ident)
        states = {n["name"].lower(): n for n in issue["team"]["states"]["nodes"]}
        target = rollup_state([{**c, "state": states[moved[c["identifier"]].lower()]} if c["identifier"] in moved else c
                               for c in issue["children"]["nodes"]])
        if issue["identifier"] == feature:
            if target in ("In Review", "Done"):
                target = "In Review" if verified else "In Progress"
            if target:
                linear_move(issue, target)
            return
        if target:
            linear_move(issue, target)
            moved[issue["identifier"]] = target
        ident = (issue.get("parent") or {}).get("identifier")

def linear_event(proj, meta, event, result=None):
    """One task event through the state table: `dispatched` moves the task In Progress, `passed` and `hand_done` In Review
    with a comment, `failed` keeps it In Progress with the failure as a comment; then its story and the feature roll up."""
    if not meta.get("linear"):
        return
    if not linear_ready():
        return
    try:
        issue = linear_issue(meta["linear"])
        state = "In Review" if event in ("passed", "hand_done") else "In Progress"
        linear_move(issue, state)
        if event == "passed":
            linear_comment(issue, f"Passed: branch `{result['branch']}`, {result['attempts']} attempt(s), ${result['cost']:.4f}, model `{result['model']}`.")
        elif event == "hand_done":
            linear_comment(issue, f"Finished by hand: {result['note']}")
        elif event != "dispatched":
            last = (result.get("log") or [{}])[-1]
            tail = (last.get("test_output") or "").strip().splitlines()
            why = last.get("contradiction") or last.get("error") or (tail[-1] if tail else "no detail")
            linear_comment(issue, f"{result['status']} after {result['attempts']} attempt(s) (${result['cost']:.4f}, model `{result['model']}`): {why[:400]}")
        parent = (issue.get("parent") or {}).get("identifier")
        if parent:
            linear_roll_up(proj, parent, moved={issue["identifier"]: state})
    except Exception as e:  # noqa: BLE001  Linear never stops a run
        fc_core.say(f"linear {meta.get('linear')}: update failed ({str(e)[:200]}); the run goes on")

def linear_merged(feature, metas, project_merged):
    """clean's step through the state table: every task proven merged moves to Done, its story rolls up, and the feature is
    Done once every story is and the project branch is merged; otherwise the feature is left as verify put it. A Canceled
    task stays Canceled. With a feature and nothing proven merged one line says the states are unchanged; without a key
    one line says so; a Linear failure is said and never stops the clean."""
    if not feature and not metas:
        return
    if not linear_ready():
        return
    if not (metas or (feature and project_merged)):
        fc_core.say("linear  nothing proven merged; states unchanged")
        return
    try:
        stories = []
        for m in metas:
            issue = linear_issue(m["linear"])
            if issue["state"].get("type") == "canceled":
                continue
            linear_move(issue, "Done")
            parent = (issue.get("parent") or {}).get("identifier")
            if parent and parent != feature and parent not in stories:
                stories.append(parent)
        for s in stories:
            issue = linear_issue(s)
            target = rollup_state(issue["children"]["nodes"])
            if target:
                linear_move(issue, target)
        if feature and project_merged:
            issue = linear_issue(feature)
            if rollup_state(issue["children"]["nodes"]) == "Done":
                linear_move(issue, "Done")
    except Exception as e:  # noqa: BLE001
        fc_core.say(f"linear: moving merged work to Done failed ({str(e)[:200]}); the states are yours to set")

def linear_reconcile(proj, verified=False):
    """The end of a run and verify PASS: every story under the feature rolls up from its tasks again, then the feature from
    its stories, so a roll-up a task event missed (parallel tasks, a read behind the write) is made true. A project scoped to
    stories re-rolls only those. The feature moves to In Review only when `verified`."""
    link = proj / "linear.json"
    if not link.exists() or not fc_config.LINEAR_KEY:
        return
    meta = json.loads(link.read_text())
    feature, scope = meta.get("feature"), set(meta.get("stories") or [])
    try:
        moved = {}
        for child in linear_issue(feature)["children"]["nodes"]:
            if scope and child["identifier"] not in scope:
                continue
            story = linear_issue(child["identifier"])
            target = rollup_state(story["children"]["nodes"])
            if target:
                linear_move(story, target)
                moved[story["identifier"]] = target
        linear_roll_up(proj, feature, verified=verified, moved=moved)
    except Exception as e:  # noqa: BLE001
        fc_core.say(f"linear {feature}: update failed ({str(e)[:200]})")


def ready_ids(issues):
    """The identifiers, in input order, of the issues that can start now: state Todo or Backlog and every `blocks`
    blocker finished (Done or Canceled, or In Review carrying the Design label)."""
    def finished(b):
        s = (b["state"]["name"] or "").lower()
        return s in ("done", "canceled") or (s == "in review" and any(l["name"].lower() == "design" for l in b["labels"]["nodes"]))
    return [i["identifier"] for i in issues
            if (i["state"]["name"] or "").lower() in ("todo", "backlog")
            and all(finished(r["issue"]) for r in i["inverseRelations"]["nodes"] if r["type"] == "blocks")]

LINEAR_READY_TREE = ""

def linear_mark_ready(feature):
    raise NotImplementedError("linear_mark_ready")

def ready_line(items):
    raise NotImplementedError("ready_line")

def cmd_ready(a):
    raise NotImplementedError("cmd_ready")

def refresh_ready(proj, feature=None):
    raise NotImplementedError("refresh_ready")

def linear_feature_after(repo, proj):
    raise NotImplementedError("linear_feature_after")


def cmd_sync(a):
    """Store the feature and its tasks, read from Linear with the workspace key or piped in as JSON (--stdin), and list them."""
    proj = fc_core.project_dir(a)
    if a.stdin:
        try:
            data = json.load(sys.stdin)
        except json.JSONDecodeError as e:
            sys.exit(f"sync: stdin is not JSON ({e}); expected {fc_tasks.SYNC_SHAPE}")
    else:
        data = linear_sync_payload(proj)
    tasks = fc_tasks.sync_tasks(proj, data)
    f = fc_tasks.linear_cache(proj)["feature"]
    print(f"{f['id']} {f['title']}: {len(tasks)} task(s) synced")
    for m in tasks:
        print(f"  {m['id']:4} {m['linear']:9} {m['linear_state'][:12]:12} {m['title'][:50]:50} after {m['after'] or '-'}")
