"""The pass gate of a task: what its branch may change (size, documents, files) and what must still pass after it.
Imports only lower modules."""
import re, threading
import fc_core, fc_config, fc_worktree

def branch_budget(wt, base, allowed=None, delete=()):
    """(lines changed vs base counting the working tree, new document files, files outside the task's `files:` list).
    All three are hard limits for an implementer: size, no documents, and scope. A file deleted whole counts one line, as
    does each `delete:` path; files under a `delete:` path count nothing and are never stray."""
    fc_core.sh(["git", "add", "-A"], wt, check=False)
    del_paths = {d.rstrip("/") for d in delete}
    gone = set(fc_core.sh(["git", "diff", "--cached", "--diff-filter=D", "--name-only", base], wt, check=False).stdout.split())
    lines = len(del_paths)
    for row in fc_core.sh(["git", "diff", "--cached", "--numstat", base], wt, check=False).stdout.splitlines():
        a, d, f = row.split("\t", 2)
        if any(f == p or f.startswith(p + "/") for p in del_paths):
            continue
        if f in gone:
            lines += 1
        elif not fc_worktree.GENERATED_RE.search(f):  # lockfiles are regenerated, nobody reads them
            lines += (int(a) if a.isdigit() else 0) + (int(d) if d.isdigit() else 0)
    changed = fc_core.sh(["git", "diff", "--cached", "--name-only", base], wt, check=False).stdout.split()
    new_docs = [f for f in fc_core.sh(["git", "diff", "--cached", "--name-only", "--diff-filter=A", base], wt, check=False).stdout.split()
                if fc_config.DOC_RE.search(f)]
    stray = [f for f in changed if allowed is not None and f not in allowed and f not in new_docs
             and not any(f == p or f.startswith(p + "/") for p in del_paths)]
    return lines, new_docs, stray

FAILING_RE = re.compile(r"^\s*(?:(?:FAIL|ERROR): |FAILED |not ok \d+ - |--- FAIL: )(\S.*?)(?: \(\d[\d.]*s\))?\s*$", re.M)  # unittest, pytest, node --test, go test
BASELINES, BASELINE_LOCK = {}, threading.Lock()

def check_state(run, cmds, wt, limit):
    """What each of the project's checks does in this checkout: its exit code and the failing test ids it printed. `run` is fc_implement.timed."""
    state = {}
    for cmd in cmds:
        r = run(cmd, wt, limit, env=fc_core.clean_env())
        state[cmd] = {"exit": r.returncode, "failing": sorted(set(FAILING_RE.findall(r.stdout + r.stderr)))}
    return state

def baseline_state(run, cmds, wt, base, limit):
    """check_state on a task's base, once per base: tasks that start from the same commit share it. None when the project has no checks."""
    if not cmds:
        return None
    with BASELINE_LOCK:
        if (base, tuple(cmds)) not in BASELINES:
            BASELINES[base, tuple(cmds)] = check_state(run, cmds, wt, limit)
        return BASELINES[base, tuple(cmds)]

def regressions(before, after):
    """What passed on the base and fails now: a failing test id the base run did not print, or a check that exited 0 and no longer does.
    A check that was already red tells nothing about the task beyond its new failures."""
    broke = []
    for cmd, now in after.items():
        was = before.get(cmd)
        if was and now["exit"] != 0:
            new = [t for t in now["failing"] if t not in was["failing"]]
            broke += new or ([f"`{cmd}` exits {now['exit']}"] if was["exit"] == 0 else [])
    return broke

def advice(broke):
    """The next prompt's problem when a passing task broke something that passed before it."""
    return ("Your change breaks what passed before it. Code outside this task, other tasks' stubs included, must stay as it was; "
            "restore it. Now failing: " + "; ".join(broke[:10]))
