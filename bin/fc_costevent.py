"""The cost events: one per task at the end of its run and verify's at its end, written through the evidence ledger."""


def detail(workflow, depth, numbers):
    """The event's one-line detail: the route, then attempts, escalations, fix rounds and cost."""
    raise NotImplementedError("detail")


def cost_event(base, workflow, depth, numbers):
    """A ledger event of phase `cost` with `base`'s ids, source and result, then the route and the numbers."""
    raise NotImplementedError("cost_event")


def run_event(proj, meta, result, final):
    """The task's cost event for its run batch; None for a held or hand-done task or without a `final` event."""
    raise NotImplementedError("run_event")


def verify_events(proj, tasks, passed, cost, run_id, commit_sha):
    """Verify's cost events for its final batch."""
    raise NotImplementedError("verify_events")
