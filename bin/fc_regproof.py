"""The proof of a regression test: its run on the base and on the fix, and its ledger rows."""

import re

import fc_jev

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
    raise NotImplementedError("prove")


def record_proof(proj, meta, proof):
    """Save a proof's red and final rows on the task's ledger; add_row's answer."""
    raise NotImplementedError("record_proof")
