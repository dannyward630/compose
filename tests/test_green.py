import hermetic  # first: no test sees the real home
import io, json, os, shutil, subprocess, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import importlib.machinery, importlib.util, sys
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)

GIT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


class Repo(unittest.TestCase):
    """A git repo with one commit and a project folder beside it."""
    def setUp(self):
        root = Path(tempfile.mkdtemp()).resolve(); self.addCleanup(shutil.rmtree, root, True)
        self.repo, self.proj, self.counter = root / "repo", root / "proj", root / "runs"
        self.repo.mkdir(); self.proj.mkdir()
        env = mock.patch.dict(os.environ, GIT); env.start(); self.addCleanup(env.stop)
        self.git("init", "-q", "-b", "main")
        (self.repo / "a.txt").write_text("one\n")
        self.git("add", "-A"); self.git("commit", "-qm", "init")

    def git(self, *a):
        return subprocess.run(["git", *a], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def runs(self):
        return len(self.counter.read_text().split()) if self.counter.exists() else 0

    @property
    def count(self):
        return f"echo run >> {self.counter}"


class GreenStore(Repo):
    def test_a_green_result_is_taken_on_the_same_tree_and_command_with_one_line_saying_so(self):
        tree = fc.fc_green.tree_of(self.repo)
        fc.fc_green.record(self.proj, tree, "make test", 0)
        line = fc.fc_green.taken(self.proj, tree, "make test")
        self.assertRegex(line, rf"^make test green on tree {tree[:12]} at \S+( \S+)?, not rerun$")

    def test_a_red_unknown_other_command_or_other_tree_is_never_taken(self):
        tree = fc.fc_green.tree_of(self.repo)
        fc.fc_green.record(self.proj, tree, "make test", 1)
        fc.fc_green.record(self.proj, tree, "make lint", 124)
        self.assertIsNone(fc.fc_green.taken(self.proj, tree, "make test"))
        self.assertIsNone(fc.fc_green.taken(self.proj, tree, "make lint"))
        fc.fc_green.record(self.proj, tree, "make test", 0)
        self.assertIsNone(fc.fc_green.taken(self.proj, tree, "make other"))
        self.assertIsNone(fc.fc_green.taken(self.proj, "0" * 40, "make test"))
        self.assertIsNone(fc.fc_green.taken(self.proj, "", "make test"))

    def test_a_red_run_on_a_tree_takes_back_its_earlier_green(self):
        tree = fc.fc_green.tree_of(self.repo)
        fc.fc_green.record(self.proj, tree, "make test", 0)
        fc.fc_green.record(self.proj, tree, "make test", 1)
        self.assertIsNone(fc.fc_green.taken(self.proj, tree, "make test"))

    def test_fresh_takes_nothing(self):
        tree = fc.fc_green.tree_of(self.repo)
        fc.fc_green.record(self.proj, tree, "make test", 0)
        self.assertIsNone(fc.fc_green.taken(self.proj, tree, "make test", fresh=True))

    def test_the_tree_follows_the_files_not_the_commit_and_counts_uncommitted_edits(self):
        clean = fc.fc_green.tree_of(self.repo)
        self.assertEqual(clean, self.git("rev-parse", "HEAD^{tree}"))
        (self.repo / "a.txt").write_text("two\n")
        edited = fc.fc_green.tree_of(self.repo)
        (self.repo / "new.txt").write_text("n\n")
        added = fc.fc_green.tree_of(self.repo)
        self.assertEqual(len({clean, edited, added}), 3)
        self.assertEqual(self.git("status", "--porcelain").count("\n"), 1)  # reading the tree stages nothing
        self.git("add", "-A"); self.git("commit", "-qm", "same files")
        self.assertEqual(fc.fc_green.tree_of(self.repo), added)
        self.assertEqual(fc.fc_green.tree_of(self.repo, "HEAD~1"), clean)

    def test_a_folder_that_is_not_a_repo_has_no_tree(self):
        self.assertEqual(fc.fc_green.tree_of(Path(tempfile.mkdtemp())), "")


class VerifyChecks(Repo):
    def stages(self, checks, **kw):
        out = io.StringIO()
        with mock.patch.object(fc.fc_herdr, "herdr_verify_panes", return_value={}), redirect_stdout(out), mock.patch.object(fc.fc_core, "say", lambda s: print(s)):
            ok, report, _ = fc.fc_verify.run_stages(self.repo, self.proj, {"checks": checks}, SimpleNamespace(skip_e2e=True, skip_review=True, **kw))
        return ok, report, out.getvalue()

    def test_a_check_green_on_this_tree_is_not_run_again_and_says_so(self):
        self.assertTrue(self.stages([self.count])[0])
        ok, report, said = self.stages([self.count])
        self.assertTrue(ok)
        self.assertEqual(self.runs(), 1)
        self.assertRegex(said, rf"{self.count} green on tree {fc.fc_green.tree_of(self.repo)[:12]} at .*, not rerun")
        self.assertEqual([(c["cmd"], c["exit"]) for c in report["checks"]], [(self.count, 0)])  # the report still lists it, passed

    def test_a_changed_tree_a_red_result_and_fresh_run_the_check(self):
        self.stages([self.count])
        (self.repo / "a.txt").write_text("two\n")
        self.stages([self.count])
        self.assertEqual(self.runs(), 2)
        self.stages([self.count], fresh=True)
        self.assertEqual(self.runs(), 3)
        flag = self.proj / "flag"
        red = f"{self.count}; test -f {flag}"
        self.assertFalse(self.stages([red])[0])
        self.assertFalse(self.stages([red])[0])
        self.assertEqual(self.runs(), 5)


class PassGate(unittest.TestCase):
    """run_task twice over the same base with the same edit: the second pass takes what the first proved on that tree."""
    def run_task(self, root, redo):
        repo, proj = root / "repo", root / "proj"
        task = {"id": "001", "title": "answer", "files": ["a.txt"], "protected": [], "test": f"echo test >> {root}/tests; grep -q yes a.txt",
                "model": "pi:p/primary", "after": "", "linear": "ENG-1", "body": "## Goal\nWrite yes."}
        def impl(cwd, model, prompt, session=None, task=None, timeout=None):
            (Path(cwd) / "a.txt").write_text("yes\n")
            return "s", "", 1, {"tokens_in": 1, "tokens_out": 1, "cost": 0.0}
        said = io.StringIO()
        with mock.patch.object(fc.fc_implement, "implementer", impl), mock.patch.object(fc.fc_implement, "trail_pack", return_value=""), \
                mock.patch.object(fc.fc_config, "TEST_READER", None), mock.patch.dict(os.environ, {**GIT, **({"COMPOSE_REDO": "1"} if redo else {})}), redirect_stdout(said):
            result = fc.fc_implement.run_task(repo, proj, task, 2)
        return result, said.getvalue()

    def test_a_check_and_a_test_green_on_this_tree_are_not_run_again_by_the_second_pass(self):
        root = Path(tempfile.mkdtemp()).resolve(); self.addCleanup(shutil.rmtree, root, True)
        repo, proj = root / "repo", root / "proj"; repo.mkdir(); proj.mkdir()
        git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, env={**os.environ, **GIT})
        git("init", "-q", "-b", "main"); (repo / "a.txt").write_text("no\n"); git("add", "-A"); git("commit", "-qm", "init")
        (proj / "verify.json").write_text(json.dumps({"checks": [f"echo check >> {root}/checks"]}))
        first, _ = self.run_task(root, redo=False)
        second, said = self.run_task(root, redo=True)
        self.assertEqual((first["status"], second["status"]), ("passed", "passed"))
        self.assertEqual((root / "checks").read_text().split(), ["check"])
        self.assertEqual((root / "tests").read_text().split(), ["test"] * 3)  # red on the base twice, green once
        self.assertIn("green on tree", said)
        self.assertIn("not rerun", said)


if __name__ == "__main__":
    unittest.main()
