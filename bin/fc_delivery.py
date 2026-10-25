"""`compose delivery`: the product delivery plan across features, read from Linear (seed, order); the plan is a document in the Linear project."""
import json, sys, time

import fc_core, fc_config, fc_linear, fc_linear_cmd, fc_plan, fc_tasks

PRODUCT_TITLE = "Product delivery plan"
NO_PLAN = "no product delivery plan yet: compose delivery seed starts one"
FEATURES_QUERY = """query($p: ID!, $after: String) { issues(first: 50, after: $after, filter: {project: {id: {eq: $p}},
  labels: {some: {name: {eqIgnoreCase: "feature"}}}}) { pageInfo { hasNextPage endCursor } nodes { %s url } } }""" % fc_linear.LINEAR_TREE_FIELDS
ISSUE_QUERY = "query($id: String!) { issue(id: $id) { %s url project { id } } }" % fc_linear.LINEAR_TREE_FIELDS
DOCS_QUERY = """query($p: String!, $after: String) { project(id: $p) { documents(first: 50, after: $after) {
  pageInfo { hasNextPage endCursor } nodes { id title url } } } }"""
DOC_QUERY = "query($id: String!) { document(id: $id) { id title url content } }"

def _issue(n):
    """A Linear issue node as the plan's modules read it."""
    return {"id": n["identifier"], "title": n["title"], "url": n.get("url") or "", "state": n["state"]["name"] or "",
            "labels": [l["name"] for l in n["labels"]["nodes"]], "parent": (n.get("parent") or {}).get("identifier"), "plan_url": None, "stories": [],
            "blockers": [{"id": r["issue"]["identifier"], "state": r["issue"]["state"]["name"] or "",
                          "labels": [l["name"] for l in r["issue"]["labels"]["nodes"]]} for r in n["inverseRelations"]["nodes"] if r["type"] == "blocks"]}

def _paged(query, variables, pick):
    nodes, after = [], None
    while True:
        page = pick(fc_linear.linear_gql(query, {**variables, "after": after}))
        nodes += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return nodes
        after = page["pageInfo"]["endCursor"]

def _tracks_text(content):
    lines = content.split("\n")
    span = fc_plan.section_span(lines, "## Tracks")
    return "\n".join(lines[span[0] + 1:span[1]]).strip() if span else ""

def read_product(repo, tracks=None):
    """{"project", "doc", "tracks", "features"}: the project's features by id with their stories and plan links, and the plan document with its tracks.
    `tracks` stands in for the document's, when they are about to be replaced."""
    proj = fc_linear_cmd.linear_project(repo)
    docs = _paged(DOCS_QUERY, {"p": proj["id"]}, lambda r: r["project"]["documents"])
    found = next((d for d in docs if d["title"] == PRODUCT_TITLE), None)
    doc = fc_linear.linear_gql(DOC_QUERY, {"id": found["id"]})["document"] if found else None
    if tracks is None:
        tracks = fc_plan.parse_tracks(_tracks_text(doc["content"] or "")) if doc else []
    features = {f["id"]: f for f in map(_issue, _paged(FEATURES_QUERY, {"p": proj["id"]}, lambda r: r["issues"]))}
    for ident in (i for t in tracks for i in t["items"] if i not in features):
        n = fc_linear.linear_gql(ISSUE_QUERY, {"id": ident})["issue"]
        if n and (n.get("project") or {}).get("id") == proj["id"]:
            features[ident] = _issue(n)
    plans = {d["title"]: d["url"] for d in docs}
    for f in features.values():
        f["plan_url"] = plans.get(f"{f['id']}: delivery plan") or (plans.get(f"{f['parent']}: delivery plan") if f["parent"] else None)
        if not fc_tasks.blocker_finished(f["state"], f["labels"]):
            f["stories"] = [_issue(s) for s in fc_linear.linear_children(f["id"])]
    return {"project": proj, "doc": doc, "tracks": tracks, "features": features}

def product_plan(repo):
    """The product read from Linear, or None when its document is missing or names no track."""
    product = read_product(repo)
    return product if product["doc"] and product["tracks"] else None

def delivery_order(repo):
    plan = product_plan(repo)
    if not plan:
        sys.exit(NO_PLAN)
    return fc_plan.order_entries(plan["tracks"], plan["features"])

def entry_line(n, e):
    waits = f"; waits on {', '.join(e['waits_on'])}" if e["waits_on"] else ""
    return f"{n}. {e['id']} {e['title']} ({e['state']}; {'feature ' + e['feature'] if e['kind'] == 'story' else 'feature'}, track {e['track']}, wave {e['wave']}{waits})"

def verb_order(a):
    plan = product_plan(a.repo)
    if not plan:
        sys.exit(NO_PLAN)
    entries = fc_plan.order_entries(plan["tracks"], plan["features"])
    for ident in dict.fromkeys(i for t in plan["tracks"] for i in t["items"] if i not in plan["features"]):
        print(f"{ident} is in a track but was not found in Linear: fix the id or drop it from the track", file=sys.stderr)
    print(json.dumps(entries, indent=2) if a.json else "\n".join(entry_line(n, e) for n, e in enumerate(entries, 1)))

def verb_seed(a):
    product = read_product(a.repo)
    print("No product delivery plan yet." if not product["doc"] else f"The product delivery plan has no tracks yet: {product['doc']['url']}")
    open_ = [f for f in sorted(product["features"].values(), key=lambda f: fc_plan.issue_num(f["id"]))
             if not fc_tasks.blocker_finished(f["state"], f["labels"])]
    for f in open_:
        blocked = f", blocked by {', '.join(b['id'] for b in f['blockers'])}" if f["blockers"] else ""
        print(f"- {f['id']} {f['title']} ({f['state']}{blocked}), its plan: {f['plan_url'] or 'none'}")
    print("A first guess at the tracks, from the blocks Linear holds today; play it back as a guess:")
    print(fc_plan.seed_tracks(product["features"]))

DOC_UPDATE = "mutation($id: String!, $content: String!) { documentUpdate(id: $id, input: {content: $content}) { success } }"
DOC_CREATE = "mutation($title: String!, $content: String!, $projectId: String!) { documentCreate(input: {title: $title, content: $content, projectId: $projectId}) { document { id title url content } } }"

def state_path(repo):
    return fc_core.repo_link(repo).with_name("delivery.json")

def last_reconcile(repo):
    """What the last reconcile did, or None when there has been none."""
    path = state_path(repo)
    return json.loads(path.read_text()) if path.exists() else None

def _blocked_comment(added, removed, url):
    parts = ([f"now blocked by {', '.join(added)}"] if added else []) + ([f"no longer blocked by {', '.join(removed)}"] if removed else [])
    return f"{PRODUCT_TITLE} reconcile: {'; '.join(parts)}. The plan wins over Linear; change the plan to change this: {url}"

def reconcile(repo, dry_run=False):
    """Make Linear's blocks and Ready labels follow the plan; destructive fixes are only proposed. Idempotent."""
    plan = product_plan(repo)
    if not plan:
        sys.exit(NO_PLAN)
    tracks, features = plan["tracks"], plan["features"]
    fc_plan.track_waves(tracks)
    plan_ids = {i for t in tracks for i in t["items"]}
    current = {i: [b["id"] for b in f["blockers"]] for i, f in features.items()}
    added, removed = fc_plan.blocks_diff(fc_plan.derived_blocks(tracks), current, plan_ids)
    proposals = fc_plan.product_proposals(tracks, features)
    result = {"added": [list(p) for p in added], "removed": [list(p) for p in removed], "ready": [], "proposed": proposals, "doc": plan["doc"]["url"]}
    if dry_run:
        return result
    for blocked in dict.fromkeys(k for _, k in added + removed):
        gone = {b for b, k in removed if k == blocked}
        new = [b for b, k in added if k == blocked]
        want = sorted({*current[blocked]} - gone | set(new), key=fc_plan.issue_num)
        fc_linear.linear_blocked_by(fc_linear.linear_issue(blocked), want)
        fc_linear.linear_comment(fc_linear.linear_issue(blocked), _blocked_comment(new, sorted(gone, key=fc_plan.issue_num), result["doc"]))
    for item in dict.fromkeys(e["feature"] if e["kind"] == "story" else e["id"] for e in fc_plan.order_entries(tracks, features)):
        for r in fc_linear.linear_mark_ready(item):
            if r["id"] not in result["ready"]:
                result["ready"].append(r["id"])
    content = plan["doc"]["content"] or ""
    for heading, text in fc_plan.product_sections(tracks, features, result["ready"], proposals).items():
        content = fc_plan.replace_section(content, heading, text)
    if content.rstrip("\n") != (plan["doc"]["content"] or "").rstrip("\n"):
        fc_linear.linear_gql(DOC_UPDATE, {"id": plan["doc"]["id"], "content": content})
    fc_core.atomic_write(state_path(repo), json.dumps({**result, "at": fc_core.now()}, indent=2) + "\n")
    return result

def summary(r, dry_run=False):
    head = f"product delivery plan{' (dry run, nothing written)' if dry_run else ''}: {len(r['added'])} blocks added, {len(r['removed'])} removed, " \
           f"{len(r['ready'])} ready, {len(r['proposed'])} proposed"
    return "\n".join([head, *(f"  + {a} blocks {b}" for a, b in r["added"]), *(f"  - {a} no longer blocks {b}" for a, b in r["removed"]),
                      *([f"  ready: {', '.join(r['ready'])}"] if r["ready"] else []), *(f"  proposed: {p}" for p in r["proposed"])])

def _reconciled(repo, dry_run=False):
    try:
        return reconcile(repo, dry_run)
    except RuntimeError as e:
        sys.exit(f"delivery reconcile: {e}; run it again: it only writes what is still out of step")

def verb_reconcile(a):
    print(summary(_reconciled(a.repo, a.dry_run), a.dry_run))

def verb_tracks(a):
    if not a.quote:
        sys.exit('delivery tracks needs --quote "<the product owner\'s words>": the order across features is theirs to set')
    body = fc_linear_cmd.read_body(a)
    tracks = fc_plan.parse_tracks(_tracks_text(body) if "## Tracks" in body else body)
    fc_plan.track_waves(tracks)
    product = read_product(a.repo, tracks)
    unknown = [i for i in dict.fromkeys(i for t in tracks for i in t["items"]) if i not in product["features"]]
    if unknown:
        sys.exit(f"delivery tracks: {', '.join(unknown)} {'is' if len(unknown) == 1 else 'are'} no issue in this project; nothing written")
    doc = product["doc"]
    if not doc:
        doc = fc_linear.linear_gql(DOC_CREATE, {"title": PRODUCT_TITLE, "content": fc_plan.product_skeleton(), "projectId": product["project"]["id"]})["documentCreate"]["document"]
    words = " ".join(a.quote.split())
    content = fc_plan.replace_section(doc["content"] or "", "## Tracks", "## Tracks\n\n" + "\n".join(l.strip() for l in body.strip().splitlines() if l.strip() and not l.startswith("## ")))
    content = fc_plan.with_history(content, f'- {time.strftime("%Y-%m-%d")}: tracks set; the product owner said: "{words}"')
    fc_linear.linear_gql(DOC_UPDATE, {"id": doc["id"], "content": content})
    r = _reconciled(a.repo)
    print(f"tracks set on {r['doc']}\n{summary(r)}")

def cmd_delivery(a):
    if not fc_config.LINEAR_KEY:
        sys.exit(fc_config.needs_linear_key("compose delivery"))
    verb = globals().get(f"verb_{a.action}")
    if not verb:
        sys.exit(f"delivery {a.action}: not available yet")
    try:
        verb(a)
    except ValueError as e:
        sys.exit(f"delivery {a.action}: the Tracks section does not parse: {e}")
    except (RuntimeError, OSError) as e:
        sys.exit(f"delivery {a.action}: {e}")
