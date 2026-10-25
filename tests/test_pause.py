import hermetic  # first: no test sees the real home
import json, os, subprocess, sys, tempfile, threading, time, unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_reflect import fc, project, task, with_tasks, run_all  # the loaded compose and the run-loop helpers
os.environ["HERDR_ENV"] = ""

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(repo, *a):
    return subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, text=True, env={**os.environ, **ENV}).stdout


class PauseRunningTask(unittest.TestCase):
    def go(self, impl, reason=""):
        """run_task over a real repo with `impl` as the implementer and a hold on 001 written once its first turn starts."""
        root = Path(tempfile.mkdtemp())
        repo, proj = root / "repo", root / "proj"
        repo.mkdir(); (proj / "results").mkdir(parents=True)
        git(repo, "init", "-q", "-b", "main")
        (repo / "a.txt").write_text("no\n")
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "init")
        meta = {"id": "001", "title": "answer", "files": ["a.txt", "b.txt"], "protected": [], "test": "grep -q yes a.txt",
                "model": "pi:p/primary", "after": "", "linear": "ENG-1", "body": "## Goal\nWrite yes."}
        self.linear_events = []
        def wrapped(*a, **kw):
            (proj / "results" / "hold.json").write_text(json.dumps({"001": {"reason": reason, "at": "2026-10-26 10:00:00"}}))
            return impl(*a, **kw)
        self.addCleanup(fc.fc_proc.resume_task, "001")
        with mock.patch.object(fc.fc_implement, "implementer", wrapped), mock.patch.object(fc.fc_implement.fc_trailpack, "trail_pack", return_value=""), \
                mock.patch.object(fc.fc_config, "TEST_READER", None), mock.patch.dict(os.environ, ENV), \
                mock.patch.object(fc.fc_linear, "linear_event", lambda p, m, e, *r: self.linear_events.append((m["id"], e))):
            return fc.fc_implement.run_task(repo, proj, meta, 3), repo, proj

    def test_a_hold_during_a_turn_pauses_the_task_and_keeps_its_edits_on_a_ref(self):
        def impl(cwd, model, prompt, session=None, task=None, timeout=None):
            (Path(cwd) / "a.txt").write_text("half\n"); (Path(cwd) / "b.txt").write_text("new\n")
            threading.Timer(0.3, fc.fc_proc.pause_task, ("001",)).start()
            fc.fc_proc.run(["sleep", "30"])  # the turn, still going when the hold lands
        r, repo, proj = self.go(impl, reason="D2 changed")
        self.assertEqual(r["status"], "paused")
        self.assertEqual(r["paused"]["ref"], f"refs/compose/{proj.name}/paused/001")
        self.assertEqual(sorted(r["paused"]["files"]), ["a.txt", "b.txt"])
        self.assertEqual(git(repo, "show", f"{r['paused']['ref']}:a.txt"), "half\n")
        self.assertEqual(json.loads((proj / "results" / "001.json").read_text())["status"], "paused")
        self.assertEqual(list((proj / "worktrees").glob("001*")), [])  # the clone is gone, the ref holds the work
        self.assertEqual([e for _, e in self.linear_events], ["dispatched"])  # no failed or passed event

    def test_a_pause_between_turns_stops_before_the_next_turn(self):
        turns = []
        def impl(cwd, model, prompt, session=None, task=None, timeout=None):
            turns.append(1); fc.fc_proc.pause_task("001")  # lands while the test runs after this turn
            (Path(cwd) / "a.txt").write_text("nope\n")
            return "s", "", 1, {"cost": 0.0}
        r, _, _ = self.go(impl)
        self.assertEqual((r["status"], len(turns)), ("paused", 1))


    def test_a_turn_that_returns_after_the_pause_never_reaches_its_test(self):
        tests, turned = [], []  # the base is tested once before the turn; only a test after it counts
        def impl(cwd, model, prompt, session=None, task=None, timeout=None):
            turned.append(1)
            fc.fc_proc.pause_task("001")  # the cut did not end the turn with an error: it came back with the answer written
            (Path(cwd) / "a.txt").write_text("yes\n")
            return "s", "", 1, {"cost": 0.0}
        with mock.patch.object(fc.fc_implement, "run_test", lambda *a: (tests.append(1) if turned else None) or mock.Mock(returncode=1, stdout="", stderr="")):
            r, repo, _ = self.go(impl)
        self.assertEqual((r["status"], tests), ("paused", []))
        self.assertEqual([e for _, e in self.linear_events], ["dispatched"])
        self.assertEqual(git(repo, "branch", "--list", "task-*"), "")  # nothing committed to a task branch

    def test_a_snapshot_that_fails_reports_an_error_and_keeps_the_clone(self):
        def impl(cwd, model, prompt, session=None, task=None, timeout=None):
            (Path(cwd) / "b.txt").write_text("new\n")
            fc.fc_proc.pause_task("001")
            return "s", "", 1, {"cost": 0.0}
        with mock.patch.object(fc.fc_implement.fc_pause, "snapshot", side_effect=RuntimeError("git broke")):
            r, _, proj = self.go(impl, reason="D2 changed")
        self.assertEqual(r["status"], "failed")
        self.assertIn("pause snapshot failed", json.dumps(r["log"]))
        self.assertTrue((proj / "worktrees" / "001" / "b.txt").exists())
        self.assertEqual(json.loads((proj / "results" / "001.json").read_text())["status"], "failed")


class HerdrPiPause(unittest.TestCase):
    def turn(self, answer):
        proj = Path(tempfile.mkdtemp()) / "hw"
        task = {"proj": proj, "meta": {"id": "001", "title": "t"}, "space": "s"}
        session = {"name": "hw-001", "pane": "p1", "sfile": None, "seen": 0}
        self.addCleanup(fc.fc_proc.resume_task, "001")
        fc.fc_proc.pause_task("001")
        with mock.patch.object(fc.fc_herdr, "herdr_error", return_value=answer), mock.patch.object(fc.fc_herdr, "herdr", return_value={}):
            fc.fc_implement.herdr_pi(tempfile.mkdtemp(), "x/y", "hi", session, task)

    def test_a_paused_task_raises_paused_whether_or_not_herdr_reported_an_error(self):
        for answer in (({"ok": 1}, None), (None, "agent_error")):
            with self.subTest(answer=answer), self.assertRaises(fc.fc_proc.Paused):
                self.turn(answer)


class RunLoopPauses(unittest.TestCase):
    def setUp(self):
        self.proj = project()
        with_tasks(self.proj, [task("001"), task("002")])
        self.addCleanup(fc.fc_proc.resume_task, "002")

    def hold_002_and_wait(self, tid):
        if tid != "002":
            return
        (self.proj / "results" / "hold.json").write_text(json.dumps({"002": {"reason": "D2 changed", "at": "2026-10-26 10:00:00"}}))
        end = time.time() + 6
        while time.time() < end and not fc.fc_proc.task_paused("002"):
            time.sleep(0.05)

    def test_the_run_pauses_a_held_running_task_within_a_pass_and_keeps_it_pending(self):
        calls, out, _ = run_all(self.proj, status={"002": "paused"}, during=self.hold_002_and_wait, parallel=2)
        self.assertIn("002 paused  D2 changed", out)
        self.assertEqual(calls.count("002"), 1)  # not restarted while held
        self.assertIn("002 held    D2 changed", out)
        self.assertFalse(fc.fc_proc.task_paused("002"))  # cleared when its result came back

    def test_a_hold_that_vanishes_between_reads_does_not_stop_the_loop(self):
        gone = []
        real = fc.fc_tasks.held
        def held(proj):  # the hold shows for two reads once 002 runs, then a release lands
            if len(gone) >= 2 or not seen:
                return {}
            gone.append(1)
            return {"002": {"reason": "D2 changed", "at": "x"}}
        seen = []
        def during(tid):
            if tid == "002":
                seen.append(1)
                end = time.time() + 3
                while time.time() < end and len(gone) < 2:
                    time.sleep(0.05)
        with mock.patch.object(fc.fc_tasks, "held", held):
            _, out, _ = run_all(self.proj, during=during, parallel=2)
        self.assertIn("run done", out)


if __name__ == "__main__":
    unittest.main()
