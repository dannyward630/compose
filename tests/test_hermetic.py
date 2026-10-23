import hermetic  # first: no test sees the real home
import io, json, os, shutil, subprocess, sys, tempfile, time, types, unittest
from pathlib import Path
from unittest import mock
from cleanup_kit import fc
os.environ["HERDR_ENV"] = ""


class HermeticCleanup(unittest.TestCase):
    """Every temp dir a test makes is gone when the test is: a suite run by many teammates at once must not fill the disk's temp folder."""

    def run_case(self, body):
        made = {}
        class Case(unittest.TestCase):
            def test_it(self):
                body(self, made)
        unittest.TextTestRunner(stream=io.StringIO()).run(unittest.defaultTestLoader.loadTestsFromTestCase(Case))
        return made

    def test_a_tests_mkdtemp_dirs_are_removed_after_it(self):
        made = self.run_case(lambda case, made: made.update(a=tempfile.mkdtemp(), b=Path(tempfile.mkdtemp(prefix="x-")) / "sub"))
        self.assertEqual([k for k, d in made.items() if Path(d).exists()], [])

    def test_a_tests_temp_home_is_removed_after_it(self):
        made = self.run_case(lambda case, made: made.update(home=os.environ["HOME"]))
        self.assertTrue(made["home"].startswith(tempfile.gettempdir()) or "/compose-home-" in made["home"], made["home"])
        self.assertFalse(Path(made["home"]).exists(), made["home"])

    def test_dirs_named_after_a_tests_mkdtemp_dir_go_with_it(self):
        """A pi turn keeps its sessions beside the task clone as <clone>.pi-sessions and a crew test adds a <repo>-slot worktree:
        made by mkdir, not mkdtemp, so only the dir they are named after is tracked; they go when it goes."""
        def body(case, made):
            d = tempfile.mkdtemp()
            for s in (".pi-sessions", "-slot"):
                Path(d + s).mkdir(); (Path(d + s) / "f").write_text("x")
                made[s] = d + s
        self.assertEqual([k for k, d in self.run_case(body).items() if Path(d).exists()], [])

    def test_a_tests_home_gives_trail_nothing_to_do_after_the_test(self):
        """trail (graft) spawns a detached child to check npm for a newer version when its cache is stale and another to flush
        telemetry; each writes under HOME after the test removed it, so the home came back as an empty .graft. The test home
        carries a fresh update cache and DO_NOT_TRACK, so neither child is spawned."""
        def body(case, made):
            made["dnt"] = os.environ.get("DO_NOT_TRACK")
            made["cache"] = json.loads((Path(os.environ["HOME"]) / ".graft" / "update-check.json").read_text())
        made = self.run_case(body)
        self.assertEqual(made["dnt"], "1")
        self.assertEqual(made["cache"]["latest"], None)
        self.assertLess(abs(made["cache"]["checkedAt"] - time.time() * 1000), 60_000)

    def test_the_dirs_of_a_test_survive_while_it_runs(self):
        def body(case, made):
            d = Path(tempfile.mkdtemp()); (d / "f").write_text("x")
            made["seen"] = (d / "f").read_text()
        self.assertEqual(self.run_case(body)["seen"], "x")

    def test_stubs_with_the_same_body_share_one_executable(self):
        """macOS scans every new executable file on its first run (about 150 ms of XprotectService each); a stub body
        seen before is linked to the file already scanned instead of being a new file."""
        def body(case, made):
            for n in ("a", "b"):
                d = Path(tempfile.mkdtemp()); (d / "gh").write_text("#!/bin/sh\necho 1.0.0\n"); (d / "gh").chmod(0o755)
                made[n] = d / "gh"
            made["out"] = subprocess.run([str(made["a"])], capture_output=True, text=True).stdout
            made["links"] = (made["a"].is_symlink(), made["b"].is_symlink())
            made["same"] = made["a"].resolve() == made["b"].resolve()
        made = self.run_case(body)
        self.assertEqual((made["out"], made["links"], made["same"]), ("1.0.0\n", (True, True), True))

    def test_stubs_with_different_bodies_are_different_executables(self):
        def body(case, made):
            for n, text in (("a", "#!/bin/sh\necho a\n"), ("b", "#!/bin/sh\necho b\n")):
                d = Path(tempfile.mkdtemp()); (d / "t").write_text(text); (d / "t").chmod(0o755)
                made[n] = subprocess.run([str(d / "t")], capture_output=True, text=True).stdout
        self.assertEqual(self.run_case(body), {"a": "a\n", "b": "b\n"})

    def test_a_stub_made_non_executable_again_is_its_own_file(self):
        def body(case, made):
            d = Path(tempfile.mkdtemp()); f = d / "gh"; f.write_text("#!/bin/sh\necho 1.0.0\n"); f.chmod(0o755)
            g = Path(tempfile.mkdtemp()) / "gh"; g.write_text("#!/bin/sh\necho 1.0.0\n"); g.chmod(0o755)
            f.chmod(0o644)
            made["f_exec"], made["g_exec"] = os.access(f, os.X_OK), os.access(g, os.X_OK)
            made["f_link"] = f.is_symlink()
        self.assertEqual(self.run_case(body), {"f_exec": False, "g_exec": True, "f_link": False})

    def test_a_stub_rewritten_in_place_runs_its_new_body_and_leaves_its_twin(self):
        def body(case, made):
            f = Path(tempfile.mkdtemp()) / "gh"; f.write_text("#!/bin/sh\necho 1.0.0\n"); f.chmod(0o755)
            g = Path(tempfile.mkdtemp()) / "gh"; g.write_text("#!/bin/sh\necho 1.0.0\n"); g.chmod(0o755)
            f.write_text("#!/bin/sh\necho 2.0.0\n")  # no chmod again: it stays executable
            made["f"], made["g"] = subprocess.run([str(f)], capture_output=True, text=True).stdout, g.read_text()
            h = Path(tempfile.mkdtemp()) / "gh"; h.write_text("#!/bin/sh\necho 1.0.0\n"); h.chmod(0o755)
            made["h"] = subprocess.run([str(h)], capture_output=True, text=True).stdout
        self.assertEqual(self.run_case(body), {"f": "2.0.0\n", "g": "#!/bin/sh\necho 1.0.0\n", "h": "1.0.0\n"})


class HermeticMachine(unittest.TestCase):
    """No test touches the real machine: lsof and herdr on PATH are fakes, and a process a test registers dies with it."""

    def process(self, cwd):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"], cwd=cwd)
        p.cwd = cwd
        self.addCleanup(lambda: (p.kill(), p.wait()))
        return p

    def alive(self, p):
        deadline = time.time() + 5
        while p.poll() is None and time.time() < deadline:
            time.sleep(0.05)
        return p.poll() is None

    def test_lsof_and_herdr_on_the_path_are_the_fakes(self):
        self.assertEqual(Path(shutil.which("lsof")).parent, hermetic.guard_dir())
        self.assertEqual(Path(shutil.which("herdr")).parent, hermetic.guard_dir())
        self.assertNotEqual(os.environ.get("HERDR_ENV"), "1")  # the suite is no pane of the user's herdr
        for var in ("HERDR_SOCKET_PATH", "HERDR_SESSION", "HERDR_BIN_PATH", "HERDR_TAB_ID"):
            self.assertNotIn(var, os.environ)

    def test_the_fake_lsof_knows_only_the_listeners_a_test_registers(self):
        scan = lambda: subprocess.run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-t"], capture_output=True, text=True).stdout.split()
        self.assertEqual(scan(), [])
        p = self.process(tempfile.mkdtemp())
        hermetic.listen(p.pid, 8001, Path.cwd())
        self.assertEqual(scan(), [str(p.pid)])

    def test_listeners_under_asks_lsof_twice_however_many_servers_there_are(self):
        root = Path(tempfile.mkdtemp()).resolve()
        inside = [self.process(root) for _ in range(12)]
        outside = [self.process(tempfile.mkdtemp()) for _ in range(3)]
        for i, p in enumerate(inside + outside):
            hermetic.listen(p.pid, 9000 + i, Path(p.cwd).resolve())
        hermetic.guard_calls(clear=True)
        self.assertEqual(sorted(fc.fc_crew.listeners_under(root)), sorted(str(p.pid) for p in inside))
        self.assertEqual(len(hermetic.guard_calls("lsof")), 2, hermetic.guard_calls())
        hermetic.guard_calls(clear=True)
        self.assertEqual(fc.fc_crew.listeners_under(tempfile.mkdtemp()), [])
        self.assertEqual(len(hermetic.guard_calls("lsof")), 2)

    def test_kill_listeners_asks_lsof_once_for_all_the_ports(self):
        servers = {9100 + i: self.process(tempfile.mkdtemp()) for i in range(3)}
        for port, p in servers.items():
            hermetic.listen(p.pid, port, Path.cwd())
        keep = self.process(tempfile.mkdtemp())
        hermetic.listen(keep.pid, 9199, Path.cwd())
        hermetic.guard_calls(clear=True)
        fc.fc_jev.kill_listeners(set(servers))
        self.assertEqual(len(hermetic.guard_calls("lsof")), 1, hermetic.guard_calls())
        self.assertEqual([self.alive(p) for p in servers.values()], [False] * 3)
        self.assertTrue(self.alive(keep))

    def run_case(self, body):
        class Case(unittest.TestCase):
            def test_it(self):
                body(self)
        return unittest.TextTestRunner(stream=io.StringIO()).run(unittest.defaultTestLoader.loadTestsFromTestCase(Case))

    def test_a_test_that_starts_a_herdr_agent_starts_none_and_fails(self):
        def body(case):
            with mock.patch.dict(os.environ, {"HERDR_ENV": "1", "HERDR_SOCKET_PATH": "/nowhere/herdr.sock"}):
                case.assertIsNone(fc.fc_herdr.herdr("agent", "start", "p-tester", "--cwd", tempfile.mkdtemp()))
        result = self.run_case(body)
        self.assertEqual(len(result.failures), 1, result.errors)
        self.assertIn("real herdr", result.failures[0][1])
        self.assertIn("herdr agent start p-tester", result.failures[0][1])

    def test_a_test_that_reads_herdrs_version_is_not_a_failure(self):
        result = self.run_case(lambda case: case.assertEqual(subprocess.run(["herdr", "--version"], capture_output=True, text=True).returncode, 0))
        self.assertTrue(result.wasSuccessful(), result.failures)

    def test_a_process_a_test_registers_is_killed_when_the_test_ends(self):
        made = {}
        def body(case):
            made["p"] = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
            hermetic.listen(made["p"].pid, 9300, Path.cwd())
        self.run_case(body)
        self.addCleanup(lambda: (made["p"].kill(), made["p"].wait()))
        self.assertFalse(self.alive(made["p"]))


class HermeticModules(unittest.TestCase):
    """Test files reload every fc_* module at import, so the last file loaded owns sys.modules while the others run."""

    def test_a_test_runs_with_the_fc_modules_its_file_loaded(self):
        probes, seen, cases = [types.ModuleType("fc_probe"), types.ModuleType("fc_probe")], [], []
        self.addCleanup(sys.modules.pop, "fc_probe", None)
        for n, probe in zip("ab", probes):  # file a loads first and file b after it: only b's copy is left in sys.modules
            sys.modules["fc_probe"] = probe
            cases.append(type("Case", (unittest.TestCase,), {"__module__": "probe_file_" + n, "test_it": lambda case: seen.append(sys.modules["fc_probe"])}))
            self.addCleanup(hermetic._world.pop, "probe_file_" + n, None)
        unittest.TextTestRunner(stream=io.StringIO()).run(unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in cases))
        self.assertEqual(seen, probes)
        self.assertIs(sys.modules["fc_probe"], probes[1])  # and what sys.modules held is back after each test


class HermeticEnv(unittest.TestCase):
    def test_a_suite_under_a_timed_slot_holds_none_in_its_tests(self):
        """A suite run by `compose timed` gets its slot as COMPOSE_TEST_SLOT, a lock under the caller's home: kept, a test's own
        timed commands would take no slot in the test's temp home, and a test of the slots would see them all run at once."""
        r = subprocess.run([sys.executable, "-c", "import hermetic, os; print(os.environ.get('COMPOSE_TEST_SLOT'))"],
                           cwd=Path(__file__).parent, env={**os.environ, "COMPOSE_TEST_SLOT": "0"}, capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "None"), r.stderr)


class HermeticGitIdentity(unittest.TestCase):
    """A temp HOME has no ~/.gitconfig, so every test's environment carries a git identity."""
    IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

    def commit(self):
        """git init and an empty commit in a fresh dir, with no -c user.*; returns the exit code and `author|committer` of the commit."""
        repo = tempfile.mkdtemp()
        for args in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "x"]):
            r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
        log = subprocess.run(["git", "log", "-1", "--format=%an <%ae>|%cn <%ce>"], cwd=repo, capture_output=True, text=True)
        return log.stdout.strip()

    def test_temp_home_returns_the_identity_beside_its_other_keys(self):
        home = hermetic.temp_home()
        self.assertEqual({k: home.get(k) for k in self.IDENTITY}, self.IDENTITY)
        for k in ("HOME", "COMPOSE_CONFIG", "DO_NOT_TRACK", "COMPOSE_NO_PREFLIGHT", "COMPOSE_NO_AWAKE"):
            self.assertIn(k, home)

    def test_a_commit_in_a_test_needs_no_identity_of_its_own(self):
        self.assertEqual(self.commit(), "t <t@t>|t <t@t>")

    def test_a_tests_own_value_wins_and_the_environment_is_restored(self):
        for var, value, expect in (("GIT_AUTHOR_NAME", "me", "me <t@t>|t <t@t>"), ("GIT_COMMITTER_EMAIL", "me@x", "t <t@t>|t <me@x>")):
            with mock.patch.dict(os.environ, {var: value}):
                self.assertEqual(self.commit(), expect)
            self.assertEqual(os.environ[var], self.IDENTITY[var])
        self.assertEqual(self.commit(), "t <t@t>|t <t@t>")

    def test_the_docstring_names_the_identity_and_why(self):
        doc = hermetic.temp_home.__doc__
        for name in self.IDENTITY:
            self.assertIn(name, doc)
        self.assertIn(".gitconfig", doc)


if __name__ == "__main__":
    unittest.main()
