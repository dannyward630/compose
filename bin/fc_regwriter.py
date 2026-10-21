"""The regression test writer of a FAST task whose fix passed: its branch, brief, start, and ready line."""


def writer_branch(proj, tid):
    """The writer's branch: the project's task prefix plus `regress-<tid>`."""
    raise NotImplementedError("writer_branch")


def writer_brief(meta, diff):
    """The writer's brief: the four instruction lines, the expected behavior, and the fix's diff."""
    raise NotImplementedError("writer_brief")


def start_writer(repo, proj, meta, result):
    """Start the `tests-<tid>` writer on its own branch and checkout off the task's tip; the checkout's path."""
    raise NotImplementedError("start_writer")


READY_RE = None


def parse_ready(message):
    """(commit, command) from the first ready line in `message`; None without one."""
    raise NotImplementedError("parse_ready")


def wait_ready(proj, tid, since=0, poll=5):
    """(commit, command) once the writer reports its test ready; None when it ends, blocks, or is gone without one."""
    raise NotImplementedError("wait_ready")
