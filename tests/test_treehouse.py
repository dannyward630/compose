import importlib.machinery, importlib.util, json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)

CLI = str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")
GIT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


@unittest.skipUnless(shutil.which("treehouse"), "treehouse is not installed")
class Treehouse(unittest.TestCase):
    """Real treehouse, in-project pools inside temp repos, so the tests never touch ~/.treehouse."""
    def setUp(self):
        self.env = {**os.environ, **GIT, "HERDR_ENV": "", "FAST_CODING_NO_GRAFT": "1", "FAST_CODING_NO_TREEHOUSE": ""}
        p = mock.patch.dict(os.environ, self.env); p.start(); self.addCleanup(p.stop)
        self.repo = Path(tempfile.mkdtemp()).resolve() / "app"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        (self.repo / ".gitignore").write_text("node_modules/\n")
        (self.repo / "a.txt").write_text("a\n")
        self.git("add", "-A"); self.git("commit", "-qm", "init")
        self.addCleanup(shutil.rmtree, self.repo.parent, True)

    def git(self, *a, cwd=None):
        return subprocess.run(["git", *a], cwd=cwd or self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def status(self):
        out = subprocess.run(["treehouse", "--root", ".", "status", "--json"], cwd=self.repo, capture_output=True, text=True).stdout
        return {Path(e["path"]).resolve(): e["status"] for e in json.loads(out or "[]")}

    def init(self):
        p = subprocess.run([CLI, "init", "--project", "p", "--repo", str(self.repo)], capture_output=True, text=True, env=self.env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return fc.all_projects(self.repo)["p"]

    def test_project_is_a_slot_in_the_repos_own_pool_and_the_user_checkout_stays_clean(self):
        wt, proj = self.init()
        self.assertTrue(str(wt).startswith(str(self.repo / ".treehouse")))  # under the repo, so a trusted folder covers it
        self.assertEqual(self.git("branch", "--show-current", cwd=wt), "fast-coding/p")
        self.assertEqual(self.status()[wt.resolve()], "leased")
        self.assertEqual(self.git("status", "--porcelain"), "")  # the pool is excluded, never shown or committed
        self.assertEqual(self.git("branch", "--show-current"), "main")

    def test_test_crew_slots_are_leased_then_returned_on_collect(self):
        wt, proj = self.init()
        (proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": [{"id": "001", "title": "A", "files": [], "protected": [], "test": "true", "body": ""}]}))
        slot = fc.test_worktree(proj, "001")
        self.assertEqual(self.git("branch", "--show-current", cwd=slot), "fast/p/tests-001")
        (slot / "t_test.txt").write_text("t\n")
        self.git("add", "-A", cwd=slot); self.git("commit", "-qm", "Test A", cwd=slot)
        fc.collect_tests(proj)
        self.assertTrue((wt / "t_test.txt").exists())
        self.assertEqual(self.status()[slot.resolve()], "available")  # back in the pool, installs and all
        self.assertEqual(fc.slots(proj), {})

    def test_stack_slot_is_reused_and_clean_hands_every_slot_back(self):
        wt, proj = self.init()
        first = fc.stack_worktree(wt, proj, "fast-coding/p")
        self.assertEqual(fc.stack_worktree(wt, proj, "fast-coding/p"), first)
        p = subprocess.run([CLI, "clean", "--project", "p", "--delete-unmerged", "--repo", str(self.repo)], capture_output=True, text=True, env=self.env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        st = self.status()
        self.assertEqual(st[first.resolve()], "available")
        self.assertEqual(st[wt.resolve()], "available")
        self.assertFalse((wt / ".fast-coding").exists())  # no stale project results for the next lease
        self.assertEqual(self.git("branch", "--list", "fast-coding/p"), "")

    def test_a_crew_in_another_repo_gets_a_slot_on_its_own_branch(self):
        wt, proj = self.init()
        other = self.repo.parent / "tool"
        other.mkdir()
        self.git("init", "-q", "-b", "main", cwd=other)
        (other / "x").write_text("x\n"); self.git("add", "-A", cwd=other); self.git("commit", "-qm", "x", cwd=other)
        with mock.patch.object(fc, "claude_trusted", return_value=True):
            slot, branch = fc.crew_workdir(other, wt, "p-toolsmith")
        self.assertTrue(str(slot).startswith(str(other / ".treehouse")))
        self.assertEqual(self.git("branch", "--show-current", cwd=slot), branch)
        self.assertEqual(self.git("branch", "--show-current", cwd=other), "main")  # the other repo's checkout never moves
        self.assertEqual(self.git("status", "--porcelain", cwd=other), "")


if __name__ == "__main__":
    unittest.main()
