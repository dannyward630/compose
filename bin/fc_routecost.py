"""What each route cost: the task's workflow and depth from its Route section, and its attempts, escalations, fix rounds and dollars."""


def route(proj, meta):
    """`(workflow, depth)` from the Route section of the task's issue in the sync cache, each `-` when missing or unknown."""
    raise NotImplementedError("route")


def rounds(proj):
    """The `rounds` of `results/verify.json`; [] when it is missing or unreadable."""
    raise NotImplementedError("rounds")


def fix_tasks(tasks, files):
    """Ids of the code tasks whose `files` or `protected` hold one of `files`, in task order."""
    raise NotImplementedError("fix_tasks")


def counts(result, rounds, tid):
    """The task's `attempts`, `escalations`, `fix_rounds` and `cost`."""
    raise NotImplementedError("counts")


def summary(rows):
    """The status block of cost per workflow and per depth; [] for no rows."""
    raise NotImplementedError("summary")
