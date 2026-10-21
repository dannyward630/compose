"""The cost events: one per task at the end of its run and verify's at its end, written through the evidence ledger."""

import fc_ledger
import fc_routecost
import fc_tasks


def detail(workflow, depth, numbers):
    """The event's one-line detail: the route, then attempts, escalations, fix rounds and cost."""
    return f"{workflow} {depth}: attempts {numbers['attempts']}, escalations {numbers['escalations']}, fix rounds {numbers['fix_rounds']}, cost ${numbers['cost']:.4f}"


def cost_event(base, workflow, depth, numbers):
    """A ledger event of phase `cost` with `base`'s ids, source and result, then the route and the numbers."""
    ev = fc_ledger.event(base["run_id"], base["commit_sha"], base["task_ids"], base["criterion_id"], "cost", base["source"], base["result"], None, detail(workflow, depth, numbers))
    ev["workflow"] = workflow
    ev["depth"] = depth
    ev["attempts"] = numbers["attempts"]
    ev["escalations"] = numbers["escalations"]
    ev["fix_rounds"] = numbers["fix_rounds"]
    ev["cost"] = numbers["cost"]
    return ev


def run_event(proj, meta, result, final):
    """The task's cost event for its run batch; None without a `final` event, whatever the status."""
    if final is None:
        return None
    return cost_event(dict(final, source="run"), *fc_routecost.route(proj, meta), fc_routecost.counts(result, [], meta["id"]))


def verify_events(proj, tasks, passed, cost, run_id, commit_sha):
    """Verify's cost events for its final batch: one per code task, then one for verify itself."""
    rs = fc_routecost.rounds(proj)
    code = fc_tasks.code_tasks(tasks)
    base = {"run_id": run_id, "commit_sha": commit_sha, "criterion_id": [], "source": "verify", "result": "pass" if passed else "fail"}
    evs = [cost_event(dict(base, task_ids=[t["id"]]), *fc_routecost.route(proj, t), {"attempts": 0, "escalations": 0, "fix_rounds": fc_routecost.counts({}, rs, t["id"])["fix_rounds"], "cost": 0.0}) for t in code]
    evs.append(cost_event(dict(base, task_ids=[t["id"] for t in code]), "-", "-", {"attempts": 0, "escalations": 0, "fix_rounds": sum("fix_tasks" in r for r in rs), "cost": cost}))
    return evs
