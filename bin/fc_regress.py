"""A FAST fix inside `run`: one proof round of its regression test, and the pin of a proven test into the task."""


def pinned(desc, paths, command):
    """`desc` with the test's paths added to `protected:` and ` && <command>` appended to `test:` in its compose block."""
    raise NotImplementedError("pinned")


def pin_test(proj, meta, paths, command):
    """Pin a proven test into the task issue and the sync cache; False when the Linear write failed."""
    raise NotImplementedError("pin_test")


def fast_fix(proj, meta, result):
    """True for an unproven fix-then-regression-test result with no proof yet."""
    raise NotImplementedError("fast_fix")


def end_writer(repo, proj, tid):
    """Release the writer's checkout and branch and report it done."""
    raise NotImplementedError("end_writer")


def regress(repo, proj, meta, result, attempts=1):
    """Prove the fix's regression test; the result, `passed` once its proof is saved."""
    raise NotImplementedError("regress")
