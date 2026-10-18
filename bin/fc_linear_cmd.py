"""`compose linear <verb>`: read and write Linear with the workspace key, printing compact text."""
import json, sys
from pathlib import Path

import fc_core, fc_config, fc_linear


def issue_line(issue):
    raise NotImplementedError

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
    raise NotImplementedError

def state_and_labels(team, a):
    raise NotImplementedError

def replace_section(body, heading, text):
    raise NotImplementedError

def verb_project(a):
    p = linear_project(a.repo)
    print(f"{p['name']} on team {p['team']['name']}: {p['url']}")

def verb_get(a):
    raise NotImplementedError

def verb_list(a):
    raise NotImplementedError

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
