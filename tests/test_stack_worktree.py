import importlib.machinery, importlib.util, json, os, subprocess, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)

ENV = {"HERDR_ENV": "", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


class StackWorktree(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, ENV); self.env.start(); self.addCleanup(self.env.stop)
        self.repo = Path(tempfile.mkdtemp())
        self.git("init", "-q", "-b", "main")
        (self.repo / "a.txt").write_text("base\n")
        self.git("add", "-A"); self.git("commit", "-qm", "init")
        self.proj = self.repo / ".fast-coding" / "p"
        (self.proj / "results").mkdir(parents=True)
        (self.proj / "linear.json").write_text(json.dumps({"feature": "ENG-1"}))
        (self.repo / ".git" / "info" / "exclude").write_text("/.fast-coding/\n")

    def git(self, *a):
        return subprocess.run(["git", *a], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def test_the_stack_worktree_sees_the_tool_dir(self):
        (self.proj / "e2e").mkdir(); (self.proj / "e2e" / "assert.sh").write_text("true\n")
        wt = fc.stack_worktree(self.repo, self.proj, "main")
        self.assertTrue((wt / ".fast-coding" / "p" / "e2e" / "assert.sh").exists())
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(subprocess.run(["git", "status", "--porcelain"], cwd=wt, capture_output=True, text=True).stdout, "")


class ReviewGate(unittest.TestCase):
    def test_confirmed_review_findings_fail_verify(self):
        proj = Path(tempfile.mkdtemp()) / "p"; (proj / "results").mkdir(parents=True)
        (proj / "linear.json").write_text(json.dumps({"feature": "ENG-1"}))
        high = {"file": "s.go", "severity": "high", "note": "a query per answer", "confirmed": True}
        rv = {"pass": False, "issues": [high], "confirmed": [high]}
        a = SimpleNamespace(skip_e2e=True, skip_review=False)
        with mock.patch.dict(os.environ, {"HERDR_ENV": ""}), mock.patch.object(fc, "llm_review", return_value=rv), \
                mock.patch.object(fc, "review_inputs", return_value=("diff", "plan", "", [])):
            ok, _, findings = fc.run_stages(proj, proj, {"review": True, "jev_acceptance": False}, a)
        self.assertFalse(ok); self.assertIn("a query per answer", findings)


if __name__ == "__main__":
    unittest.main()
