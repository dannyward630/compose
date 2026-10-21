import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, json, os, shutil, subprocess, sys, tempfile, threading, time, unittest
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)


class Proc(unittest.TestCase):
    """Task 001 (NEB-918): fc_proc.run, kill_group, stop, Stopped and HOOKS."""

    def setUp(self):
        self.addCleanup(fc.fc_proc.STOP.clear); self.addCleanup(fc.fc_proc.HOOKS.clear); self.addCleanup(fc.fc_proc.RUNNING.clear)

    def sleeps(self, k):
        """A sleep length unique to this run and case (12 s and change, so a missed kill ends on its own), and its live pids."""
        n = f"12.{os.getpid()}{k}"
        pids = lambda: [int(p) for p in subprocess.run(["pgrep", "-f", f"sleep {n}( |$)"], capture_output=True, text=True).stdout.split()]
        self.addCleanup(lambda: [os.kill(p, 9) for p in pids()])
        return n, pids

    def test_returns_output_and_exit_code_from_a_session_of_its_own(self):
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, True)
        code = "import os, sys; print(os.getpgid(0), os.getsid(0), os.getcwd(), os.environ['X'], repr(sys.stdin.read())); sys.exit('bad')"
        r = fc.fc_proc.run([sys.executable, "-c", code], cwd=d, env={"X": "y"}, timeout=30)
        pgid, sid, cwd, x, stdin = r.stdout.split()
        self.assertEqual((type(r), r.returncode, r.stderr, x, stdin, os.path.realpath(cwd)), (subprocess.CompletedProcess, 1, "bad\n", "y", "''", os.path.realpath(d)))
        self.assertEqual(pgid, sid); self.assertNotEqual(int(pgid), os.getpgid(0))
        self.assertEqual(fc.fc_proc.RUNNING, set())

    def test_stop_from_another_thread_kills_the_whole_group_within_6s(self):
        """The background sleep holds stdout open and every process ignores SIGTERM: only the group SIGKILL ends the run."""
        (n, pids), stopped = self.sleeps(0), []
        def stopper():
            deadline = time.time() + 5
            while len(pids()) < 3 and time.time() < deadline: time.sleep(0.05)
            stopped.append(time.time()); fc.fc_proc.stop()
        threading.Thread(target=stopper, daemon=True).start()
        try:
            fc.fc_proc.run(["sh", "-c", f"trap '' TERM; sleep {n} & sleep {n}"], timeout=60)
        except fc.fc_proc.Stopped:
            pass
        self.assertLess(time.time() - stopped[0], 6)
        time.sleep(0.5); self.assertEqual(pids(), [])

    def test_a_timeout_kills_the_whole_group_and_raises(self):
        (n, pids), t0 = self.sleeps(1), time.time()
        with self.assertRaises(subprocess.TimeoutExpired):
            fc.fc_proc.run(["sh", "-c", f"sleep {n} & sleep {n}"], timeout=1)
        self.assertLess(time.time() - t0, 8)
        time.sleep(0.5); self.assertEqual(pids(), []); self.assertEqual(fc.fc_proc.RUNNING, set())

    def test_after_the_stop_run_raises_stopped_and_starts_nothing(self):
        d = tempfile.mkdtemp(); self.addCleanup(shutil.rmtree, d, True)
        fc.fc_proc.STOP.set()
        with self.assertRaises(fc.fc_proc.Stopped):
            fc.fc_proc.run(["touch", "started"], cwd=d)
        self.assertFalse(os.path.exists(os.path.join(d, "started")))

    def test_stop_sets_stop_and_calls_every_hook(self):
        called = []
        fc.fc_proc.HOOKS.update(esc=lambda: called.append("esc"), close=lambda: called.append("close"))
        fc.fc_proc.stop()
        self.assertTrue(fc.fc_proc.STOP.is_set()); self.assertEqual(sorted(called), ["close", "esc"])

    def test_killing_a_group_already_gone_is_not_an_error(self):
        p = subprocess.Popen(["true"], start_new_session=True); p.wait()
        fc.fc_proc.kill_group(p.pid)


class Slots(unittest.TestCase):
    """fc_proc.slot lanes: a scoped run never queues behind a suite."""

    def test_scoped_tells_a_slice_of_the_tests_from_a_suite(self):
        yes = ("pytest -k foo", "go test ./... -run TestX", "npx vitest src/a.test.ts", "python3 -m unittest tests.test_proc", "pytest tests/test_a.py::T::t",
               "python3 -m unittest discover -s tests -p 'test_x.py'", "cd app && npx jest --testNamePattern=foo", "pytest -k a | tail", "npm test -- -t foo")
        no = ("python3 -m unittest discover -s tests", "python3 -m unittest discover -s tests -p \"test_*.py\"", "go test ./...", "npm test", "make test", "",
              "pytest -k a; pytest", "cd app")
        for c in yes: self.assertTrue(fc.fc_proc.scoped(c), c)
        for c in no: self.assertFalse(fc.fc_proc.scoped(c), c)

    def test_a_quick_run_gets_a_slot_while_every_suite_slot_is_held_and_waits_only_on_quick_runs(self):
        env = {"COMPOSE_TEST_SLOTS": "1", "COMPOSE_QUICK_SLOTS": "1"}
        said = []
        with mock.patch.dict(os.environ, env), mock.patch.object(fc.fc_proc, "SLOT_SAY_AFTER", 0.2):
            os.environ.pop("COMPOSE_TEST_SLOT", None)
            with fc.fc_proc.slot() as full:
                t0 = time.time()
                with fc.fc_proc.slot(said.append, True) as quick:
                    self.assertLess(time.time() - t0, 1)
                    self.assertEqual((full, quick), ("0", "q0"))
                    t1 = time.time()
                    ready = threading.Event()
                    def another():
                        os.environ.pop("COMPOSE_TEST_SLOT", None)
                        with fc.fc_proc.slot(said.append, True) as n: ready.set(); said.append(n)
                    th = threading.Thread(target=another); th.start()
                    time.sleep(0.6); self.assertFalse(ready.is_set())  # a second quick run waits on the first
                th.join(timeout=5); self.assertTrue(ready.is_set())
        self.assertTrue(any("quick-run slot" in x for x in said), said)
        self.assertEqual(sorted(x.name for x in (Path(os.environ["HOME"]) / ".compose" / "test-slots").iterdir()), ["0", "q0"])

    def test_a_process_already_under_a_slot_takes_none_in_either_lane(self):
        with mock.patch.dict(os.environ, {"COMPOSE_TEST_SLOT": "q1", "COMPOSE_QUICK_SLOTS": "1"}):
            with fc.fc_proc.slot(None, True) as a, fc.fc_proc.slot(None, True) as b, fc.fc_proc.slot() as c:
                self.assertEqual((a, b, c), ("q1", "q1", "q1"))


if __name__ == "__main__":
    unittest.main()
