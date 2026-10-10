import json, os, subprocess, tempfile, unittest
from pathlib import Path

CLI = str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")
ENV = {**os.environ, "HERDR_ENV": "", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


class InitAfter(unittest.TestCase):
    """An epic's dependent feature: `init --after a` starts project b from a's branch and shows it."""
    def fc(self, *args, check=True):
        p = subprocess.run([CLI, *args, "--repo", str(self.repo)], capture_output=True, text=True, env=ENV)
        if check:
            self.assertEqual(p.returncode, 0, p.stderr)
        return p

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp()) / "repo"
        self.repo.mkdir()
        git = lambda *a: subprocess.run(["git", *a], cwd=self.repo, check=True, capture_output=True, env=ENV)
        git("init", "-q", "-b", "main")
        (self.repo / "a.txt").write_text("base\n")
        git("add", "-A"); git("commit", "-qm", "init")

    def test_dependent_project_starts_from_the_other_projects_branch(self):
        self.fc("init", "--project", "a")
        a_wt = self.repo.parent / "fast-coding-a"
        (a_wt / "feature_a.txt").write_text("a\n")
        subprocess.run(["git", "add", "-A"], cwd=a_wt, check=True, env=ENV)
        subprocess.run(["git", "commit", "-qm", "a"], cwd=a_wt, check=True, env=ENV)
        self.fc("init", "--project", "b", "--after", "a")
        b_wt = self.repo.parent / "fast-coding-b"
        self.assertTrue((b_wt / "feature_a.txt").exists())  # b sits on a's code
        self.assertEqual(json.loads((b_wt / ".fast-coding" / "b" / "verify.json").read_text())["review_base"], "fast-coding/a")
        self.assertEqual(json.loads((a_wt / ".fast-coding" / "a" / "verify.json").read_text())["review_base"], "main")
        listing = self.fc("projects").stdout
        self.assertIn("(after a)", [l for l in listing.splitlines() if l.startswith("b ")][0])
        self.assertNotIn("(after", [l for l in listing.splitlines() if l.startswith("a ")][0])
        self.assertIn("trunk fast-coding/b (after a)", self.fc("status", "--project", "b").stdout)

    def test_clean_counts_a_merge_into_the_base_project(self):
        self.fc("init", "--project", "a")
        self.fc("init", "--project", "b", "--after", "a")
        a_wt, b_wt = self.repo.parent / "fast-coding-a", self.repo.parent / "fast-coding-b"
        (b_wt / "feature_b.txt").write_text("b\n")
        subprocess.run(["git", "add", "-A"], cwd=b_wt, check=True, env=ENV)
        subprocess.run(["git", "commit", "-qm", "b"], cwd=b_wt, check=True, env=ENV)
        self.assertIn("not merged yet", self.fc("clean", "--project", "b").stdout)
        subprocess.run(["git", "merge", "-q", "--no-edit", "fast-coding/b"], cwd=a_wt, check=True, capture_output=True, env=ENV)
        self.assertIn("contained in fast-coding/a", self.fc("clean", "--project", "b").stdout)
        self.assertFalse(b_wt.exists())

    def test_after_an_unknown_project_refuses(self):
        p = self.fc("init", "--project", "b", "--after", "nope", check=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("no branch fast-coding/nope", p.stderr)
        self.assertFalse((self.repo.parent / "fast-coding-b").exists())


if __name__ == "__main__":
    unittest.main()

