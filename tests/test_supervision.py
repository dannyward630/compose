import contextlib, importlib.machinery, importlib.util, io, os, subprocess, sys, tempfile, time, unittest
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
    """Silence with work pending wakes the supervisor once; expected silence (done, waiting on the product owner) never does."""
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()) / "hw"
        (self.proj / "results").mkdir(parents=True)

    def snap(self, tasks=("pending",), crew=None, status="working", last_ago=60, run=False, run_end=0, verify=None):
        return {"tasks": {f"00{i}": {"state": s} for i, s in enumerate(tasks, 1)}, "agents": {ORCH: status},
                "crew": {n: [{"at": at(ago), "state": st, "message": "m"}] for n, (st, ago) in (crew or {}).items()},
                "run": run, "verify": verify, "run_end": run_end, "last": (NOW - last_ago, "teammate x reported working")}

    def stalls(self, snap, now=NOW):
        return fc.watch_stalls(self.proj, snap, 240, now_s=now)

    def test_quiet_project_fires_once(self):
        s = self.snap(crew={ORCH: ("working", 600)}, last_ago=600)
        ev = self.stalls(s)
        self.assertEqual(len(ev), 1)
        self.assertIn("stall=quiet agent=hw-orchestrator", ev[0])
        self.assertIn("herdr agent read hw-orchestrator --lines 60", ev[0])
        self.assertEqual(self.stalls(s), [])  # the same silence does not wake the supervisor again

    def test_a_project_without_a_team_lead_names_none(self):
        s = self.snap(crew={"hw-designer": ("working", 600)}, last_ago=600)
        s["agents"] = {}
        ev = self.stalls(s)
        self.assertEqual(len(ev), 1)
        self.assertIn("stall=quiet nothing moved", ev[0])
        self.assertNotIn("orchestrator", ev[0])
        self.assertIn("no team lead", ev[0])

    def test_the_team_lead_name_is_the_one_crew_start_gives_it(self):
        self.assertEqual(fc.agent_name("autofill-hifi-design", "orchestrator"), "autofill-hifi-desig-orchestrator")
        self.assertLessEqual(len(fc.agent_name("autofill-hifi-design", "orchestrator")), 32)

    def test_recent_activity_is_not_a_stall(self):
        self.assertEqual(self.stalls(self.snap(crew={ORCH: ("working", 60)}, last_ago=60)), [])

    def test_done_or_waiting_on_the_product_owner_is_not_a_stall(self):
        self.assertEqual(self.stalls(self.snap(crew={ORCH: ("done", 900)}, last_ago=900)), [])
        self.assertEqual(self.stalls(self.snap(crew={ORCH: ("needs-user", 900)}, last_ago=900)), [])

    def test_test_crews_done_and_nothing_dispatched(self):
        crew = {ORCH: ("working", 100), "hw-tests-001": ("done", 500), "hw-tests-002": ("done", 400)}
        ev = self.stalls(self.snap(crew=crew, last_ago=100))
        self.assertTrue(any("stall=undispatched" in e for e in ev), ev)

    def test_run_ended_with_no_next_step(self):
        ev = self.stalls(self.snap(tasks=("passed",), crew={ORCH: ("working", 900)}, last_ago=100, run_end=NOW - 300))
        self.assertTrue(any("stall=no-next-step" in e for e in ev), ev)

    def test_team_lead_idle_with_pending_tasks(self):
        s = self.snap(status="idle", crew={ORCH: ("working", 100)}, last_ago=100)
        self.assertEqual(self.stalls(s, now=NOW), [])  # it just went idle
        ev = self.stalls(s, now=NOW + 300)
        self.assertTrue(any("stall=idle agent=hw-orchestrator" in e for e in ev), ev)

    def test_held_tasks_are_still_work(self):
        s = self.snap(tasks=("held",), status="idle", crew={ORCH: ("working", 600)}, last_ago=600)
        self.assertTrue(any("stall=quiet" in e for e in self.stalls(s)))
        ev = self.stalls(s, now=NOW + 300)
        self.assertTrue(any("stall=idle" in e and "1 task(s) pending" in e for e in ev), ev)

    def test_the_engineering_manager_receives_stalls_and_the_team_lead_too(self):
        ev = ["event stall=quiet agent=hw-orchestrator x", "event crew=hw-tests-001 state=done message='m'",
              "event stall=idle agent=hw-orchestrator the team lead has been idle"]
        self.assertEqual(fc.watch_filter(ev, "hw", [ORCH]), [ev[0], ev[2]])
        self.assertEqual(fc.watch_filter(ev, "hw", []), ev[:2])  # the team lead is idle because it waits on this watch


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
        self.assertIn("pending tasks 1, teammates working hw-tests-001, run not live, verify not run", out[-1])


def wsnap(state="pending", run=False, crashed=False, halt=None):
    return {"tasks": {"001": {"state": state, "attempts": 1, "cost": 0.0, "note": "", "linear": "", "title": "t"}}, "agents": {},
            "crew": {}, "run": run, "crashed": crashed, "verify": None, "halt": halt, "run_end": 0, "last": [0, ""]}


class WatchMemory(unittest.TestCase):
    """Each watcher remembers what it last reported, so what happens while no watch runs is reported by the next one."""
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()) / "hw"

    def watch(self, snap, **kw):
        a = SimpleNamespace(repo=".", now=False, from_=None, timeout=0.05, interval=0.01, stall=10_000, rewake=False)
        a.__dict__.update(kw)
        out = []
        with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch.object(fc, "watch_snapshot", return_value=snap), \
                mock.patch("builtins.print", out.append):
            try:
                fc.cmd_watch(a)
            except SystemExit:
                pass
        return out

    def test_a_change_between_two_watches_is_reported_by_the_next(self):
        self.watch(wsnap("running"), now=True)
        out = self.watch(wsnap("passed"))  # the task passed while nobody watched
        self.assertTrue(any("event task=001 state=passed" in line for line in out), out)
        self.assertIn("event timeout", self.watch(wsnap("passed"))[-1])  # reported once, not again

    def test_now_marks_the_current_state_seen(self):
        self.assertTrue(any("task=001 state=passed" in line for line in self.watch(wsnap("passed"), now=True)))
        self.assertIn("event timeout", self.watch(wsnap("passed"))[-1])

    def test_each_watcher_keeps_its_own_memory(self):
        self.watch(wsnap("running"), now=True)
        self.watch(wsnap("running"), now=True, from_="orchestrator")
        later = wsnap("passed")
        later["crew"] = {ORCH: [{"at": at(0), "state": "needs-user", "message": "which db?"}]}
        self.watch(later)  # the team lead's own watch reports the task first
        out = self.watch(later, from_="orchestrator")  # the engineering manager's watch still gets the team lead's question
        self.assertTrue(any(f"event crew={ORCH} state=needs-user" in line for line in out), out)

    def test_a_payment_halt_is_an_event(self):
        ev = fc.watch_events(wsnap(run=True), wsnap(halt=["2026-10-11 10:00:00", "openrouter", 2]))
        self.assertTrue(any(e.startswith("event halt=payment provider=openrouter remaining=2") for e in ev), ev)

    def test_now_reports_a_crashed_run(self):
        out = self.watch(wsnap("running", crashed=True), now=True)
        self.assertTrue(any("run=ended" in line and "CRASHED" in line for line in out), out)


class Rewake(unittest.TestCase):
    """The team lead's Stop hook: park one watch per turn end, wake the idle session with the event on stderr, exit 2."""
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()) / "hw"
        (self.proj / "results").mkdir(parents=True)
        self.env = {"FAST_CODING_ROLE": "orchestrator", "FAST_CODING_PROJECT": "hw", "FAST_CODING_REPO": "/r"}

    def rewake(self, snaps, env=None):
        err = io.StringIO()
        with mock.patch.dict(fc.os.environ, env or self.env), mock.patch.object(fc, "project_dir", return_value=self.proj) as pd, \
                mock.patch.object(fc, "watch_snapshot", side_effect=snaps), mock.patch.object(fc, "WATCH_INTERVAL", 0.01), \
                contextlib.redirect_stderr(err):
            try:
                fc.cmd_rewake(SimpleNamespace())
                code = 0
            except SystemExit as e:
                code = e.code
        return code, err.getvalue(), pd

    def test_an_event_wakes_the_session(self):
        code, err, _ = self.rewake([wsnap("running"), wsnap("running"), wsnap("passed")])
        self.assertEqual(code, 2)
        self.assertIn("event task=001 state=passed", err)

    def test_sessions_that_are_not_the_team_lead_return_at_once(self):
        code, err, pd = self.rewake([], env={"FAST_CODING_ROLE": "crew", "FAST_CODING_PROJECT": "hw"})
        self.assertEqual((code, err), (0, ""))
        pd.assert_not_called()

    def test_a_second_hook_leaves_the_parked_one_alone(self):
        held = fc.watch_lock(self.proj, "all", wait=False)
        self.assertIsNotNone(held)
        code, err, _ = self.rewake([wsnap("passed")])
        self.assertEqual((code, err), (0, ""))
        held.close()


class Detach(unittest.TestCase):
    """run, verify, and resume work in their own session: a closed herdr tab or a dead Claude session ends only the
    follower that streams their log, never the work."""
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.log = self.dir / "run.log"

    def test_the_log_streams_here_and_the_exit_code_comes_back(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = fc.follow([sys.executable, "-c", "print('layer 001 passed'); raise SystemExit(3)"], self.log)
        self.assertEqual(code, 3)
        self.assertIn("layer 001 passed", out.getvalue())
        self.assertIn("layer 001 passed", self.log.read_text())

    def test_the_work_runs_in_its_own_session(self):
        with contextlib.redirect_stdout(io.StringIO()):
            fc.follow([sys.executable, "-c", "import os; print(os.getsid(0))"], self.log)
        self.assertNotEqual(int(self.log.read_text().split()[0]), os.getsid(0))

    def test_killing_the_follower_leaves_the_work_running(self):
        done = self.dir / "done"
        started = self.dir / "started"
        work = f"import time; open({str(started)!r}, 'w').write('1'); time.sleep(1.5); open({str(done)!r}, 'w').write('ok')"
        cli = Path(__file__).resolve().parents[1] / "bin" / "fast-coding"
        follower = subprocess.Popen([sys.executable, "-c",
            "import importlib.machinery as m, importlib.util as u, sys; "
            f"s = u.spec_from_loader('fc', m.SourceFileLoader('fc', {str(cli)!r})); fc = u.module_from_spec(s); s.loader.exec_module(fc); "
            f"fc.follow([sys.executable, '-c', {work!r}], fc.Path({str(self.log)!r}))"], stdout=subprocess.DEVNULL)
        def wait_for(path):  # generous deadline, polled: a loaded machine can take seconds to start python
            for _ in range(300):
                if path.exists():
                    return
                time.sleep(0.1)
        wait_for(started)  # kill only once the work is running, or the follower may die before it ever spawned it
        def tree(pid):  # what Claude Code does to a background task when its tab closes: the whole process tree
            kids = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True).stdout.split()
            return [pid] + [p for k in kids for p in tree(int(k))]
        for pid in tree(follower.pid):
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass
        follower.wait()
        wait_for(done)
        self.assertEqual(done.read_text(), "ok")

    def test_now_says_a_run_is_live(self):
        proj = Path(tempfile.mkdtemp()) / "hw"
        out = []
        a = SimpleNamespace(repo=".", now=True, from_=None)
        with mock.patch.object(fc, "project_dir", return_value=proj), mock.patch.object(fc, "watch_snapshot", return_value=wsnap("running", run=True)), \
                mock.patch("builtins.print", out.append):
            fc.cmd_watch(a)
        self.assertTrue(any(line.startswith("event run=live") for line in out), out)


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
        r = sp.run([str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding"), "timed", "1", "--", "sh -c 'sleep 4017' & sleep 4017"],
                   capture_output=True, text=True)
        self.assertEqual(r.returncode, 124)
        self.assertIn("hangs", r.stderr)
        self.assertLess(time.time() - t0, 10)
        time.sleep(0.5)
        self.assertEqual(sp.run(["pgrep", "-f", "sleep 4017"], capture_output=True).stdout.strip(), b"")


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
