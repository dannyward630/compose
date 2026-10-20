"""`compose linear <verb>`: read and write Linear with the workspace key, printing compact text."""
import json, sys, urllib.parse
from pathlib import Path

import fc_core, fc_config, fc_linear, fc_plan


def issue_line(issue):
    labels = issue["labels"]["nodes"]
    return f"{issue['identifier']} {issue['state']['name']} {labels[0]['name'] if labels else '-'} {issue['title']}"

def read_body(a):
    if a.file:
        return Path(a.file).read_text()
    return "" if sys.stdin.isatty() else sys.stdin.read()

def linear_project(repo):
    path = Path(repo) / ".compose" / "linear.json"
    if not path.exists():
        sys.exit(f"no .compose/linear.json in {repo}")
    link = json.loads(path.read_text())
    name = urllib.parse.urlsplit(link["project"]).path.split("/project/", 1)[-1].strip("/").split("/")[0]
    slug = name.rsplit("-", 1)[-1]
    p = fc_linear.linear_gql("query($slug: String!) { projects(filter: {slugId: {eq: $slug}}) { nodes { id name url teams { nodes { id name key } } } } }",
                             {"slug": slug})["projects"]["nodes"]
    if not p:
        sys.exit(f"Linear has no project {link['project']}")
    p = p[0]
    team = next((t for t in p["teams"]["nodes"] if t["name"] == link["team"]), None)
    if not team:
        sys.exit(f"project {p['name']} is not on team {link['team']}")
    return {"id": p["id"], "name": p["name"], "url": p["url"], "team": {"id": team["id"], "name": team["name"], "key": team["key"]}}

def in_scope(item, a, name=None):
    if a.any_project:
        return
    p = linear_project(a.repo)
    if (item["project"] or {}).get("id") != p["id"]:
        sys.exit(f"{name or item['identifier']} is not in project {p['name']}; pass --any-project to use it")

def state_and_labels(team, a):
    out = {}
    if a.state:
        s = next((s for s in team["states"]["nodes"] if s["name"].lower() == a.state.lower()), None)
        if not s:
            sys.exit(f"team {team['name']} has no state '{a.state}'")
        out["stateId"] = s["id"]
    if a.label:
        ids = []
        for name in a.label:
            l = next((l for l in team["labels"]["nodes"] if l["name"].lower() == name.lower()), None)
            if not l:
                sys.exit(f"team {team['name']} has no label '{name}'; compose linear labels --create {name} makes it")
            ids.append(l["id"])
        out["labelIds"] = ids
    return out

def writes_body(a, verb):
    """Whether the verb writes the body; refuses a flag mix that would write something other than what the caller meant."""
    if sum(bool(x) for x in (a.section, a.append, a.description)) > 1:
        sys.exit(f"{verb} takes one of --section, --append, --description")
    writes = bool(a.section or a.append or a.description)
    if a.file and not writes:  # the body file would be read by nothing
        sys.exit(f"{verb} --file needs --section, --append, or --description")
    return writes

def new_body(a, old):
    body, old = read_body(a), old or ""
    if a.section:
        return fc_plan.replace_section(old, a.section, body)
    if a.append:
        return old.rstrip("\n") + "\n\n" + body.strip() + "\n"
    return body

def verb_project(a):
    writes = writes_body(a, "project")
    p = linear_project(a.repo)
    content = fc_linear.linear_gql("query($id: String!) { project(id: $id) { content } }", {"id": p["id"]})["project"]["content"] if writes or a.body else None
    if writes:
        fc_linear.linear_gql("mutation($id: String!, $in: ProjectUpdateInput!) { projectUpdate(id: $id, input: $in) { success } }",
                             {"id": p["id"], "in": {"content": new_body(a, content)}})
        print(f"updated {p['name']}")
        return
    print(f"{p['name']} on team {p['team']['name']}: {p['url']}")
    if a.body:
        print(content or "")

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
    if not a.title:
        sys.exit("create needs --title")
    p = linear_project(a.repo)
    team = fc_linear.linear_gql("query($id: String!) { team(id: $id) { name states { nodes { id name } } labels(first: 250) { nodes { id name } } } }",
                                {"id": p["team"]["id"]})["team"]
    inp = {"teamId": p["team"]["id"], "projectId": p["id"], "title": a.title, "description": read_body(a)}
    inp.update(state_and_labels(team, a))
    if a.parent:
        inp["parentId"] = fc_linear.linear_issue(a.parent)["id"]
    issue = fc_linear.linear_gql("mutation($in: IssueCreateInput!) { issueCreate(input: $in) { issue { id identifier } } }", {"in": inp})["issueCreate"]["issue"]
    if a.blocked_by:
        fc_linear.linear_blocked_by({"id": issue["id"]}, a.blocked_by.split(","))
    print(f"created {issue['identifier']}")

def verb_update(a):
    if not a.target:
        sys.exit("update needs an issue id")
    writes = writes_body(a, "update")
    if not (writes or a.title or a.parent or a.state or a.label or a.blocked_by is not None):
        sys.exit("update needs --title, --state, --parent, --label, --blocked-by, or a body: --section, --append, or --description with --file or stdin")
    issue = fc_linear.linear_gql("query($id: String!) { issue(id: $id) { id identifier description project { id name } team { name states { nodes { id name } } labels(first: 250) { nodes { id name } } } } }",
                                 {"id": a.target[0]})["issue"]
    in_scope(issue, a)
    inp = {}
    if a.title:
        inp["title"] = a.title
    if a.parent:
        inp["parentId"] = fc_linear.linear_issue(a.parent)["id"]
    inp.update(state_and_labels(issue["team"], a))
    if writes:
        inp["description"] = new_body(a, issue["description"])
    if inp:  # empty only when --blocked-by is the one change
        fc_linear.linear_gql("mutation($id: String!, $in: IssueUpdateInput!) { issueUpdate(id: $id, input: $in) { success } }", {"id": issue["id"], "in": inp})
    if a.blocked_by is not None:
        fc_linear.linear_blocked_by(issue, [x for x in a.blocked_by.split(",") if x])
    print(f"updated {issue['identifier']}")

def verb_comment(a):
    if not a.target:
        sys.exit("comment needs an issue id")
    issue = fc_linear.linear_gql("query($id: String!) { issue(id: $id) { id identifier project { id name } } }",
                                 {"id": a.target[0]})["issue"]
    in_scope(issue, a)
    body = read_body(a).strip()
    if not body:
        sys.exit("comment needs a body: --file <path> or stdin")
    fc_linear.linear_comment(issue, body)
    print(f"commented on {issue['identifier']}")

def verb_labels(a):
    p = linear_project(a.repo)
    if a.create:
        fc_linear.linear_gql("mutation($name: String!, $team: String!) { issueLabelCreate(input: {name: $name, teamId: $team}) { success } }",
                             {"name": a.create, "team": p["team"]["id"]})
        print(f"created label {a.create}")
        return
    team = fc_linear.linear_gql("query($id: String!) { team(id: $id) { labels(first: 250) { nodes { id name } } } }",
                                {"id": p["team"]["id"]})["team"]
    for l in sorted(team["labels"]["nodes"], key=lambda l: l["name"]):
        print(l["name"])

def verb_doc(a):
    if a.target == ["create"]:
        if not a.title:
            sys.exit("doc create needs --title")
        p = linear_project(a.repo)
        doc = fc_linear.linear_gql("mutation($in: DocumentCreateInput!) { documentCreate(input: $in) { document { url } } }",
                                   {"in": {"title": a.title, "content": read_body(a), "projectId": p["id"]}})["documentCreate"]["document"]
        print(doc["url"])
    elif a.target == ["list"]:
        p, after = linear_project(a.repo), None
        while True:
            page = fc_linear.linear_gql("query($id: String!, $after: String) { project(id: $id) { documents(first: 100, after: $after) { pageInfo { hasNextPage endCursor } nodes { id title updatedAt } } } }",
                                        {"id": p["id"], "after": after})["project"]["documents"]
            for d in page["nodes"]:
                print(f"{d['id']} {d['updatedAt'][:10]} {d['title']}")
            if not page["pageInfo"]["hasNextPage"]:
                break
            after = page["pageInfo"]["endCursor"]
    elif len(a.target) == 2 and a.target[0] == "update":
        writes = writes_body(a, "doc update")
        if not writes and not a.title:
            sys.exit("doc update needs --title, --section, --append, or --description")
        doc = fc_linear.linear_gql("query($id: String!) { document(id: $id) { id title content url project { id name } } }",
                                   {"id": a.target[1]})["document"]
        in_scope(doc, a, f"document {doc['title']}")
        inp = {"title": a.title} if a.title else {}
        if writes:
            inp["content"] = new_body(a, doc["content"])
        fc_linear.linear_gql("mutation($id: String!, $in: DocumentUpdateInput!) { documentUpdate(id: $id, input: $in) { success } }", {"id": doc["id"], "in": inp})
        print(f"updated {doc['url']}")
    elif len(a.target) == 2 and a.target[0] == "get":
        doc = fc_linear.linear_gql("query($id: String!) { document(id: $id) { title content url } }",
                                   {"id": a.target[1]})["document"]
        print(doc["title"])
        print(doc["content"])
    else:
        sys.exit("doc takes create, list, get <id>, or update <id>")

def cmd_linear(a):
    if not fc_config.LINEAR_KEY:
        sys.exit(f"compose linear needs a Linear key for workspace {fc_config.WORKSPACE!r}: pbpaste | compose workspace key {fc_config.WORKSPACE} --linear")
    try:
        globals()[f"verb_{a.action}"](a)
    except (RuntimeError, OSError) as e:
        sys.exit(f"linear {a.action}: {e}")
