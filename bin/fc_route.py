"""`compose route`: each task's workflow and depth, project policies first, Jev for the rest; recorded on the task issue
when the workspace has a Linear key, printed only without one."""
import sys


def route_tasks(repo, proj, tasks, recalculate=False):
    """Route each task, print one line per task, record it with a Linear key. Returns ({id: route}, {id: why held})."""
    raise NotImplementedError("route_tasks")


def record_route(proj, meta, section):
    """Write the section into the task issue's description, post it as a comment, and update the sync cache."""
    raise NotImplementedError("record_route")


def cmd_route(a):
    """Route the project's tasks: --only NNN[,NNN], --recalculate."""
    sys.exit("route: not implemented")
