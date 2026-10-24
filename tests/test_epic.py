import hermetic  # first: no test sees the real home
import json, os, subprocess, tempfile, unittest
from pathlib import Path
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"  # these cover the plain-worktree path, not the treehouse pool
os.environ["HERDR_ENV"] = ""

CLI = str(Path(__file__).resolve().parents[1] / "bin" / "compose")
ENV = {**os.environ, "COMPOSE_NO_TRAIL": "1", "HERDR_ENV": "", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


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
        a_wt = self.repo.parent / "compose-a"
        (a_wt / "feature_a.txt").write_text("a\n")
        subprocess.run(["git", "add", "-A"], cwd=a_wt, check=True, env=ENV)
        subprocess.run(["git", "commit", "-qm", "a"], cwd=a_wt, check=True, env=ENV)
        self.fc("init", "--project", "b", "--after", "a")
        b_wt = self.repo.parent / "compose-b"
        self.assertTrue((b_wt / "feature_a.txt").exists())  # b sits on a's code
        self.assertEqual(json.loads((b_wt / ".compose" / "b" / "verify.json").read_text())["review_base"], "compose/a")
        self.assertEqual(json.loads((a_wt / ".compose" / "a" / "verify.json").read_text())["review_base"], "main")
        listing = self.fc("projects").stdout
        self.assertIn("(after a)", [l for l in listing.splitlines() if l.startswith("b ")][0])
        self.assertNotIn("(after", [l for l in listing.splitlines() if l.startswith("a ")][0])
        self.assertIn("trunk compose/b (after a)", self.fc("status", "--project", "b").stdout)

    def test_clean_counts_a_merge_into_the_base_project(self):
        self.fc("init", "--project", "a")
        self.fc("init", "--project", "b", "--after", "a")
        a_wt, b_wt = self.repo.parent / "compose-a", self.repo.parent / "compose-b"
        (b_wt / "feature_b.txt").write_text("b\n")
        subprocess.run(["git", "add", "-A"], cwd=b_wt, check=True, env=ENV)
        subprocess.run(["git", "commit", "-qm", "b"], cwd=b_wt, check=True, env=ENV)
        self.assertIn("not merged yet", self.fc("clean", "--project", "b").stdout)
        subprocess.run(["git", "merge", "-q", "--no-edit", "compose/b"], cwd=a_wt, check=True, capture_output=True, env=ENV)
        self.assertIn("contained in compose/a", self.fc("clean", "--project", "b").stdout)
        self.assertFalse(b_wt.exists())

    def test_after_on_an_existing_project_moves_it_when_empty_and_refuses_otherwise(self):
        self.fc("init", "--project", "a")
        a_wt, b_wt = self.repo.parent / "compose-a", self.repo.parent / "compose-b"
        git = lambda wt, *a: subprocess.run(["git", *a], cwd=wt, check=True, capture_output=True, text=True, env=ENV).stdout
        (a_wt / "feature_a.txt").write_text("a\n")
        git(a_wt, "add", "-A"); git(a_wt, "commit", "-qm", "a")
        self.fc("init", "--project", "b")
        vfile = b_wt / ".compose" / "b" / "verify.json"
        (b_wt / "dirty.txt").write_text("x\n")
        p = self.fc("init", "--project", "b", "--after", "a", check=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("uncommitted changes", p.stderr)
        self.assertEqual(json.loads(vfile.read_text())["review_base"], "main")
        (b_wt / "dirty.txt").unlink()
        self.fc("init", "--project", "b", "--after", "a")
        self.assertTrue((b_wt / "feature_a.txt").exists())
        self.assertEqual({k: json.loads(vfile.read_text())[k] for k in ("review_base", "after")}, {"review_base": "compose/a", "after": "a"})
        self.assertEqual(git(b_wt, "rev-parse", "HEAD"), git(a_wt, "rev-parse", "HEAD"))
        self.fc("init", "--project", "b", "--after", "a")  # the same --after again changes nothing

    def test_after_an_unknown_project_refuses(self):
        p = self.fc("init", "--project", "b", "--after", "nope", check=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("no branch compose/nope", p.stderr)
        self.assertFalse((self.repo.parent / "compose-b").exists())


class InitBase(unittest.TestCase):
    """init records the branch a project starts from as its review base, whatever the repo's trunk is called, and `init --after`
    reads it back: a base that names no branch is the default branch, and agent wiring a session hook rewrote is no change."""
    fc = InitAfter.fc

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp()) / "repo"
        self.repo.mkdir()
        self.git(self.repo, "init", "-q", "-b", "master")
        (self.repo / "a.txt").write_text("base\n")
        (self.repo / ".claude").mkdir()
        (self.repo / ".claude" / "settings.json").write_text("{}\n")
        self.git(self.repo, "add", "-A"); self.git(self.repo, "commit", "-qm", "init")

    def git(self, wt, *a):
        return subprocess.run(["git", *a], cwd=wt, check=True, capture_output=True, text=True, env=ENV).stdout.strip()

    def wt(self, name):
        return self.repo.parent / f"compose-{name}"

    def cfg(self, name, **change):
        f = self.wt(name) / ".compose" / name / "verify.json"
        if change:
            f.write_text(json.dumps({**json.loads(f.read_text()), **change}))
        return json.loads(f.read_text())

    def commit(self, name, file):
        (self.wt(name) / file).write_text(f"{file}\n")
        self.git(self.wt(name), "add", "-A"); self.git(self.wt(name), "commit", "-qm", file)

    def test_a_master_trunk_repo_records_master_and_a_recorded_main_reads_the_default_branch(self):
        self.fc("init", "--project", "a")
        self.fc("init", "--project", "b")
        self.fc("init", "--project", "c")
        self.assertEqual(self.cfg("b")["review_base"], "master")
        for p in ("b", "c"):
            self.cfg(p, review_base="main")  # as init wrote it for every project not made with --after
        self.commit("a", "feature_a.txt")
        self.fc("init", "--project", "b", "--after", "a")
        self.assertEqual(self.git(self.wt("b"), "rev-parse", "HEAD"), self.git(self.wt("a"), "rev-parse", "HEAD"))
        self.assertEqual((self.cfg("b")["review_base"], self.cfg("b")["after"]), ("compose/a", "a"))
        self.commit("c", "feature_c.txt")
        p = self.fc("init", "--project", "c", "--after", "a", check=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("1 commit of its own", p.stderr)
        self.assertEqual(self.cfg("c")["review_base"], "main")

    def test_a_project_started_on_a_feature_branch_is_based_on_it(self):
        self.fc("init", "--project", "a")
        self.commit("a", "feature_a.txt")
        self.git(self.repo, "checkout", "-q", "-b", "feat")
        (self.repo / "f.txt").write_text("f\n")
        self.git(self.repo, "add", "-A"); self.git(self.repo, "commit", "-qm", "feat")
        self.assertIn("(from feat)", self.fc("init", "--project", "c").stdout)
        self.assertEqual(self.cfg("c")["review_base"], "feat")
        self.fc("init", "--project", "d")
        self.cfg("d", review_base="master")  # recorded before init knew the branch it started from: feat's commit is still not d's own
        for p in ("c", "d"):
            self.fc("init", "--project", p, "--after", "a")
            self.assertEqual(self.git(self.wt(p), "rev-parse", "HEAD"), self.git(self.wt("a"), "rev-parse", "HEAD"), p)

    def test_after_moves_a_project_whose_only_change_is_the_agent_wiring_and_keeps_it(self):
        self.fc("init", "--project", "a")
        self.fc("init", "--project", "b")
        self.commit("a", "feature_a.txt")
        wiring = self.wt("b") / ".claude" / "settings.json"
        wiring.write_text('{"hooks": {"SessionStart": []}}\n')  # a graph tool's session hook rewrote the tracked file
        (self.wt("b") / "notes.txt").write_text("mine\n")
        p = self.fc("init", "--project", "b", "--after", "a", check=False)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("uncommitted changes (notes.txt)", p.stderr)
        self.assertNotIn("settings.json", p.stderr)
        (self.wt("b") / "notes.txt").unlink()
        self.fc("init", "--project", "b", "--after", "a")
        self.assertEqual(self.git(self.wt("b"), "rev-parse", "HEAD"), self.git(self.wt("a"), "rev-parse", "HEAD"))
        self.assertEqual(wiring.read_text(), '{"hooks": {"SessionStart": []}}\n')


if __name__ == "__main__":
    unittest.main()

