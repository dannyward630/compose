import importlib.machinery, importlib.util, json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock
import sys

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast_coding.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
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
        return fc.fc_core.all_projects(self.repo)["p"]

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
        slot = fc.fc_briefs.test_worktree(proj, "001")
        self.assertEqual(self.git("branch", "--show-current", cwd=slot), "fast/p/tests-001")
        (slot / "t_test.txt").write_text("t\n")
        self.git("add", "-A", cwd=slot); self.git("commit", "-qm", "Test A", cwd=slot)
        fc.fc_briefs.collect_tests(proj)
        self.assertTrue((wt / "t_test.txt").exists())
        self.assertEqual(self.status()[slot.resolve()], "available")  # back in the pool, installs and all
        self.assertEqual(fc.fc_worktree.slots(proj), {})

    def test_a_collected_test_slot_can_be_leased_again(self):
        # `return` resets a slot to its lease's base, and treehouse reuses a slot only when its commit is an ancestor of the next
        # base; a slot leased on its test branch came back on a test commit, "in use or dirty" for every lease after it
        (self.repo / "treehouse.toml").write_text("max_trees = 2\n")
        self.git("add", "treehouse.toml"); self.git("commit", "-qm", "cap the pool")
        wt, proj = self.init()
        (proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": [{"id": "001", "title": "A", "files": [], "protected": [], "test": "true", "body": ""}]}))
        slot = fc.fc_briefs.test_worktree(proj, "001")
        (slot / "t_test.txt").write_text("t\n")
        self.git("add", "-A", cwd=slot); self.git("commit", "-qm", "Test A", cwd=slot)
        fc.fc_briefs.collect_tests(proj)
        self.git("checkout", "-qb", "next"); self.git("commit", "-q", "--allow-empty", "-m", "main moved on"); self.git("checkout", "-q", "main")
        again = fc.fc_worktree.slot_on(self.repo, "next", "fast-coding:p:tests-002")
        self.assertEqual(again.resolve(), slot.resolve())

    def cap(self, n):
        (self.repo / "treehouse.toml").write_text(f"max_trees = {n}\n")
        self.git("add", "treehouse.toml"); self.git("commit", "-qm", "cap the pool")

    def test_testcrews_skips_finished_tasks_and_a_full_pool_stops_before_any_lease(self):
        self.cap(2)
        wt, proj = self.init()  # the project holds one of the two slots
        task = lambda tid, **kw: {"id": tid, "title": tid, "files": [], "protected": [], "test": "true", "body": "", **kw}
        (proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": [
            task("001"), task("002", linear_state="Canceled"), task("003"), task("004"), task("005", linear_state="Done")]}))
        (proj / "results" / "001.json").write_text(json.dumps({"id": "001", "status": "hand_done"}))
        (proj / "results" / "contract.md").write_text("c")
        started = []
        run = lambda: fc.fc_briefs.cmd_testcrews(mock.Mock(repo=str(self.repo), project="p", contract=None, only=None, print_=False, collect=False, budget=None))
        with mock.patch.object(fc.fc_core, "project_dir", return_value=proj), mock.patch.object(fc.fc_herdr, "herdr_space"), \
             mock.patch.object(fc.fc_crew, "cmd_crew", lambda ns: started.append(ns.role)):
            with self.assertRaises(SystemExit) as e:
                run()  # 003 and 004 need two slots, one is free
            msg = str(e.exception.code)
            self.assertNotIn("\n", msg)
            for s in ("2 worktree", "1 free", "fast-coding:p:project"):
                self.assertIn(s, msg)
            self.assertEqual(sorted(self.status().values()), ["leased"])  # nothing leased, nothing started
            self.assertEqual(started, [])
            (proj / "results" / "004.json").write_text(json.dumps({"id": "004", "status": "passed"}))
            run()
        self.assertEqual(started, ["tests-003"])
        self.assertEqual(list(fc.fc_worktree.slots(proj)), ["tests-003"])

    def test_a_lease_from_a_full_pool_exits_with_one_line_naming_the_holders(self):
        self.cap(1)
        wt, proj = self.init()
        with self.assertRaises(SystemExit) as e:
            fc.fc_worktree.slot_on(self.repo, "main", "fast-coding:p:stackroot")
        msg = str(e.exception.code)
        self.assertNotIn("\n", msg)
        for s in ("1 worktree", "0 free", "fast-coding:p:project"):
            self.assertIn(s, msg)

    def test_stack_slot_is_reused_and_clean_hands_every_slot_back(self):
        wt, proj = self.init()
        first = fc.fc_worktree.stack_worktree(wt, proj, "fast-coding/p")
        self.assertEqual(fc.fc_worktree.stack_worktree(wt, proj, "fast-coding/p"), first)
        head = self.git("rev-parse", "HEAD")
        for ref in ("refs/fast-coding/p/C1/001", f"refs/fast-coding/replaced/p/001/{head}", "refs/fast-coding/pq/C1/001"):
            self.git("update-ref", ref, head)
        p = subprocess.run([CLI, "clean", "--project", "p", "--delete-unmerged", "--repo", str(self.repo)], capture_output=True, text=True, env=self.env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        st = self.status()
        self.assertEqual(st[first.resolve()], "available")
        self.assertEqual(st[wt.resolve()], "available")
        self.assertFalse((wt / ".fast-coding").exists())  # no stale project results for the next lease
        self.assertEqual(self.git("branch", "--list", "fast-coding/p"), "")
        refs = self.git("for-each-ref", "--format=%(refname)", "refs/fast-coding/").split()
        self.assertEqual(refs, ["refs/fast-coding/pq/C1/001"])  # the project's change and replaced-tip refs go with it; another project's stay

    def test_a_crew_in_another_repo_gets_a_slot_on_its_own_branch(self):
        wt, proj = self.init()
        other = self.repo.parent / "tool"
        other.mkdir()
        self.git("init", "-q", "-b", "main", cwd=other)
        (other / "x").write_text("x\n"); self.git("add", "-A", cwd=other); self.git("commit", "-qm", "x", cwd=other)
        with mock.patch.object(fc.fc_claude, "claude_trusted", return_value=True):
            slot, branch = fc.fc_crew.crew_workdir(other, wt, "p-toolsmith")
        self.assertTrue(str(slot).startswith(str(other / ".treehouse")))
        self.assertEqual(self.git("branch", "--show-current", cwd=slot), branch)
        self.assertEqual(self.git("branch", "--show-current", cwd=other), "main")  # the other repo's checkout never moves
        self.assertEqual(self.git("status", "--porcelain", cwd=other), "")


if __name__ == "__main__":
    unittest.main()
