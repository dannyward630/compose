import hermetic  # first: no test sees the real home
import io, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock
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
