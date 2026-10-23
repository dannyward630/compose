import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, json, os, shutil, subprocess, sys, tempfile, threading, time, types, unittest
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

    def test_run_limited_turns_a_timeout_into_exit_124_with_the_output_so_far_and_the_limit(self):
        (n, pids), t0 = self.sleeps(2), time.time()
        p = fc.fc_proc.run_limited(["sh", "-c", f"echo before; sleep {n} & sleep {n}"], timeout=1)
        self.assertEqual((p.returncode, p.stdout), (124, "before\n"))
        self.assertIn("TIMEOUT: did not finish within 1s", p.stderr)
        self.assertLess(time.time() - t0, 8)
        time.sleep(0.5); self.assertEqual(pids(), [])

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

    def test_only_a_whole_suite_takes_a_suite_slot(self):
        suites = ("python3 -m unittest discover -s tests", "pytest", "npm test", "make test", "go test ./...", "cd app && npm run test", "cargo nextest run",
                  "uv run pytest tests", "pytest -k a; pytest", "python3 -m tests.run", "cd compose && python3 -m tests.run -j 4")
        others = ("python3 bin/compose.py --help", "bp help", "uv sync --locked", "git status", "npm install test-pkg", "cd app", "",
                  "pytest -k foo", "node --test test/bp.test.mjs", "pytest tests/test_a.py tests/test_b.py", "npm test -- -t foo",
                  "python3 -m tests.run test_ship.py", "python3 -m tests.run test_ship test_layers")
        for c in suites: self.assertTrue(fc.fc_proc.suite(c), c)
        for c in others: self.assertFalse(fc.fc_proc.suite(c), c)

    def test_suite_slots_default_to_one_on_any_core_count_and_the_env_overrides_them(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("COMPOSE_TEST_SLOTS", None)
            for cores in (None, 1, 4, 16, 64):
                with mock.patch("os.cpu_count", return_value=cores):
                    self.assertEqual(fc.fc_proc.suite_slots(), 1, cores)
            with mock.patch("os.cpu_count", return_value=64):
                for env, want in (("3", 3), ("1", 1), ("0", 1), ("", 1)):
                    os.environ["COMPOSE_TEST_SLOTS"] = env
                    self.assertEqual(fc.fc_proc.suite_slots(), want, env)

    def test_a_second_suite_waits_for_the_first_by_default_while_a_quick_run_does_not(self):
        with mock.patch.dict(os.environ, {"COMPOSE_QUICK_SLOTS": "1"}), mock.patch("os.cpu_count", return_value=16):
            os.environ.pop("COMPOSE_TEST_SLOT", None); os.environ.pop("COMPOSE_TEST_SLOTS", None)
            ready, got = threading.Event(), []
            def another():
                os.environ.pop("COMPOSE_TEST_SLOT", None)
                with fc.fc_proc.slot() as n: got.append(n); ready.set()
            with fc.fc_proc.slot() as first:
                th = threading.Thread(target=another); th.start()
                time.sleep(0.6); self.assertFalse(ready.is_set())  # the second suite waits on the first
                with fc.fc_proc.slot(None, True) as quick: self.assertEqual((first, quick), ("0", "q0"))
            th.join(timeout=5); self.assertEqual(got, ["0"])  # it takes the slot the first one released

    def test_a_command_that_is_not_a_suite_runs_while_every_suite_slot_is_held(self):
        with mock.patch.dict(os.environ, {"COMPOSE_TEST_SLOTS": "1", "COMPOSE_QUICK_SLOTS": "1"}):
            os.environ.pop("COMPOSE_TEST_SLOT", None)
            with fc.fc_proc.slot():
                t0 = time.time()
                r = fc.fc_implement.timed("echo hi", os.getcwd(), 10)
                self.assertEqual((r.returncode, r.stdout.strip()), (0, "hi"))
                self.assertLess(time.time() - t0, 3)

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
class KeepAwake(unittest.TestCase):
    """fc_proc.keep_awake holds one `caffeinate -dims -w <pid>` per process, and nothing where there is no caffeinate."""
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.dir, True)
        (self.dir / "caffeinate").write_text(f"#!/bin/sh\necho \"$@\" >> {self.dir}/args\nexec sleep 30\n")
        (self.dir / "caffeinate").chmod(0o755)
        for p in (mock.patch.dict(os.environ, {"PATH": f"{self.dir}{os.pathsep}{os.environ['PATH']}", "COMPOSE_NO_AWAKE": ""}), mock.patch.object(sys, "platform", "darwin"),
                  mock.patch.dict(fc.fc_proc.AWAKE, clear=True)):
            p.start(); self.addCleanup(p.stop)
        self.addCleanup(lambda: [(h.terminate(), h.wait()) for h in list(fc.fc_proc.AWAKE.values())])

    def args(self, count):
        deadline = time.time() + 5
        while time.time() < deadline and not ((self.dir / "args").exists() and len((self.dir / "args").read_text().splitlines()) >= count):
            time.sleep(0.02)
        return sorted((self.dir / "args").read_text().splitlines())

    def test_it_holds_the_display_idle_disk_and_system_assertions_for_the_pid_and_only_once(self):
        held = fc.fc_proc.keep_awake()
        self.assertIs(fc.fc_proc.keep_awake(), held)  # run, verify and an e2e stage may each ask: one assertion
        self.assertIsNone(held.poll())
        self.assertEqual(self.args(1), [f"-dims -w {os.getpid()}"])
        other = fc.fc_proc.keep_awake(4242)  # a teammate's session
        self.assertIsNot(other, held)
        self.assertEqual(self.args(2), sorted([f"-dims -w {os.getpid()}", "-dims -w 4242"]))

    def test_it_asks_again_when_the_hold_ended(self):
        held = fc.fc_proc.keep_awake()
        held.terminate(); held.wait()
        self.assertIsNot(fc.fc_proc.keep_awake(), held)

    def test_it_does_nothing_without_caffeinate_or_off_macos(self):
        with mock.patch.object(sys, "platform", "linux"):
            self.assertIsNone(fc.fc_proc.keep_awake())
        (self.dir / "caffeinate").unlink()
        with mock.patch("shutil.which", return_value=None):
            self.assertIsNone(fc.fc_proc.keep_awake())
        self.assertEqual(fc.fc_proc.AWAKE, {})

    def test_it_does_nothing_under_compose_no_awake(self):
        with mock.patch.dict(os.environ, {"COMPOSE_NO_AWAKE": "1"}):
            self.assertIsNone(fc.fc_proc.keep_awake())
        self.assertEqual(fc.fc_proc.AWAKE, {})


class Slept(unittest.TestCase):
    """fc_proc.clock and fc_proc.slept: the seconds a Mac slept, the wall clock's against the awake one (monotonic stops in sleep)."""

    def at(self, wall, awake):
        return mock.patch.object(fc.fc_proc, "time", types.SimpleNamespace(time=lambda: wall, monotonic=lambda: awake))

    def test_it_is_the_wall_time_the_awake_clock_did_not_see(self):
        with self.at(1000.0, 50.0):
            since = fc.fc_proc.clock()
        with self.at(1000.0 + 5400, 50.0 + 180):
            self.assertEqual(fc.fc_proc.slept(since), 5220)

    def test_a_short_gap_or_a_clock_set_back_is_no_sleep(self):
        with self.at(1000.0, 50.0):
            since = fc.fc_proc.clock()
        for wall, awake in ((1000.0 + 30, 50.0), (1000.0 + 600, 50.0 + 590), (1000.0 - 3600, 50.0 + 10)):
            with self.subTest(wall=wall), self.at(wall, awake):
                self.assertEqual(fc.fc_proc.slept(since), 0)

    def test_it_says_the_minutes(self):
        self.assertEqual(fc.fc_proc.slept_text(5220), "the machine slept for 87 minutes")
        self.assertEqual(fc.fc_proc.slept_text(90), "the machine slept for 2 minutes")


if __name__ == "__main__":
    unittest.main()
