"""`compose delivery`: the product delivery plan across features, read from Linear (seed, order); the plan is a document in the Linear project."""
import json, sys

import fc_config, fc_linear, fc_linear_cmd, fc_plan, fc_tasks

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

def read_product(repo):
    """{"project", "doc", "tracks", "features"}: the project's features by id with their stories and plan links, and the plan document with its tracks."""
    proj = fc_linear_cmd.linear_project(repo)
    docs = _paged(DOCS_QUERY, {"p": proj["id"]}, lambda r: r["project"]["documents"])
    found = next((d for d in docs if d["title"] == PRODUCT_TITLE), None)
    doc = fc_linear.linear_gql(DOC_QUERY, {"id": found["id"]})["document"] if found else None
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
