import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, json, os, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock
import sys
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_fast  # noqa: E402


WHY = "no expected behavior: add a Reproduction section or acceptance criteria"
FIX, IMPL = "fix-then-regression-test", "implement-then-test"
FLOWS = {"001": FIX, "002": FIX, "003": FIX, "004": FIX, "005": IMPL, "006": "test-first", "008": FIX, "009": IMPL}  # 007 has no route
CTX = {"001": ([], 0, 0, 0), "002": (["c"], 0, 0, 0), "003": ([], 0, 1, 0), "004": ([], 0, 0, 1), "008": ([], 1, 0, 0)}  # criteria, label, documented, confirmed


class RunHolds(unittest.TestCase):
    """run holds a FAST task with no expected behavior, and prints that an implement-then-test task runs as test-first."""
    def setUp(self):
        self.routectx, self.routerec = (importlib.import_module(m) for m in ("fc_routectx", "fc_routerec"))  # the foundation's modules, not on every branch
        self.repo = Path(tempfile.mkdtemp()).resolve(); self.proj = self.repo / ".compose" / "p"; (self.proj / "results").mkdir(parents=True)
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=self.repo, check=True, capture_output=True)
        git("init", "-q", "-b", "main"); (self.repo / "a.txt").write_text("x"); git("add", "-A"); git("commit", "-qm", "init")
        (self.repo / ".git" / "info" / "exclude").write_text("/.compose/\n")
        self.tasks = [{"id": t, "title": t, "files": [], "protected": [], "test": "true", "body": "no route here", "model": "m", "after": "", "linear": f"ENG-{t}", "waits_on": []} for t in sorted([*FLOWS, "007"])]
        self.issues = {f"ENG-{t}": {"description": f"## Route\n\n* workflow: {FLOWS[t]}" if t in FLOWS else "## Goal\nx"} for t in sorted([*FLOWS, "007"])}
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": self.tasks, "issues": self.issues}))
        self.routes = {t: {"workflow": w} for t, w in reversed(FLOWS.items())}
        ctx = lambda repo, proj, meta, tasks, issues: {"criteria": CTX[meta["id"]][0], "bug": dict(zip(("label", "documented", "confirmed"), map(bool, CTX[meta["id"]][1:])))}
        self.ctx = mock.patch.object(self.routectx, "route_context", side_effect=ctx).start()  # a KeyError says it was asked about a task that is not FAST
        self.say = mock.patch.object(fc.fc_core, "say").start()
        mock.patch.object(self.routerec, "parse_route", side_effect=lambda d: {"workflow": d.split("workflow: ")[1]} if "workflow: " in d else None).start()
        self.addCleanup(mock.patch.stopall)

    def test_holds_a_fast_task_with_no_reproduction_confirmed_case_or_criterion_and_says_implement_then_test_runs_as_test_first(self):
        held = fc_fast.run_holds(self.repo, self.proj, self.tasks, self.routes)
        self.assertEqual(held, {"001": WHY, "008": WHY})  # a Bug label alone is no expected behavior
        self.assertEqual([c.args for c in self.say.call_args_list], [(f"{t} route   implement-then-test is not implemented yet: it runs as test-first",) for t in ("005", "009")])
        self.assertEqual(self.ctx.call_args_list[0].args, (self.repo, self.proj, self.tasks[0], self.tasks, self.issues))

    def test_run_waits_the_held_task_on_the_route_and_still_dispatches_every_task_unchanged(self):
        a = mock.Mock(repo=str(self.repo), project="p", only=None, redo=False, unproven=True, no_stack=True)
        with mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch.object(fc.fc_herdr, "project_worktree", return_value=self.repo), \
             mock.patch.object(fc.fc_route, "route_tasks", return_value=(self.routes, {"006": "boom"})), mock.patch.object(fc.fc_run, "run_tasks") as run_tasks:
            fc.fc_run.cmd_run(a)
        metas = run_tasks.call_args.args[2]
        self.assertEqual({m["id"]: m["waits_on"] for m in metas}, {t: {"001": [f"the route ({WHY})"], "008": [f"the route ({WHY})"], "006": ["the route (boom)"]}.get(t, []) for t in sorted([*FLOWS, "007"])})

    def test_workflow_reads_the_cache_description_and_is_none_without_a_route_or_an_issue(self):
        t = self.tasks
        got = [fc_fast.workflow(self.proj, m) for m in (t[0], t[4], t[6], {**t[0], "linear": "ENG-x"}, {"id": "010"})]
        self.assertEqual(got, [FIX, IMPL, None, None, None])


class FastAttempts(unittest.TestCase):
    """A FAST task needs a green base: its existing tests pass before the fix, and the fix ends unproven."""
    def run_task(self, workflow, test, write="ok\n"):
        """Runs task 001 in a real repo whose a.txt is `ok`; the implementer writes `write` into it. Returns the result, with calls, sent, closed and repo on self."""
        self.repo = Path(tempfile.mkdtemp()).resolve(); proj = self.repo / ".compose" / "p"; proj.mkdir(parents=True); self.proj = proj
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=self.repo, check=True, capture_output=True)
        git("init", "-q", "-b", "main"); (self.repo / "a.txt").write_text("ok\n"); git("add", "-A"); git("commit", "-qm", "init")
        meta = {"id": "001", "title": "t", "files": ["a.txt"], "protected": [], "test": test, "model": "m", "after": "", "linear": "ENG-1", "body": "## Goal\nFix it."}
        self.calls, self.closed = [], []
        def impl(cwd, model, prompt, session=None, task=None, timeout=None):
            self.calls.append(prompt); (Path(cwd) / "a.txt").write_text(write)
            return {"pane": "p1"}, "", 1, {"tokens_in": 1, "tokens_out": 1, "cost": 0.0}
        with mock.patch.object(fc_fast, "workflow", return_value=workflow), mock.patch.object(fc.fc_implement, "implementer", impl), \
             mock.patch.object(fc.fc_implement, "trail_pack", return_value=""), mock.patch.object(fc.fc_config, "TEST_READER", None), \
             mock.patch.object(fc.fc_linear, "linear_event") as self.events, mock.patch.object(fc.fc_core, "say") as self.say, mock.patch.object(fc.fc_herdr, "herdr_label"), \
             mock.patch.object(fc.fc_herdr, "herdr", side_effect=lambda *a, **k: self.closed.append(a)), mock.patch.dict(os.environ, {"COMPOSE_NO_TREEHOUSE": "1"}):
            r = fc.fc_implement.run_task(self.repo, proj, meta, 1)
        self.sent = [c.args[2:] for c in self.events.call_args_list]  # (event, result?) of each linear_event
        return r

    def test_a_fast_task_failing_on_head_is_broken_base_with_no_turn_and_no_base_key(self):
        r = self.run_task(FIX, "echo boom; exit 3")
        self.assertEqual((r["status"], r["attempts"], self.calls, "base" in r), ("broken_base", 0, [], False))
        self.assertEqual(r["log"], [{"base_exit": 3, "test_output": "boom\n"}])
        self.assertEqual(json.loads((self.proj / "results" / "001.json").read_text()), r)
        self.assertEqual(self.say.call_args_list[-1].args, ("001 broken  test exits 3 on HEAD before any change: an environment problem, so no implementer turn",))
        self.assertEqual(self.sent, [("failed", r)])

    def test_a_fast_attempt_that_passes_ends_unproven_with_its_branch_fetched_and_its_pane_closed(self):
        r = self.run_task(FIX, "grep -q ok a.txt", write="ok fixed\n")
        self.assertEqual((r["status"], r["attempts"], len(self.calls), self.sent[-1:]), ("unproven", 1, 1, [("unproven", r)]))
        self.assertEqual(subprocess.run(["git", "show", f"{r['branch']}:a.txt"], cwd=self.repo, capture_output=True, text=True).stdout, "ok fixed\n")
        self.assertEqual(self.closed, [("pane", "close", "p1")])
        self.assertEqual(self.say.call_args_list[-1].args[0].split()[:2], ["001", "unproven"])

    def test_a_fast_attempt_that_fails_stays_failed(self):
        r = self.run_task(FIX, "grep -q ok a.txt", write="no\n")
        self.assertEqual((r["status"], [e for e, *_ in self.sent][-1:]), ("failed", ["failed"]))

    def test_a_test_first_task_still_skips_a_green_base_and_passes_a_red_one(self):
        for flow in (None, "test-first"):
            with self.subTest(flow=flow):
                r = self.run_task(flow, "grep -q ok a.txt")
                self.assertEqual((r["status"], self.calls, self.sent), ("already_green", [], []))
                r = self.run_task(flow, "grep -q fixed a.txt", write="fixed\n")
                self.assertEqual((r["status"], len(self.calls), [e for e, *_ in self.sent]), ("passed", 1, ["dispatched", "passed"]))


class UnprovenLinear(unittest.TestCase):
    """An unproven task stays In Progress on Linear with its comment, and watch wakes on unproven and broken_base."""


class UnprovenRun(unittest.TestCase):
    """An unproven task's dependents wait, and its run events carry no red event."""


class UnprovenWhy(unittest.TestCase):
    """The unproven comment says why the regression test is not proof once the proof has run."""
