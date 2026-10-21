"""A FAST fix inside `run`: one proof round of its regression test, and the pin of a proven test into the task."""
import json
import re

import fc_core
import fc_linear


def pinned(desc, paths, command):
    """`desc` with the test's paths added to `protected:` and ` && <command>` appended to `test:` in its compose block."""
    def edit(m):
        block = m.group(2)
        have = re.search(r"^protected:[ \t]*(.*)$", block, re.M)
        listed = [p.strip() for p in have.group(1).split(",") if p.strip()] if have else []
        joined = ", ".join(listed + [p for p in paths if p not in listed])
        if have:
            block = block[:have.start()] + "protected: " + joined + block[have.end():]
        else:
            block = re.sub(r"^test:", lambda _: "protected: " + joined + "\ntest:", block, count=1, flags=re.M)
        block = re.sub(r"^(test:.*?)[ \t]*$", lambda t: t.group(1) + " && " + command, block, count=1, flags=re.M)
        return m.group(1) + block + m.group(3)
    return re.sub(r"(```compose\n)(.*?)(```)", edit, desc, count=1, flags=re.S)


def pin_test(proj, meta, paths, command):
    """Pin a proven test into the task issue and the sync cache; False when the Linear write failed."""
    ok = True
    if meta.get("linear"):
        try:
            live = fc_linear.linear_gql("query($id: String!) { issue(id: $id) { id description } }", {"id": meta["linear"]})["issue"]["description"]
            fc_linear.linear_gql("mutation($id: String!, $in: IssueUpdateInput!) { issueUpdate(id: $id, input: $in) { success } }",
                                 {"id": meta["linear"], "in": {"description": pinned(live, paths, command)}})
        except Exception as e:
            ok = False
            fc_core.say("%s pin     Linear update failed: %s" % (meta["id"], e))
    path = proj / "results" / "tasks.json"
    cache = json.loads(path.read_text())
    for t in cache["tasks"]:
        if t["id"] == meta["id"]:
            t["protected"] = t.get("protected", []) + [p for p in paths if p not in t.get("protected", [])]
            t["test"] = t["test"] + " && " + command
    if meta.get("linear"):
        issue = cache["issues"].setdefault(meta["linear"], {})
        issue["description"] = pinned(issue.get("description", ""), paths, command)
    fc_core.atomic_write(path, json.dumps(cache, indent=2))
    return ok


def fast_fix(proj, meta, result):
    """True for an unproven fix-then-regression-test result with no proof yet."""
    raise NotImplementedError("fast_fix")


def end_writer(repo, proj, tid):
    """Release the writer's checkout and branch and report it done."""
    raise NotImplementedError("end_writer")


def regress(repo, proj, meta, result, attempts=1):
    """Prove the fix's regression test; the result, `passed` once its proof is saved."""
    raise NotImplementedError("regress")
