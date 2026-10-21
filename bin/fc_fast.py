"""The FAST route (fix-then-regression-test): its holds before a run, its green-base check, and its run's ledger events."""


def workflow(proj, meta):
    """The task's routed workflow from its issue description in the sync cache; None without a route."""
    raise NotImplementedError("workflow")


def run_holds(repo, proj, tasks, routes):
    """{id: why} for each FAST task with no expected behavior; prints that an implement-then-test task runs as test-first."""
    raise NotImplementedError("run_holds")


def broken_base(proj, meta, red, base_name, branch, wt):
    """The `broken_base` result of a FAST task whose test fails on the base before any change."""
    raise NotImplementedError("broken_base")


def run_events(proj, repo, meta, result):
    """The task's run events for the ledger: a FAST task's carry no `red` event and end `unproven` when it is."""
    raise NotImplementedError("run_events")
