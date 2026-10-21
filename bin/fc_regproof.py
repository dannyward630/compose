"""The proof of a regression test: its run on the base and on the fix, and its ledger rows."""

import re
import subprocess
from pathlib import Path

import fc_implement
import fc_jev
import fc_regwriter
import fc_worktree

HARNESS_RE = re.compile(r"ImportError|ModuleNotFoundError|Failed to import test module|ERROR collecting|errors? during collection")


def base_result(proc):
    """(result, fails_on_base) of the regression test's run on the base."""
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0:
        return "pass", False
    if proc.returncode == 124 or fc_jev.tool_error(output) or HARNESS_RE.search(output):
        return "error", None
    return "fail_expected", True


def prove(repo, proj, meta, result, commit, command):
    """Run the test commit on a detached base and on the fix; the proof dict."""
    tid, wt = meta["id"], Path(result["worktree"])
    wb = fc_regwriter.writer_branch(proj, tid)

    def git(cwd, *a):
        return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)

    def run(path):
        return fc_implement.run_test({**meta, "test": command}, path)

    def tail(proc):
        return ((proc.stdout or "") + (proc.stderr or ""))[-2000:]

    base_sha = git(wt, "rev-parse", "HEAD~1").stdout.strip()
    paths = git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", commit).stdout.split()
    if fc_worktree.use_treehouse():
        path = Path(fc_worktree.slot_on(repo, base_sha, f"compose:{proj.name}:proof-{tid}", detach=True))
    else:
        path = proj / "worktrees" / f"proof-{tid}"
        git(repo, "worktree", "add", "-q", "--detach", str(path), base_sha)
    fc_worktree.ready_checkout(repo, path)
    pick = git(path, "cherry-pick", "-n", commit)
    if pick.returncode:
        base, base_output = ("error", None), tail(pick)
    else:
        proc = run(path)
        base, base_output = base_result(proc), tail(proc)
    if fc_worktree.use_treehouse():
        fc_worktree.release_slot(repo, path)
    else:
        git(repo, "worktree", "remove", "--force", str(path))
    git(wt, "fetch", "-q", str(repo), wb)
    pick = git(wt, "cherry-pick", commit)
    if pick.returncode:
        git(wt, "cherry-pick", "--abort")
        tip_sha, tip_exit, tip_output = "", pick.returncode, tail(pick)
    else:
        tip_sha = git(wt, "rev-parse", "HEAD").stdout.strip()
        proc = run(wt)
        tip_exit, tip_output = proc.returncode, tail(proc)
    proven = base == ("fail_expected", True) and tip_exit == 0
    if proven:
        git(repo, "fetch", "-q", str(wt), f"{result['branch']}:{result['branch']}")
    elif tip_sha:
        git(wt, "reset", "-q", "--hard", "HEAD~1")
    return {"commit": commit, "command": command, "paths": paths, "base_sha": base_sha, "base": base, "base_output": base_output,
            "tip_sha": tip_sha, "tip_exit": tip_exit, "tip_output": tip_output, "proven": proven}


def record_proof(proj, meta, proof):
    """Save a proof's red and final rows on the task's ledger; add_row's answer."""
    raise NotImplementedError("record_proof")
