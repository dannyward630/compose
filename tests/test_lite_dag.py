import importlib.machinery, importlib.util, json, os, subprocess, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)

ENV = {"HERDR_ENV": "", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


class LiteDag(unittest.TestCase):
    """A lite project never rebases tasks into one chain mid-run: a task builds on its dependency, or on a merge of several,
    and verify merges every task branch into the project branch."""
    def setUp(self):
        self.env = mock.patch.dict(os.environ, ENV); self.env.start()
        self.repo = Path(tempfile.mkdtemp())
        self.git("init", "-q", "-b", "main")
        (self.repo / "a.txt").write_text("base\n")
        self.git("add", "-A"); self.git("commit", "-qm", "init")
        self.proj = self.repo / ".fast-coding" / "p"
        (self.proj / "results").mkdir(parents=True)
        (self.proj / "linear.json").write_text(json.dumps({"feature": "p", "lite": True}))
        (self.repo / ".git" / "info" / "exclude").write_text("/.fast-coding/\n")
        tasks = [{"id": "001"}, {"id": "002"}, {"id": "003", "after": "001,002"}]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))

    def tearDown(self):
        self.env.stop()

    def git(self, *a):
        return subprocess.run(["git", *a], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def task(self, tid, name, text):
        self.git("checkout", "-q", "-b", f"fast/p/{tid}", "main")
        (self.repo / name).write_text(text)
        self.git("add", "-A"); self.git("commit", "-qm", f"task {tid}")
        self.git("checkout", "-q", "main")

    def test_several_dependencies_merge_and_nothing_is_linearized(self):
        self.task("001", "b.txt", "b\n"); self.task("002", "c.txt", "c\n")
        with mock.patch.object(fc, "_linearize", side_effect=AssertionError("lite must not linearize")):
            name, sha = fc.task_base(self.repo, self.proj, {"after": "001,002"})
            self.assertTrue(name.startswith("merge of"))
            self.assertEqual(sorted(self.git("ls-tree", "--name-only", sha).split()), ["a.txt", "b.txt", "c.txt"])
            self.assertEqual(fc.task_base(self.repo, self.proj, {"after": "001"})[0], "fast/p/001")
            fc.land_lite(self.repo, self.proj)
        self.assertEqual(self.git("branch", "--show-current"), "main")
        self.assertTrue((self.repo / "b.txt").exists() and (self.repo / "c.txt").exists())

    def test_landing_is_linear_with_plain_messages(self):
        self.task("001", "b.txt", "b\n"); self.task("002", "c.txt", "c\n")
        _, sha = fc.task_base(self.repo, self.proj, {"after": "001,002"})  # 003 builds on a merge of its dependencies
        self.git("checkout", "-q", "-b", "fast/p/003", sha)
        (self.repo / "d.txt").write_text("d\n"); self.git("add", "-A"); self.git("commit", "-qm", "task 003")
        self.git("checkout", "-q", "main")
        fc.land_lite(self.repo, self.proj)
        self.assertEqual(self.git("rev-list", "--merges", "main"), "")
        msgs = self.git("log", "--format=%s", "main").splitlines()
        self.assertEqual(msgs[:3], ["task 003", "task 002", "task 001"])
        self.assertFalse([m for m in msgs if "fast/" in m or "fast-coding" in m])
        self.assertEqual(sorted(self.git("ls-tree", "--name-only", "main").split()), ["a.txt", "b.txt", "c.txt", "d.txt"])
        self.assertEqual(fc.stack_order(self.repo, self.proj), [])  # every task now reads as landed
        fc.land_lite(self.repo, self.proj)  # landing again adds nothing
        self.assertEqual(len(self.git("log", "--format=%s", "main").splitlines()), len(msgs))

    def test_landing_conflict_names_the_task(self):
        self.task("001", "a.txt", "one\n")
        (self.repo / "a.txt").write_text("other\n"); self.git("commit", "-qam", "trunk change")
        with self.assertRaisesRegex(SystemExit, "task 001"):
            fc.land_lite(self.repo, self.proj)
        self.assertEqual(self.git("status", "--porcelain"), "")

    def test_overlapping_dependencies_fail_clearly(self):
        self.task("001", "a.txt", "one\n"); self.task("002", "a.txt", "two\n")
        with self.assertRaisesRegex(RuntimeError, "conflict when merged"):
            fc.task_base(self.repo, self.proj, {"after": "001,002"})


class LiteReview(unittest.TestCase):
    def run_review(self, lite):
        proj = Path(tempfile.mkdtemp()) / "p"; (proj / "results").mkdir(parents=True)
        (proj / "linear.json").write_text(json.dumps({"feature": "p", "lite": lite}))
        high = {"file": "s.go", "severity": "high", "note": "a query per answer", "confirmed": True}
        rv = {"pass": False, "issues": [high], "confirmed": [high]}
        a = SimpleNamespace(skip_e2e=True, skip_review=False)
        with mock.patch.dict(os.environ, {"HERDR_ENV": ""}), mock.patch.object(fc, "llm_review", return_value=rv), \
                mock.patch.object(fc, "review_inputs", return_value=("diff", "plan", "", [])):
            return fc.run_stages(proj, proj, {"review": True, "jev_acceptance": False}, a)

    def test_review_findings_are_advisory_on_lite_only(self):
        ok, _, findings = self.run_review(lite=True)
        self.assertTrue(ok); self.assertEqual(findings, "")
        ok, _, findings = self.run_review(lite=False)
        self.assertFalse(ok); self.assertIn("a query per answer", findings)


if __name__ == "__main__":
    unittest.main()


class LiteTop(LiteDag):
    def test_top_merges_task_branches_without_rebasing_them(self):
        self.task("001", "b.txt", "one\n"); self.task("002", "c.txt", "two\n")
        before = {b: self.git("rev-parse", f"fast/p/{b}") for b in ("001", "002")}
        with mock.patch.object(fc, "linearize", side_effect=AssertionError("lite top must not linearize")), \
                mock.patch.object(fc, "project_dir", return_value=self.proj):
            fc.cmd_top(SimpleNamespace(repo=str(self.repo), project="p", detach=False))
        wt = self.proj / "worktrees" / ".stackroot"
        self.assertTrue((wt / "b.txt").exists() and (wt / "c.txt").exists())
        self.assertEqual(before, {b: self.git("rev-parse", f"fast/p/{b}") for b in ("001", "002")})

    def test_the_stack_worktree_sees_the_tool_dir(self):
        (self.proj / "e2e").mkdir(); (self.proj / "e2e" / "assert.sh").write_text("true\n")
        wt = fc.stack_worktree(self.repo, self.proj, "main")
        self.assertTrue((wt / ".fast-coding" / "p" / "e2e" / "assert.sh").exists())
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(subprocess.run(["git", "status", "--porcelain"], cwd=wt, capture_output=True, text=True).stdout, "")
