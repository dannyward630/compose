import json, sys, urllib.request
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
        sys.exit(f"sync --from-linear needs a Linear key for workspace {fc_config.WORKSPACE!r}: pbpaste | fast-coding workspace key {fc_config.WORKSPACE} --linear; "
                 f"or pipe the JSON on stdin to `fast-coding sync --project {proj.name}` ({fc_tasks.SYNC_SHAPE})")
    stories = set(link.get("stories") or [])
    try:
        feature = linear_gql(LINEAR_FEATURE, {"id": link["feature"]})["issue"]
        if not feature:
            sys.exit(f"sync --from-linear: Linear has no issue {link['feature']}")
        issues = []
        for child in linear_children(link["feature"]):
            if stories and child["identifier"] not in stories:
                continue
            issues += [child, *linear_children(child["identifier"])]
    except (RuntimeError, OSError) as e:  # urllib errors name the status, never the key
        sys.exit(f"sync --from-linear: Linear failed ({str(e)[:200]}); the stdin form still works ({fc_tasks.SYNC_SHAPE})")
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
    with urllib.request.urlopen(req, timeout=20) as r:
        out = json.load(r)
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
        fc_core.say(f"linear skipped: workspace {fc_config.WORKSPACE!r} has no Linear key; set it: pbpaste | fast-coding workspace key {fc_config.WORKSPACE} --linear")
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

def linear_roll_up(proj, ident, verified=False):
    """Roll `ident` and its parents up the table. The feature reaches In Review only when verify passed, and the CLI
    never marks the feature Done (that needs the project branch merged)."""
    feature = json.loads((proj / "linear.json").read_text()).get("feature")
    while ident:
        issue = linear_issue(ident)
        target = rollup_state(issue["children"]["nodes"])
        if issue["identifier"] == feature:
            if target in ("In Review", "Done"):
                target = "In Review" if verified else "In Progress"
            if target:
                linear_move(issue, target)
            return
        if target:
            linear_move(issue, target)
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
        if event == "dispatched":
            linear_move(issue, "In Progress")
        elif event == "passed":
            linear_move(issue, "In Review")
            linear_comment(issue, f"Passed: branch `{result['branch']}`, {result['attempts']} attempt(s), ${result['cost']:.4f}, model `{result['model']}`.")
        elif event == "hand_done":
            linear_move(issue, "In Review")
            linear_comment(issue, f"Finished by hand: {result['note']}")
        else:
            linear_move(issue, "In Progress")
            last = (result.get("log") or [{}])[-1]
            tail = (last.get("test_output") or "").strip().splitlines()
            why = last.get("contradiction") or last.get("error") or (tail[-1] if tail else "no detail")
            linear_comment(issue, f"{result['status']} after {result['attempts']} attempt(s) (${result['cost']:.4f}, model `{result['model']}`): {why[:400]}")
        parent = (issue.get("parent") or {}).get("identifier")
        if parent:
            linear_roll_up(proj, parent)
    except Exception as e:  # noqa: BLE001  Linear never stops a run
        fc_core.say(f"linear {meta.get('linear')}: update failed ({str(e)[:200]}); the run goes on")

def linear_merged(feature, metas, project_merged):
    """clean's step through the state table: every task proven merged moves to Done, its story rolls up, and the feature is
    Done once every story is and the project branch is merged; otherwise the feature is left as verify put it. A Canceled
    task stays Canceled. Without a key one line says so; a Linear failure is said and never stops the clean."""
    if not (metas or (feature and project_merged)) or not linear_ready():
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

def linear_verified(proj):
    """verify PASS: the feature moves to In Review once every story is In Review or Done."""
    link = proj / "linear.json"
    if not link.exists() or not fc_config.LINEAR_KEY:
        return
    feature = json.loads(link.read_text()).get("feature")
    try:
        linear_roll_up(proj, feature, verified=True)
    except Exception as e:  # noqa: BLE001
        fc_core.say(f"linear {feature}: update failed ({str(e)[:200]})")


def cmd_sync(a):
    """Store the feature and its tasks, read from Linear (--from-linear) or piped in as JSON, and list them."""
    proj = fc_core.project_dir(a)
    if a.from_linear:
        data = linear_sync_payload(proj)
    else:
        try:
            data = json.load(sys.stdin)
        except json.JSONDecodeError as e:
            sys.exit(f"sync: stdin is not JSON ({e}); expected {fc_tasks.SYNC_SHAPE}")
    tasks = fc_tasks.sync_tasks(proj, data)
    f = fc_tasks.linear_cache(proj)["feature"]
    print(f"{f['id']} {f['title']}: {len(tasks)} task(s) synced")
    for m in tasks:
        print(f"  {m['id']:4} {m['linear']:9} {m['linear_state'][:12]:12} {m['title'][:50]:50} after {m['after'] or '-'}")
