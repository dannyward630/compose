"""The regression test writer of a FAST task whose fix passed: its branch, brief, start, and ready line."""
import fc_herdr, fc_worktree


def writer_branch(proj, tid):
    """The writer's branch: the project's task prefix plus `regress-<tid>`."""
    return fc_worktree.task_prefix(fc_herdr.project_worktree(proj), proj) + f"regress-{tid}"


def writer_brief(meta, diff):
    """The writer's brief: the four instruction lines, the expected behavior, and the fix's diff."""
    lines = meta["body"].splitlines()
    head = next((n for n, l in enumerate(lines) if l == "## Reproduction"), None)
    if head is None:
        head = next(n for n, l in enumerate(lines) if l == "## Acceptance criteria")
    end = next((n for n in range(head + 1, len(lines)) if lines[n].startswith("## ")), len(lines))
    text = "\n".join(lines[head + 1:end]).strip()
    return (f"Write one regression test for task {meta['id']}: {meta['title']}.\n"
            "The fix below passed. Your test must fail on the base and pass on the fix.\n"
            "Change only test files, in one commit; never edit the fix.\n"
            'Then report working "test ready: <commit> <command>", where <command> runs only your test.\n'
            f"\n## Expected behavior\n{text}\n\n## The fix\n```diff\n{diff}\n```")


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
