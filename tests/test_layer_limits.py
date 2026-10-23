import hermetic  # first: no test sees the real home
import os, shutil, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock
from layers_kit import ENV, fc, unit
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"
os.environ["HERDR_ENV"] = ""


class DeletionBudget(unittest.TestCase):
    """Task 014 (NEB-951): branch_budget counts a whole-file deletion and each delete: path as one line."""

    def repo(self, files):
        r = Path(tempfile.mkdtemp())
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=r, check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        for f, n in files.items():
            (r / f).parent.mkdir(parents=True, exist_ok=True); (r / f).write_text("".join(f"line {i}\n" for i in range(n)))
        git("add", "-A"); git("commit", "-q", "-m", "init")
        return r

    def budget(self, r, allowed, delete=()):
        return fc.fc_gate.branch_budget(r, "main", allowed=allowed, delete=delete)

    def test_deleting_a_400_line_file_the_task_owns_counts_one_line(self):
        r = self.repo({"big.py": 400, "keep.py": 3})
        (r / "big.py").unlink()
        self.assertEqual(self.budget(r, ["big.py"]), (1, [], []))

    def test_a_deleted_delete_directory_counts_one_line_and_its_files_are_not_stray(self):
        r = self.repo({"old/a.py": 100, "old/sub/b.py": 50, "keep.py": 3})
        shutil.rmtree(r / "old")
        self.assertEqual(self.budget(r, [], delete=["old/"]), (1, [], []))

    def test_a_deletion_outside_allowed_and_every_delete_path_is_still_stray(self):
        r = self.repo({"old/a.py": 100, "older.py": 80, "keep.py": 3})
        shutil.rmtree(r / "old"); (r / "older.py").unlink()
        self.assertEqual(self.budget(r, [], delete=["old"]), (2, [], ["older.py"]))

    def test_edits_lockfiles_and_an_emptied_file_count_as_before_beside_a_deletion(self):
        r = self.repo({"a.py": 5, "b.py": 10, "gone.py": 300})
        (r / "a.py").write_text("line 0\nchanged\nline 2\nline 3\nline 4\n"); (r / "b.py").write_text("")
        (r / "yarn.lock").write_text("x\n" * 5000); (r / "gone.py").unlink()
        self.assertEqual(self.budget(r, ["a.py", "b.py", "yarn.lock", "gone.py"]), (2 + 10 + 1, [], []))


class WholeFileDeletion(unittest.TestCase):
    """Task 018: commit_facts counts a file the commit deletes whole as one line."""

    def facts(self, files, change):
        r = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, r, True)
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=r, check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        for f, t in files.items():
            (r / f).parent.mkdir(parents=True, exist_ok=True); (r / f).write_bytes(t if isinstance(t, bytes) else "".join(f"line {i}\n" for i in range(t)).encode())
        git("add", "-A"); git("commit", "-q", "-m", "init")
        change(r); git("add", "-A"); git("commit", "-q", "-m", "change")
        return fc.fc_layers.commit_facts(r, "HEAD")

    def test_a_whole_file_deletion_counts_one_line(self):
        self.assertEqual(self.facts({"old.py": 400, "a.py": 3}, lambda r: (r / "old.py").unlink()), (["old.py"], 1, {}))

    def test_a_deletion_beside_an_edit_counts_one_plus_the_edit(self):
        def change(r):
            (r / "old.py").unlink(); (r / "a.py").write_text((r / "a.py").read_text() + "x\n" * 5)
        files, counted, generated = self.facts({"old.py": 400, "a.py": 3}, change)
        self.assertEqual((sorted(files), counted, generated), (["a.py", "old.py"], 6, {}))

    def test_an_emptied_file_still_counts_every_line(self):
        self.assertEqual(self.facts({"old.py": 400}, lambda r: (r / "old.py").write_text("")), (["old.py"], 400, {}))

    def test_a_deleted_lockfile_stays_generated_with_its_full_count(self):
        got = self.facts({"package-lock.json": 300, "a.py": 3}, lambda r: (r / "package-lock.json").unlink())
        self.assertEqual(got, (["package-lock.json"], 0, {"package-lock.json": 300}))

    def test_each_deleted_file_counts_one_even_in_a_subdirectory_or_binary(self):
        files = {"old/a.py": 100, "old/sub/b.py": 50, "logo.png": bytes(range(256)) * 4, "keep.py": 3}
        got = self.facts(files, lambda r: (shutil.rmtree(r / "old"), (r / "logo.png").unlink()))
        self.assertEqual((sorted(got[0]), got[1], got[2]), (["logo.png", "old/a.py", "old/sub/b.py"], 3, {}))

    def test_a_moved_file_counts_its_old_path_as_one_and_its_new_path_in_full(self):
        got = self.facts({"old.py": 400, "a.py": 3}, lambda r: (r / "old.py").rename(r / "new.py"))
        self.assertEqual((sorted(got[0]), got[1], got[2]), (["new.py", "old.py"], 401, {}))

    def test_a_delete_only_unit_shares_the_layer_of_the_200_line_unit_before_it(self):
        lines = self.facts({"old.py": 400, "a.py": 3}, lambda r: (r / "old.py").unlink())[1]
        layers = fc.fc_layers.group_units([unit("001", 200), unit("002", lines)], 300)
        self.assertEqual([[u["name"] for u in g] for g in layers], [["001", "002"]])


class FailingIds(unittest.TestCase):
    def ids(self, out):
        return fc.fc_gate.FAILING_RE.findall(out)

    def test_a_unittest_summary_line_is_never_a_test_id(self):
        for summary in ("FAILED (failures=3)", "FAILED (errors=2)", "FAILED (failures=1, errors=1)", "FAILED (skipped=2)", "FAILED (failures=1, errors=1, skipped=2)"):
            self.assertEqual(self.ids(f"Ran 5 tests in 0.1s\n\n{summary}\n"), [], summary)

    def test_real_ids_from_each_runner_still_match(self):
        out = ("FAIL: test_x (mod.Class.test_x)\nERROR: test_z (mod.Class.test_z)\nFAILED (failures=1, errors=1)\n"
               "FAILED tests/x.py::test_y - AssertionError\nnot ok 1 - name\n--- FAIL: TestX (0.00s)\n")
        self.assertEqual(self.ids(out), ["test_x (mod.Class.test_x)", "test_z (mod.Class.test_z)", "tests/x.py::test_y - AssertionError", "name", "TestX"])

    def test_the_same_failing_ids_under_a_different_summary_are_no_regression(self):
        state = lambda summary: {"c": {"exit": 1, "failing": sorted(set(self.ids(f"FAIL: test_a (m.C.test_a)\n{summary}\n")))}}
        self.assertEqual(fc.fc_gate.regressions(state("FAILED (errors=3)"), state("FAILED (failures=3)")), ([], []))


class UnknownBaseline(unittest.TestCase):
    def run_of(self, script, limit=1):
        return lambda cmd, wt, lim, env=None: fc.fc_implement.timed(script, wt, lim, env=env)

    def repo(self, d, name=""):
        """(repo, head): a one-commit repo in `d/name`, the base a baseline is taken on."""
        d = Path(d, name); d.mkdir(exist_ok=True)
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=d, check=True, capture_output=True, text=True).stdout.strip()
        git("init", "-q"); git("commit", "-q", "--allow-empty", "-m", "init")
        return Path(d), git("rev-parse", "HEAD")

    def test_a_baseline_cut_off_by_its_limit_is_unknown_and_not_kept(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(fc.fc_gate, "CHECKS_TIMEOUT", 1):
            script = "echo 'FAIL: test_a (t.T.test_a)'; python3 -c \"print('x' * 5000)\"; sleep 30"
            repo, head = self.repo(d)
            got = fc.fc_gate.baseline_state(self.run_of(script), ["suite"], repo, (head, ()), 1)
            self.assertEqual((got["suite"]["exit"], got["suite"]["unknown"]), (124, True))
            self.assertNotIn(((head, ()), ("suite",)), fc.fc_gate.BASELINES)

    def test_a_clean_or_listed_baseline_is_known_and_kept(self):
        with tempfile.TemporaryDirectory() as d:
            for name, script, exit_ in (("clean", "true", 0), ("listed", "echo 'FAIL: test_a (t.T.test_a)'; exit 1", 1)):
                repo, head = self.repo(d, name)
                got = fc.fc_gate.baseline_state(self.run_of(script), [name], repo, (head, ()), 5)
                self.assertEqual((got[name]["exit"], got[name]["unknown"]), (exit_, False))
                self.assertIn(((head, ()), (name,)), fc.fc_gate.BASELINES)

    def test_a_non_zero_exit_that_lists_no_id_is_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            got = fc.fc_gate.check_state(self.run_of("echo boom; exit 2"), ["c"], Path(d), 5)
            self.assertEqual((got["c"]["failing"], got["c"]["unknown"]), ([], True))

    def test_an_id_red_on_an_unknown_baseline_rejects_only_when_the_diff_reaches_its_test(self):
        before = {"c": {"exit": 124, "failing": [], "unknown": True}}
        after = {"c": {"exit": 1, "failing": ["test_a (tests.test_ship.S.test_a)", "test_b (tests.test_other.O.test_b)"], "unknown": False}}
        broke, unknown = fc.fc_gate.regressions(before, after, lambda tid: "test_ship" in tid)
        self.assertEqual((broke, unknown), (["test_a (tests.test_ship.S.test_a)"], ["test_b (tests.test_other.O.test_b)"]))

    def test_an_id_red_on_a_known_baseline_is_never_excused(self):
        before = {"c": {"exit": 0, "failing": [], "unknown": False}}
        after = {"c": {"exit": 1, "failing": ["test_a (tests.test_ship.S.test_a)"], "unknown": False}}
        self.assertEqual(fc.fc_gate.regressions(before, after, lambda tid: False), (["test_a (tests.test_ship.S.test_a)"], []))

    def test_touches_names_the_test_file_and_the_modules_it_imports(self):
        with tempfile.TemporaryDirectory() as d:
            wt = Path(d)
            sh = lambda *a: subprocess.run(a, cwd=d, check=True, capture_output=True, env={**os.environ, **ENV})
            (wt / "tests").mkdir(); (wt / "bin").mkdir()
            (wt / "tests" / "test_ship.py").write_text("import fc_ship\nfc = load()\nfc.fc_status.x()\n")
            (wt / "tests" / "test_other.py").write_text("import unittest\n")
            for f in ("fc_ship", "fc_status", "fc_other"):
                (wt / "bin" / (f + ".py")).write_text("x = 1\n")
            sh("git", "init", "-q"); sh("git", "add", "-A"); sh("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
            ship, status, other = "test_a (tests.test_ship.S.test_a)", "test_b (tests.test_other.O.test_b)", "tests/test_ship.py::test_c - assert"
            (wt / "bin" / "fc_status.py").write_text("x = 2\n")
            check = fc.fc_gate.touches(wt, "HEAD")
            self.assertEqual((check(ship), check(status), check(other)), (False, False, False))  # fc_status is named in no import line
            (wt / "bin" / "fc_ship.py").write_text("x = 2\n")
            check = fc.fc_gate.touches(wt, "HEAD")
            self.assertEqual((check(ship), check(status), check(other)), (True, False, True))
            (wt / "tests" / "test_other.py").write_text("import unittest\nx = 1\n")
            self.assertTrue(fc.fc_gate.touches(wt, "HEAD")(status))
            self.assertFalse(fc.fc_gate.touches(wt, "HEAD")("TestUnnamed"))
            sh("git", "add", "-A")
            check = fc.fc_gate.touches(wt, "HEAD", ["bin/fc_status.py"])  # the changed files given: the diff of the checkout is not read
            self.assertEqual((check(ship), check(status), check(other)), (False, False, False))
            check = fc.fc_gate.touches(wt, "HEAD", ["tests/test_other.py", "bin/fc_ship.py"])
            self.assertEqual((check(ship), check(status), check(other)), (True, True, True))
            self.assertFalse(fc.fc_gate.touches(wt, "HEAD", [])(ship))


if __name__ == "__main__":
    unittest.main()
