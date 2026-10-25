import re
import fc_tasks, fc_linear, fc_change

DEEP_DIVE = "deep-dive"
MAX_CRITERIA = 5
TAG_RE = re.compile(r"\(readiness check, \d{4}-\d{2}-\d{2}\)")


class NotAStory(Exception):
    pass


READINESS_TREE = """query($id: String!) { issue(id: $id) { id identifier title description state { name } labels { nodes { name } }
  children { nodes { state { name } description } }
  inverseRelations(first: 250) { nodes { type issue { identifier state { name } labels { nodes { name } } } } }
  project { documents(first: 250) { nodes { title content url } } }
  parent { id identifier title description labels { nodes { name } }
    parent { id identifier title description labels { nodes { name } } } } } }"""


def _labels(issue):
    return [l["name"].lower() for l in ((issue or {}).get("labels") or {}).get("nodes") or ()]


def story_chain(tree):
    """The story (the issue read with READINESS_TREE), its feature, its epic (None without a parent labeled epic), its tasks
    (children carrying a compose block) and the project's documents. Raises NotAStory for a task or a non-story."""
    ident = tree["identifier"]
    if fc_tasks.TASK_BLOCK.search(tree.get("description") or ""):
        raise NotAStory(f"{ident} is a task: the planner's task lint judges tasks")
    feature = tree.get("parent")
    if not (feature and "feature" in _labels(feature)) and "story" not in _labels(tree):
        raise NotAStory(f"{ident} is not a story: readiness judges stories (a child of a feature)")
    epic = (feature or {}).get("parent")
    return {"story": tree, "feature": feature, "epic": epic if epic and "epic" in _labels(epic) else None,
            "tasks": [c for c in (tree.get("children") or {}).get("nodes") or () if fc_tasks.TASK_BLOCK.search(c.get("description") or "")],
            "docs": ((tree.get("project") or {}).get("documents") or {}).get("nodes") or []}


def gates(chain):
    """What the story still lacks that needs no judgment, as {"item", "issue", "question"} in a fixed order."""
    story, feature, epic = chain["story"], chain["feature"], chain["epic"]
    out = []

    def add(item, issue, question):
        out.append({"item": item, "issue": issue, "question": question})

    if feature:
        fid = feature["identifier"]
        if not any(f"the design on {fid} is approved" in l for l in fc_change.decision_lines(feature.get("description"))):
            add("design", fid, f"{fid}'s design is not approved yet: shape it with the product owner first (0b).")
    held = [i for i in (story, feature) if i]
    for i in held:
        if any(l.strip().rstrip(".").lower() != "none" for l in fc_change.map_section(i.get("description"), "Not yet specified").splitlines() if l.strip()):
            add("cards", i["identifier"], f"Answer the open cards on {i['identifier']} with compose decide (0b).")
    for i in held:
        n = len([q for q in fc_linear.open_questions(i.get("description")) if not TAG_RE.search(q)])
        if n:
            add("open questions", i["identifier"], f"{i['identifier']} has open questions waiting for the product owner ({n}).")
    sid, n = story["identifier"], len(fc_tasks.parse_criteria(story.get("description")))
    if n == 0:
        add("criteria", sid, f"What must be true when {sid} is done? It has no acceptance criteria.")
    elif n > MAX_CRITERIA:
        add("criteria", sid, f"{sid} has {n} acceptance criteria (at most 5): which thinner stories does it split into?")
    for i in (story, feature, epic):
        if not i or DEEP_DIVE not in _labels(i):
            continue
        iid, desc = i["identifier"], i.get("description") or ""
        doc = next((d for d in chain["docs"] if d.get("title") == f"{iid}: tech doc"), None)
        if not doc:
            add("tech doc", iid, f"{iid} is labeled deep-dive and has no tech doc: run the deep dive with the product owner (0b).")
            continue
        if not doc.get("url") or doc["url"] not in fc_change.map_section(desc, "Tech doc"):
            add("tech doc", iid, f"{iid}'s tech doc is not linked under ## Tech doc.")
        if not any(f"the tech doc on {iid} is approved" in l for l in fc_change.decision_lines(desc)):
            add("tech doc", iid, f"{iid}'s tech doc is not approved yet.")
    return out
