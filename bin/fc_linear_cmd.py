"""`compose linear <verb>`: read and write Linear with the workspace key, printing compact text."""
import json, sys
from pathlib import Path

import fc_core, fc_config, fc_linear


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

def replace_section(body, heading, text):
    text = text.strip()
    if text.split("\n")[0] == heading:
        text = text[len(heading):].strip()
    section = heading + "\n\n" + text + "\n"
    lines = body.split("\n")
    if heading not in lines:
        return body.rstrip("\n") + "\n\n" + section
    i = lines.index(heading)
    end = next((j for j in range(i + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    head = "\n".join(lines[:i]) + "\n" if i else ""
    return head + section + ("\n" + "\n".join(lines[end:]) if end < len(lines) else "")

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
    if sum(bool(x) for x in (a.section, a.append, a.description)) > 1:
        sys.exit("update takes one of --section, --append, --description")
    issue = fc_linear.linear_gql("query($id: String!) { issue(id: $id) { id identifier description project { id name } team { name states { nodes { id name } } labels(first: 250) { nodes { id name } } } } }",
                                 {"id": a.target[0]})["issue"]
    in_scope(issue, a)
    inp = {}
    if a.title:
        inp["title"] = a.title
    if a.parent:
        inp["parentId"] = fc_linear.linear_issue(a.parent)["id"]
    inp.update(state_and_labels(issue["team"], a))
    if a.section or a.append or a.description:
        body, old = read_body(a), issue["description"] or ""
        if a.section:
            inp["description"] = replace_section(old, a.section, body)
        elif a.append:
            inp["description"] = old.rstrip("\n") + "\n\n" + body.strip() + "\n"
        else:
            inp["description"] = body
    fc_linear.linear_gql("mutation($id: String!, $in: IssueUpdateInput!) { issueUpdate(id: $id, input: $in) { success } }", {"id": issue["id"], "in": inp})
    if a.blocked_by is not None:
        fc_linear.linear_blocked_by(issue, a.blocked_by.split(","))
    print(f"updated {issue['identifier']}")

def verb_comment(a):
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
    elif len(a.target) == 2 and a.target[0] == "get":
        doc = fc_linear.linear_gql("query($id: String!) { document(id: $id) { title content url } }",
                                   {"id": a.target[1]})["document"]
        print(doc["title"])
        print(doc["content"])
    else:
        sys.exit("doc takes create, or get <id>")

def cmd_linear(a):
    if not fc_config.LINEAR_KEY:
        sys.exit(f"compose linear needs a Linear key for workspace {fc_config.WORKSPACE!r}: pbpaste | compose workspace key {fc_config.WORKSPACE} --linear")
    try:
        globals()[f"verb_{a.action}"](a)
    except (RuntimeError, OSError) as e:
        sys.exit(f"linear {a.action}: {e}")
