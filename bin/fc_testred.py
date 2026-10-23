"""The check before a test writer's test is collected: it must fail on the stubs for the reason its task fixes, not because it cannot load."""
import json, re, sys
from pathlib import Path
import fc_core, fc_crew, fc_herdr, fc_models, fc_worktree


# A line that shows the test itself cannot run: a missing module or name, a syntax or compile error. An assertion or a stub's
# "not implemented" is the reason a test is meant to fail for, so none of them is here.
BROKEN_RE = re.compile(
    r"^\s*(?:E\s+)?(?:[\w.]+\.)?(?:ModuleNotFoundError|ImportError|SyntaxError|IndentationError|TabError|NameError|ReferenceError|LoadError)\b[:\s].*$"
    r"|^.*(?:\bCannot find module|\bFailed to resolve import|\berror TS\d+|\berror\[E\d+\]|\bcannot find symbol|\[(?:build|setup) failed\]).*$", re.M)

def broken(output):
    """The first line of a test run's `output` that shows the test cannot run, or ""."""
    hit = BROKEN_RE.search(output or "")
    return hit.group(0).strip() if hit else ""

def run(meta, wt):
    """(exit code, output) of the task's test command in `wt`, through `compose timed`: the same slot, time limit, and scrubbing a teammate's run gets."""
    r = fc_core.sh([sys.executable, str(Path(__file__).with_name("compose.py")), "timed", str(int(meta.get("test_timeout") or fc_models.TEST_TIMEOUT)), "--", meta["test"]],
                   wt, check=False)
    return r.returncode, r.stdout + r.stderr

def sent_back(proj, update=None):
    """The test writers sent back once, by task id, with how many reports they had then (results/tests-sentback.json)."""
    f = Path(proj) / "results" / "tests-sentback.json"
    have = json.loads(f.read_text()) if f.exists() else {}
    if update:
        have.update(update)
        fc_core.atomic_write(f, json.dumps(have, indent=2))
    return have

def gate(proj, meta, writer):
    """Whether the collect of a writer that reported its test ready waits. The test runs in the writer's checkout; one that fails
    because it cannot load (see BROKEN_RE) goes back to its writer once with the error, and the collect leaves it until the
    writer reports ready again. A test that passes, or fails any other way, is collected as before, and so is one that is still
    broken after its one send back, or whose writer cannot be reached: each says so."""
    tid = meta["id"]
    held = fc_worktree.slots(proj).get(f"tests-{tid}")
    wt = Path(held) if held else Path(proj) / "worktrees" / f"tests-{tid}"
    if not wt.exists() or not meta.get("test"):
        return False
    reports, before = len(fc_crew.crew_reports(proj, writer)), sent_back(proj).get(tid)
    live = writer in {a.get("name") for a in fc_herdr.live_agents()}
    if before is not None and reports <= before and live:
        fc_core.say(f"tests-{tid} waits: sent back once, it has not reported test ready again")
        return True
    code, out = run(meta, wt)
    line = broken(out) if code else ""
    if not line:
        return False
    if before is not None or not live:
        fc_core.say(f"tests-{tid} collected although its test fails to load ({line}): " + ("it was sent back once already" if before is not None else "its writer is not running"))
        return False
    text = "\n".join([f"Your test for task {tid} fails because it cannot load, not for the behavior the task adds: {line}",
                      "Output of `" + meta["test"] + "`:", out[-1500:],
                      "Fix the test (a plain new commit), check it fails on the stubs for the missing behavior, and report test ready again."])
    if fc_herdr.herdr("agent", "prompt", writer, text) is None:
        fc_core.say(f"tests-{tid} collected although its test fails to load ({line}): herdr could not reach its writer")
        return False
    sent_back(proj, {tid: reports})
    fc_core.say(f"tests-{tid} sent back to its writer: {line}")
    return True
