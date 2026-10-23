import hermetic  # first: no test sees the real home
import contextlib, importlib.util, io, os, signal, subprocess, sys, tempfile, textwrap, time, unittest
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""

RUN = Path(__file__).resolve().parent / "run.py"
_spec = importlib.util.spec_from_file_location("compose_tests_run", RUN)
run = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import fc_gate

PASSING = "import unittest\nclass A(unittest.TestCase):\n    def test_one(self): pass\n    def test_two(self): pass\n"
MIXED = textwrap.dedent("""\
    import unittest
    class B(unittest.TestCase):
        def test_good(self): pass
        def test_bad(self): self.assertEqual(1, 2)
        def test_boom(self): raise RuntimeError("boom")
        @unittest.skip("later")
        def test_later(self): pass
    """)
TIMES = textwrap.dedent("""\
    import os, time, unittest
    class T(unittest.TestCase):
        def test_t(self):
            with open(os.environ["TIMES"], "a") as f: f.write("start %.3f\\n" % time.time())
            time.sleep(1)
            with open(os.environ["TIMES"], "a") as f: f.write("end %.3f\\n" % time.time())
    """)


class TestRun(unittest.TestCase):
    def make_dir(self, **files):
        d = Path(tempfile.mkdtemp()).resolve()
        for name, text in files.items():
            (d / f"test_{name}.py").write_text(text)
        return d

    def go(self, d, *argv):
        err = io.StringIO()
        with mock.patch.object(run, "TESTS", d), contextlib.redirect_stderr(err), mock.patch.dict(os.environ, {"COMPOSE_TEST_JOBS": ""}):
            code = run.main(["-j", "2", *argv])
        return code, err.getvalue()

    def test_a_passing_suite_prints_unittests_summary_and_exits_zero(self):
        code, out = self.go(self.make_dir(a=PASSING, b=PASSING.replace("class A", "class C")))
        self.assertEqual(code, 0)
        self.assertRegex(out, r"(?m)^Ran 4 tests in \d+\.\d{3}s\n\nOK$")
        self.assertEqual(fc_gate.FAILING_RE.findall(out), [])

    def test_failures_errors_and_skips_are_counted_across_files_and_named_for_the_gate(self):
        code, out = self.go(self.make_dir(a=PASSING, b=MIXED, broken="import no_such_module_anywhere\n"))
        self.assertEqual(code, 1)
        self.assertRegex(out, r"(?m)^Ran 7 tests in \d+\.\d{3}s\n\nFAILED \(failures=1, errors=2, skipped=1\)$")
        self.assertEqual(sorted(fc_gate.FAILING_RE.findall(out)), sorted([
            "test_bad (test_b.B.test_bad)", "test_boom (test_b.B.test_boom)", "test_broken (unittest.loader._FailedTest.test_broken)"]))
        self.assertIn("AssertionError: 1 != 2", out)
        self.assertIn("RuntimeError: boom", out)

    def test_a_file_that_dies_without_a_summary_is_one_error_named_after_it(self):
        code, out = self.go(self.make_dir(a=PASSING, dies="import os\nos._exit(3)\n"))
        self.assertEqual(code, 1)
        self.assertEqual(fc_gate.FAILING_RE.findall(out), ["test_dies.py (exit 3, no result)"])
        self.assertRegex(out, r"(?m)^Ran 2 tests in \d+\.\d{3}s\n\nFAILED \(errors=1\)$")

    def test_named_files_run_alone_with_or_without_the_prefix_and_extension(self):
        d = self.make_dir(a=PASSING, b=MIXED)
        code, out = self.go(d, "a", "test_a.py")
        self.assertEqual((code, "Ran 2 tests" in out, "test_b" in out), (0, True, False))
        with self.assertRaises(SystemExit) as e:
            self.go(d, "nope")
        self.assertIn("nope", str(e.exception))

    def test_files_run_side_by_side_up_to_the_job_count(self):
        times = Path(tempfile.mkdtemp()) / "times"
        d = self.make_dir(a=TIMES, b=TIMES.replace("class T", "class U"))
        with mock.patch.dict(os.environ, {"TIMES": str(times)}):
            code, _ = self.go(d)
        self.assertEqual(code, 0)
        marks = [l.split()[0] for l in sorted(times.read_text().splitlines(), key=lambda l: float(l.split()[1]))]
        self.assertEqual(marks, ["start", "start", "end", "end"])

    def test_jobs_default_to_a_quarter_of_the_cores_never_under_one_and_the_env_overrides(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("COMPOSE_TEST_JOBS", None)
            for cores, want in ((64, 16), (16, 4), (8, 2), (7, 1), (4, 1), (3, 1), (1, 1), (None, 1)):
                with mock.patch("os.cpu_count", return_value=cores):
                    self.assertEqual(run.default_jobs(), want, cores)
            with mock.patch("os.cpu_count", return_value=16):
                for env, want in (("3", 3), ("9", 9), ("0", 1)):
                    os.environ["COMPOSE_TEST_JOBS"] = env
                    self.assertEqual(run.default_jobs(), want, env)

    def test_a_killed_runner_takes_its_test_processes_with_it(self):
        pids = Path(tempfile.mkdtemp()) / "pid"
        d = self.make_dir(hang=textwrap.dedent("""\
            import os, time, unittest
            class H(unittest.TestCase):
                def test_h(self):
                    open(os.environ["PIDS"], "w").write(str(os.getpid()))
                    time.sleep(60)
            """))
        code = ("import importlib.util, pathlib, sys\n"
                f"s = importlib.util.spec_from_file_location('r', {str(RUN)!r}); m = importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
                "m.TESTS = pathlib.Path(sys.argv[1]); sys.exit(m.main(['-j', '1']))\n")
        p = subprocess.Popen([sys.executable, "-c", code, str(d)], env={**os.environ, "PIDS": str(pids)}, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: p.poll() is None and p.kill())
        t0 = time.time()
        while not (pids.exists() and pids.read_text()) and time.time() - t0 < 30:
            time.sleep(0.05)
        child = int(pids.read_text())
        self.addCleanup(lambda: os.path.exists(f"/proc/{child}") and os.kill(child, signal.SIGKILL))
        p.send_signal(signal.SIGTERM)
        self.assertEqual(p.wait(timeout=30), 128 + signal.SIGTERM)
        time.sleep(0.5)
        with self.assertRaises(ProcessLookupError):
            os.kill(child, 0)


if __name__ == "__main__":
    unittest.main()
