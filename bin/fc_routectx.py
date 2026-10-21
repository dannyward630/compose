"""What Jev is shown to route a task: the cheap context first, dependency analysis only on the retry, and the hash that
tells a recorded route is still current."""


def route_context(repo, proj, meta, tasks, issues):
    """The Jev state for one task: task, criteria, files, other_files, story, bug, pin."""
    raise NotImplementedError("route_context")


def dependency_context(repo, meta):
    """{"callers": {path: [file, ...]}} for the task's existing files, or {"unavailable": "<why>"}."""
    raise NotImplementedError("dependency_context")


def context_hash(repo, meta, policies):
    """16 hex chars of sha256 over the task body (Route left out), its files, their blobs at HEAD and the policies."""
    raise NotImplementedError("context_hash")
