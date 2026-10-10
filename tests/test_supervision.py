import importlib.machinery, importlib.util, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)

NOW = 1_800_000_000.0
at = lambda ago: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(NOW - ago))
ORCH = "hw-orchestrator"


class Stalls(unittest.TestCase):
    """Silence with work pending wakes the supervisor once; expected silence (done, waiting on the captain) never does."""
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()) / "hw"
        (self.proj / "results").mkdir(parents=True)

    def snap(self, tasks=("pending",), crew=None, status="working", last_ago=60, run=False, run_end=0, verify=None):
        return {"tasks": {f"00{i}": {"state": s} for i, s in enumerate(tasks, 1)}, "agents": {ORCH: status},
                "crew": {n: [{"at": at(ago), "state": st, "message": "m"}] for n, (st, ago) in (crew or {}).items()},
                "run": run, "verify": verify, "run_end": run_end, "last": (NOW - last_ago, "crew x reported working")}

    def stalls(self, snap, now=NOW):
        return fc.watch_stalls(self.proj, snap, 240, now_s=now)

    def test_quiet_project_fires_once(self):
        s = self.snap(crew={ORCH: ("working", 600)}, last_ago=600)
        ev = self.stalls(s)
        self.assertEqual(len(ev), 1)
        self.assertIn("stall=quiet agent=hw-orchestrator", ev[0])
        self.assertIn("herdr agent read hw-orchestrator --lines 60", ev[0])
        self.assertEqual(self.stalls(s), [])  # the same silence does not wake the supervisor again

    def test_recent_activity_is_not_a_stall(self):
        self.assertEqual(self.stalls(self.snap(crew={ORCH: ("working", 60)}, last_ago=60)), [])

    def test_done_or_waiting_on_the_captain_is_not_a_stall(self):
        self.assertEqual(self.stalls(self.snap(crew={ORCH: ("done", 900)}, last_ago=900)), [])
        self.assertEqual(self.stalls(self.snap(crew={ORCH: ("needs-user", 900)}, last_ago=900)), [])

    def test_test_crews_done_and_nothing_dispatched(self):
        crew = {ORCH: ("working", 100), "hw-tests-001": ("done", 500), "hw-tests-002": ("done", 400)}
        ev = self.stalls(self.snap(crew=crew, last_ago=100))
        self.assertTrue(any("stall=undispatched" in e for e in ev), ev)

    def test_run_ended_with_no_next_step(self):
        ev = self.stalls(self.snap(tasks=("passed",), crew={ORCH: ("working", 900)}, last_ago=100, run_end=NOW - 300))
        self.assertTrue(any("stall=no-next-step" in e for e in ev), ev)

    def test_orchestrator_idle_with_pending_tasks(self):
        s = self.snap(status="idle", crew={ORCH: ("working", 100)}, last_ago=100)
        self.assertEqual(self.stalls(s, now=NOW), [])  # it just went idle
        ev = self.stalls(s, now=NOW + 300)
        self.assertTrue(any("stall=idle agent=hw-orchestrator" in e for e in ev), ev)

    def test_the_first_mate_receives_stalls_and_the_orchestrator_too(self):
        ev = ["event stall=quiet agent=hw-orchestrator x", "event crew=hw-tests-001 state=done message='m'"]
        self.assertEqual(fc.watch_filter(ev, "hw", [ORCH]), ev[:1])
        self.assertEqual(fc.watch_filter(ev, "hw", []), ev)


class WatchTimeout(unittest.TestCase):
    def test_timeout_ends_with_a_state_summary(self):
        snap = {"tasks": {"001": {"state": "pending"}}, "agents": {},
                "crew": {"hw-tests-001": [{"at": time.strftime("%Y-%m-%d %H:%M:%S"), "state": "working", "message": "m"}]},
                "run": False, "verify": None, "run_end": 0, "last": (0, "")}
        a = SimpleNamespace(repo=".", now=False, from_=None, timeout=0.01, interval=0.01, stall=10_000)
        out = []
        with mock.patch.object(fc, "project_dir", return_value=Path(tempfile.mkdtemp()) / "hw"), \
                mock.patch.object(fc, "watch_snapshot", return_value=snap), mock.patch("builtins.print", out.append):
            with self.assertRaises(SystemExit) as e:
                fc.cmd_watch(a)
        self.assertEqual(e.exception.code, 2)
        self.assertIn("event timeout", out[-1])
        self.assertIn("pending tasks 1, crews working hw-tests-001, run not live, verify not run", out[-1])


if __name__ == "__main__":
    unittest.main()


class TestHang(unittest.TestCase):
    def test_a_hanging_test_fails_fast_with_a_reason(self):
        import tempfile, time
        t0 = time.time()
        r = fc.run_test({"test": "sleep 30", "test_timeout": "1"}, tempfile.mkdtemp())
        self.assertLess(time.time() - t0, 10)
        self.assertEqual(r.returncode, 124)
        self.assertIn("hangs", r.stderr)


class Timed(unittest.TestCase):
    def test_timed_kills_the_whole_group_and_says_it_hangs(self):
        import subprocess as sp, time
        t0 = time.time()
        r = sp.run([str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding"), "timed", "1", "--", "sh -c 'sleep 40' & sleep 40"],
                   capture_output=True, text=True)
        self.assertEqual(r.returncode, 124)
        self.assertIn("hangs", r.stderr)
        self.assertLess(time.time() - t0, 10)
        time.sleep(0.5)
        self.assertEqual(sp.run(["pgrep", "-f", "sleep 40"], capture_output=True).stdout.strip(), b"")


class JevLeash(unittest.TestCase):
    def test_a_jev_that_gives_up_is_a_tool_error_not_an_app_failure(self):
        self.assertTrue(fc.tool_error("JEV_GAVE_UP: jev ended blocked after 60 steps\n"))
        self.assertTrue(fc.tool_error("JEV_GAVE_UP: jev did not reach its goal within 150s"))
        self.assertFalse(fc.tool_error("AssertionError: score was 2 of 3"))

    def test_a_jev_case_is_killed_at_its_limit(self):
        with mock.patch.object(fc, "JEV_DIR", Path(tempfile.mkdtemp())), \
             mock.patch.object(fc, "timed", return_value=fc.subprocess.CompletedProcess("x", 124, "", "hung")) as t:
            r = fc.jev_e2e({"name": "c", "url": "http://x", "goal": "g", "assert": "true", "timeout": 5}, Path("/tmp"))
        self.assertEqual(t.call_args[0][2], 5)
        self.assertIn("JEV_GAVE_UP", r["stderr"]); self.assertTrue(fc.tool_error(r["stderr"]))
