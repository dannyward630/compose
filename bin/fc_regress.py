"""A FAST fix inside `run`: one proof round of its regression test, and the pin of a proven test into the task."""
import json
import re

import fc_core
import fc_crew
import fc_fast
import fc_herdr
import fc_linear
import fc_regproof
import fc_regwriter
import fc_tasks
import fc_unproven
import fc_worktree


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
    return result["status"] == "unproven" and "proof" not in result and fc_fast.workflow(proj, meta) == fc_tasks.WORKFLOWS[2]


def end_writer(repo, proj, tid):
    """Release the writer's checkout and branch and report it done."""
    if fc_worktree.use_treehouse():
        fc_worktree.release_slot(repo, fc_worktree.slots(proj)[f"regress-{tid}"])
        fc_worktree.slots(proj, {f"regress-{tid}": None})
    else:
        fc_core.sh(["git", "worktree", "remove", "--force", str(proj / "worktrees" / f"regress-{tid}")], repo)
    fc_core.sh(["git", "branch", "-D", fc_regwriter.writer_branch(proj, tid)], repo)
    fc_crew.write_report(proj, fc_herdr.agent_name(proj.name, f"tests-{tid}"), "done", "regression test proven")


def regress(repo, proj, meta, result, attempts=1):
    """Prove the fix's regression test; the result, `passed` once its proof is saved."""
    tid, proof, saved, passed = meta["id"], result.get("proof"), True, False
    name = fc_herdr.agent_name(proj.name, f"tests-{tid}")
    since = len(fc_crew.crew_reports(proj, name))
    try:
        if proof and fc_unproven.writer_live(proj, tid):
            fc_unproven.reprompt(proj, tid, fc_unproven.prompt_text(proof))
        else:
            fc_regwriter.start_writer(repo, proj, meta, result)
        for n in range(attempts):
            ready = fc_regwriter.wait_ready(proj, tid, since)
            if not ready:
                break
            proof = fc_regproof.prove(repo, proj, meta, result, *ready)
            saved = fc_regproof.record_proof(proj, meta, proof)
            if saved is not True:
                break
            if proof["proven"]:
                passed = True
                break
            if n + 1 < attempts:
                since = len(fc_crew.crew_reports(proj, name))
                fc_unproven.reprompt(proj, tid, fc_unproven.prompt_text(proof))
    except (Exception, SystemExit):
        pass
    out = {**result, "proof": proof}
    if passed and proof and proof["proven"] and saved is True:
        pin_test(proj, meta, proof["paths"], proof["command"])
        end_writer(repo, proj, tid)
        out["status"] = "passed"
    else:
        out["status"] = "unproven"
        out["log"] = [*result.get("log", []), {"error": fc_unproven.reason(proof, saved)}]
    fc_core.atomic_write(proj / "results" / f"{tid}.json", json.dumps(out, indent=2))
    fc_linear.linear_event(proj, meta, out["status"], out)
    return out
