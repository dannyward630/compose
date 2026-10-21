import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, os, unittest
from pathlib import Path
import sys
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_fast, fc_regproof, fc_regress, fc_regwriter  # noqa: E402
import json, subprocess, tempfile
from unittest import mock

ENV = {"HERDR_ENV": "", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
FIX = "fix-then-regression-test"
PROOF = {"commit": "abc1234", "command": "true", "paths": ["tests/test_x.py"], "proven": True}


class Pin(unittest.TestCase):
    """A proven regression test is pinned into the task's protected files and test command."""


class Regress(unittest.TestCase):
    """A FAST fix passes only after its regression test is proven and saved."""
    def setUp(self):
        env = mock.patch.dict(os.environ, ENV); env.start(); self.addCleanup(env.stop)
        self.repo = Path(tempfile.mkdtemp()).resolve(); self.proj = self.repo / ".compose" / "p"; (self.proj / "results").mkdir(parents=True)
        self.meta = {"id": "001", "title": "t", "after": "", "files": [], "protected": [], "test": "true", "model": "m"}
        self.res = {"id": "001", "title": "t", "status": "unproven", "attempts": 1, "seconds": 0.0, "cost": 0.0, "branch": "fast/p/001", "log": []}
        self.flow = mock.Mock(return_value=FIX)
        for p in (mock.patch.object(fc_fast, "workflow", self.flow), mock.patch.object(fc.fc_tasks, "WORKFLOWS", ("test-first", "implement-then-test", FIX), create=True)):
            p.start(); self.addCleanup(p.stop)

    def test_fast_fix_is_an_unproven_fix_then_regression_test_result_without_a_proof(self):
        self.assertTrue(fc_regress.fast_fix(self.proj, self.meta, self.res))
        self.assertFalse(any(fc_regress.fast_fix(self.proj, self.meta, dict(self.res, **kw)) for kw in ({"proof": None}, {"status": "passed"})))

    def round(self, ready=("abc1234", "true"), proof=PROOF, saved=True, start=None):
        with mock.patch.object(fc_regwriter, "start_writer", side_effect=start, return_value=self.repo), mock.patch.object(fc_regwriter, "wait_ready", return_value=ready), \
             mock.patch.object(fc_regproof, "prove", return_value=proof), mock.patch.object(fc_regproof, "record_proof", return_value=saved), \
             mock.patch.object(fc_regress, "pin_test") as pin, mock.patch.object(fc_regress, "end_writer") as end, mock.patch.object(fc.fc_linear, "linear_event") as ev:
            out = fc_regress.regress(self.repo, self.proj, self.meta, self.res)
        self.assertEqual(json.loads((self.proj / "results" / "001.json").read_text())["status"], out["status"])
        ev.assert_called_once_with(self.proj, self.meta, out["status"], out)
        return out, pin, end

    def test_a_proven_saved_proof_passes_the_task_pins_the_test_and_ends_the_writer(self):
        out, pin, end = self.round()
        self.assertEqual((out["status"], out["proof"]), ("passed", PROOF)); pin.assert_called_once(); end.assert_called_once_with(self.repo, self.proj, "001")

    def test_anything_short_of_a_saved_proof_keeps_the_task_unproven_and_unpinned(self):
        bad = dict(PROOF, proven=False)
        for why, kw, proof in (("unsaved", {"saved": False}, PROOF), ("unproven", {"proof": bad}, bad), ("no ready line", {"ready": None}, None),
                               ("start failed", {"start": RuntimeError("x")}, None), ("start exited", {"start": SystemExit("x")}, None)):
            with self.subTest(why):
                out, pin, end = self.round(**kw)
                self.assertEqual((out["status"], out["proof"]), ("unproven", proof)); pin.assert_not_called(); end.assert_not_called()

    def test_end_writer_drops_the_writers_worktree_and_branch_and_reports_done(self):
        wt, git = self.proj / "worktrees" / "regress-001", lambda *a: subprocess.run(["git", *a], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()
        git("init", "-q", "-b", "main"); git("commit", "-q", "--allow-empty", "-m", "i"); git("worktree", "add", "-q", "-b", "wr/p/001", str(wt))
        with mock.patch.object(fc.fc_worktree, "use_treehouse", return_value=False), mock.patch.object(fc_regwriter, "writer_branch", return_value="wr/p/001"), mock.patch.object(fc.fc_crew, "write_report") as rep:
            fc_regress.end_writer(self.repo, self.proj, "001")
        self.assertFalse(wt.exists()); self.assertEqual(git("branch", "--list", "wr/p/001"), "")
        self.assertEqual((rep.call_args.args[0], rep.call_args.args[2:]), (self.proj, ("done", "regression test proven")))

    def drive(self, flow, status):
        ran, a, self.flow.return_value = [], mock.Mock(trunk="trunk", attempts=3, parallel=1, no_stack=True, redo=False), flow
        def run_task(repo, proj, m, attempts):
            ran.append(m["id"]); return dict(self.res, id=m["id"], status="unproven" if m["id"] == "001" else "passed")
        with mock.patch.object(fc.fc_core, "say"), mock.patch.object(fc.fc_run, "preflight", lambda m: None), mock.patch.object(fc.fc_herdr, "herdr_space", lambda p: None), \
             mock.patch.object(fc.fc_run, "triage", lambda *x: None), mock.patch.object(fc.fc_implement, "run_task", run_task), mock.patch("builtins.print") as out, self.assertRaises(SystemExit), \
             mock.patch.object(fc_regress, "regress", side_effect=lambda *x: {**x[3], "status": status, "proof": None}) as rg:
            fc.fc_run.run_tasks(self.repo, self.proj, [dict(self.meta), dict(self.meta, id="002", after="001")], a)
        return ran, rg, [str(c.args[0]) for c in out.call_args_list if c.args and str(c.args[0]).startswith("001")]

    def test_run_tasks_proves_an_unproven_fix_once_and_its_passed_row_releases_the_dependent(self):
        ran, rg, rows = self.drive(FIX, "passed")
        self.assertEqual((ran, len(rows)), (["001", "002"], 1)); self.assertIn("passed", rows[0])
        self.assertEqual([(c.args[0], c.args[1], c.args[2]["id"], c.args[3]["status"], c.args[4]) for c in rg.call_args_list], [(self.repo, self.proj, "001", "unproven", 3)])

    def test_run_tasks_keeps_an_unproven_fix_and_blocks_its_dependent_and_skips_other_workflows(self):
        ran, rg, rows = self.drive(FIX, "unproven")
        self.assertEqual((ran, len(rows)), (["001"], 1)); self.assertIn("unproven", rows[0])
        ran, rg, rows = self.drive("test-first", "passed")
        rg.assert_not_called(); self.assertEqual(ran, ["001"]); self.assertIn("unproven", rows[0])


class Reprove(unittest.TestCase):
    """A regression test that is not proof re-prompts its writer up to the attempts, then leaves the task unproven."""
