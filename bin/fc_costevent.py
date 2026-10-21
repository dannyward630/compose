"""The cost events: one per task at the end of its run and verify's at its end, written through the evidence ledger."""

import fc_ledger
import fc_routecost


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
    raise NotImplementedError("verify_events")
