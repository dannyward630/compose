"""`compose linear <verb>`: read and write Linear with the workspace key, printing compact text."""
import json, sys
from pathlib import Path

import fc_core, fc_config, fc_linear


def issue_line(issue):
    labels = issue["labels"]["nodes"]
    return f"{issue['identifier']} {issue['state']['name']} {labels[0]['name'] if labels else '-'} {issue['title']}"

def read_body(a):
    raise NotImplementedError

def linear_project(repo):
    path = Path(repo) / ".compose" / "linear.json"
    if not path.exists():
        sys.exit(f"no .compose/linear.json in {repo}")
    link = json.loads(path.read_text())
    slug = link["project"].rsplit("-", 1)[-1]
    p = fc_linear.linear_gql("query($slug: String!) { projects(filter: {slugId: {eq: $slug}}) { nodes { id name url teams { nodes { id name key } } } } }",
                             {"slug": slug})["projects"]["nodes"]
    if not p:
        sys.exit(f"Linear has no project {link['project']}")
    p = p[0]
    team = next((t for t in p["teams"]["nodes"] if t["name"] == link["team"]), None)
    if not team:
        sys.exit(f"project {p['name']} is not on team {link['team']}")
    return {"id": p["id"], "name": p["name"], "url": p["url"], "team": {"id": team["id"], "name": team["name"], "key": team["key"]}}

def in_scope(issue, a):
    if a.any_project:
        return
    p = linear_project(a.repo)
    if issue["project"]["id"] != p["id"]:
        sys.exit(f"{issue['identifier']} is not in project {p['name']}; pass --any-project to use it")

def state_and_labels(team, a):
    raise NotImplementedError

def replace_section(body, heading, text):
    raise NotImplementedError

def verb_project(a):
    p = linear_project(a.repo)
    print(f"{p['name']} on team {p['team']['name']}: {p['url']}")

def verb_get(a):
    if not a.target:
        sys.exit("get needs an issue id")
    issue = fc_linear.linear_gql("query($id: String!) { issue(id: $id) { identifier title description state { name } labels { nodes { name } } project { id name } parent { identifier } comments { nodes { body createdAt user { name } } } } }",
                                 {"id": a.target[0]})["issue"]
    in_scope(issue, a)
    if a.json:
        print(json.dumps(issue, indent=1))
        return
    print(issue_line(issue))
    if a.body:
        print(issue["description"])
    if a.comments:
        for c in sorted(issue["comments"]["nodes"], key=lambda c: c["createdAt"]):
            print(f"--- {c['user']['name']} {c['createdAt'][:10]}")
            print(c["body"])

def verb_list(a):
    if not a.parent and not a.search:
        sys.exit('list needs --parent <id> or --search "<terms>"')
    f = {"project": {"id": {"eq": linear_project(a.repo)["id"]}}}
    if a.parent:
        f["parent"] = {"id": {"eq": a.parent}}
    if a.search:
        f["searchableContent"] = {"contains": a.search}
    if a.state:
        f["state"] = {"name": {"eqIgnoreCase": a.state}}
    if a.label:
        f["labels"] = {"some": {"name": {"in": a.label}}}
    query = "query($after: String, $f: IssueFilter) { issues(first: 100, after: $after, filter: $f) { pageInfo { hasNextPage endCursor } nodes { identifier title state { name } labels { nodes { name } } } } }"
    nodes, after = [], None
    while True:
        page = fc_linear.linear_gql(query, {"after": after, "f": f})["issues"]
        nodes += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    if a.json:
        print(json.dumps(nodes, indent=1))
        return
    for n in nodes:
        print(issue_line(n))

def verb_create(a):
    raise NotImplementedError

def verb_update(a):
    raise NotImplementedError

def verb_comment(a):
    raise NotImplementedError

def verb_labels(a):
    raise NotImplementedError

def verb_doc(a):
    raise NotImplementedError

def cmd_linear(a):
    if not fc_config.LINEAR_KEY:
        sys.exit(f"compose linear needs a Linear key for workspace {fc_config.WORKSPACE!r}: pbpaste | compose workspace key {fc_config.WORKSPACE} --linear")
    try:
        globals()[f"verb_{a.action}"](a)
    except (RuntimeError, OSError) as e:
        sys.exit(f"linear {a.action}: {e}")
