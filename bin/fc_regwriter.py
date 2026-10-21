"""The regression test writer of a FAST task whose fix passed: its branch, brief, start, and ready line."""
import argparse
from pathlib import Path

import fc_config, fc_core, fc_crew, fc_herdr, fc_worktree


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
    tid, branch = meta["id"], writer_branch(proj, meta["id"])
    diff = fc_core.sh(["git", "diff", "HEAD~1", "HEAD"], result["worktree"]).stdout
    fc_core.sh(["git", "branch", "-f", branch, result["branch"]], repo)
    if fc_worktree.use_treehouse():
        path = Path(fc_worktree.slot_on(repo, branch, f"compose:{proj.name}:regress-{tid}"))
        fc_worktree.slots(proj, {f"regress-{tid}": str(path)})
    else:
        path = proj / "worktrees" / f"regress-{tid}"
        fc_core.sh(["git", "worktree", "add", "-q", str(path), branch], repo)
    fc_worktree.ready_checkout(repo, path, install=fc_core.project_config(proj).get("install"))
    model = "tests" if "tests" in fc_config.CREW_MODELS else "groundwork" if "groundwork" in fc_config.CREW_MODELS else None
    fc_crew.cmd_crew(argparse.Namespace(repo=str(repo), project=proj.name, action="start", role=f"tests-{tid}", title=f"tests {tid}",
                                        brief=writer_brief(meta, diff), force=False, cwd=str(path), leased=True, model=model))
    return path


READY_RE = None


def parse_ready(message):
    """(commit, command) from the first ready line in `message`; None without one."""
    raise NotImplementedError("parse_ready")


def wait_ready(proj, tid, since=0, poll=5):
    """(commit, command) once the writer reports its test ready; None when it ends, blocks, or is gone without one."""
    raise NotImplementedError("wait_ready")
