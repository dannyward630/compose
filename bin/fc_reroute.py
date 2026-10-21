"""The re-route after implementation: a passed task's route reassessed once per trigger from its real diff, recorded in Linear."""

import fc_core

DEPTHS = ("FAST", "STANDARD", "DEEP")
MARK = "rerouted"


def diff_signals(repo, meta, base, branch):
    """The task's real diff: `{"changed": [{"path", "added", "deleted"}], "lines", "outside", "untouched"}`."""
    out = fc_core.sh(["git", "diff", "--numstat", "--no-renames", f"{base}...{branch}"], repo).stdout.splitlines()
    changed = [{"path": p, "added": int(a) if a.isdigit() else 0, "deleted": int(d) if d.isdigit() else 0} for a, d, p in (l.split("\t", 2) for l in out)]
    files, done = meta["files"], {c["path"] for c in changed}
    return {"changed": changed, "lines": sum(c["added"] + c["deleted"] for c in changed),
            "outside": [c["path"] for c in changed if c["path"] not in files], "untouched": [p for p in files if p not in done]}


def diff_callers(repo, base, branch, meta):
    """`{"callers": {path: [caller paths]}}` of the changed symbols outside `files:`, or `{"unavailable": "<why>"}`."""
    raise NotImplementedError("diff_callers")


def layer_base(repo, proj, tid, trunk):
    """The branch right below task `tid` in the stack, else `trunk`."""
    raise NotImplementedError("layer_base")


def fired(issue):
    """The `(trigger, run id)` pairs of every `* rerouted:` line across the issue's comment pages."""
    raise NotImplementedError("fired")


def reassess(repo, proj, meta, tasks, triggers, run_id, base, branch):
    """One Jev reassessment of the task's depth, floored at the recorded one, then recorded; returns the route."""
    raise NotImplementedError("reassess")


def catch_up(repo, proj, tasks, ids, trunk, kinds):
    """One reassessment per passed task for the triggers of `kinds` not yet fired; `{id: why}` for each route not recorded."""
    raise NotImplementedError("catch_up")


def after_run(repo, proj, results, tasks, trunk):
    """`run`'s hook: catch up the passed results; a `PaymentRequired` is returned, never raised."""
    raise NotImplementedError("after_run")


def before_verify(repo, proj, tasks, trunk):
    """`verify`'s hook before its first stage: catch up the stack, else fail closed."""
    raise NotImplementedError("before_verify")


LEDGER = ("failed tests", "invalid evidence", "unmet requirements")


def ledger_triggers(repo, proj, meta, rows):
    """The `LEDGER` triggers of the task's counted rows, each once in `LEDGER` order."""
    raise NotImplementedError("ledger_triggers")


def after_round(repo, proj, trunk):
    """After a verify round's stages: (the ids whose recorded depth rose, `{id: why}`)."""
    raise NotImplementedError("after_round")
