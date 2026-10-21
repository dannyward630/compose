"""The proof of a regression test: its run on the base and on the fix, and its ledger rows."""

HARNESS_RE = None


def base_result(proc):
    """(result, fails_on_base) of the regression test's run on the base."""
    raise NotImplementedError("base_result")


def prove(repo, proj, meta, result, commit, command):
    """Run the test commit on a detached base and on the fix; the proof dict."""
    raise NotImplementedError("prove")


def record_proof(proj, meta, proof):
    """Save a proof's red and final rows on the task's ledger; add_row's answer."""
    raise NotImplementedError("record_proof")
