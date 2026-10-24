import hermetic  # first: no test sees the real home
import argparse, importlib.machinery, importlib.util, json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock
import sys
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)

CLI = str(Path(__file__).resolve().parents[1] / "bin" / "compose")
GIT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


@unittest.skipUnless(shutil.which("treehouse"), "treehouse is not installed")
class Treehouse(unittest.TestCase):
    """Real treehouse, in-project pools inside temp repos, so the tests never touch ~/.treehouse."""
    def setUp(self):
        self.env = {**os.environ, **GIT, "HERDR_ENV": "", "COMPOSE_NO_TRAIL": "1", "COMPOSE_NO_TREEHOUSE": ""}
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
        self.assertEqual(self.git("branch", "--show-current", cwd=wt), "compose/p")
        self.assertEqual(self.status()[wt.resolve()], "leased")
        self.assertEqual(self.git("status", "--porcelain"), "")  # the pool is excluded, never shown or committed
        self.assertEqual(self.git("branch", "--show-current"), "main")

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
        fc.fc_crew.write_report(proj, "p-tests-001", "working", "test ready: x")
        fc.fc_briefs.collect_tests(proj)
        self.git("checkout", "-qb", "next"); self.git("commit", "-q", "--allow-empty", "-m", "main moved on"); self.git("checkout", "-q", "main")
        again = fc.fc_worktree.slot_on(self.repo, "next", "compose:p:tests-002")
        self.assertEqual(again.resolve(), slot.resolve())

    def test_a_slot_leased_again_keeps_its_own_installs_but_not_an_earlier_holders_borrowed_links(self):
        # `return` keeps ignored files and info/exclude ignores the links, so the next holder's install wrote through
        # a test writer's link into the project worktree's install
        self.cap(2)
        (self.repo / "client").mkdir(); (self.repo / "client" / "x.txt").write_text("x\n")
        self.git("add", "-A"); self.git("commit", "-qm", "client")
        wt, proj = self.init()
        (wt / "client" / "node_modules").mkdir()
        (proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": [{"id": "001", "title": "A", "files": [], "protected": [], "test": "true", "body": ""}]}))
        slot = fc.fc_briefs.test_worktree(proj, "001")
        self.assertTrue((slot / "client" / "node_modules").is_symlink())
        (slot / "node_modules").mkdir()  # an install of the slot's own
        fc.fc_crew.write_report(proj, "p-tests-001", "working", "test ready: x")
        fc.fc_briefs.collect_tests(proj)
        self.git("branch", "teammate")
        again = fc.fc_worktree.slot_on(self.repo, "teammate", "compose:p-toolsmith")
        self.assertEqual(again.resolve(), slot.resolve())
        self.assertFalse((again / "client" / "node_modules").is_symlink())
        self.assertTrue((wt / "client" / "node_modules").is_dir())
        self.assertTrue((again / "node_modules").is_dir())

    def test_init_in_a_slot_with_a_dangling_tool_link_leaves_no_half_made_project_and_runs_again(self):
        # an earlier holder's `.compose` link to a checkout that is gone made `mkdir` raise FileExistsError after the branch was
        # checked out in the slot; the re-run then found the branch held by a slot with no project
        self.cap(1)
        slot = fc.fc_worktree.slot_on(self.repo, "main", "compose:old:stackroot", detach=True)
        fc.fc_worktree.exclude_paths(self.repo, ["/.compose"])  # what stack_worktree adds, so `return` keeps the link
        (slot / ".compose").symlink_to(self.repo.parent / "gone" / ".compose")
        self.assertEqual(fc.fc_worktree.treehouse(self.repo, "return", "--force", str(slot), check=False).returncode, 0)
        self.assertTrue((slot / ".compose").is_symlink())
        wt, proj = self.init()
        self.assertEqual(wt.resolve(), slot.resolve())
        self.assertFalse((wt / ".compose").is_symlink())
        self.assertTrue((proj / "verify.json").exists())

    def test_a_failed_init_hands_its_slot_and_branch_back_so_the_next_run_starts_clean(self):
        self.cap(1)
        args = argparse.Namespace(repo=str(self.repo), project="p", branch=None, here=False, after=None)
        with mock.patch.object(fc.fc_init, "setup_trail", side_effect=OSError("boom")), self.assertRaises(OSError):
            fc.fc_init.cmd_init(args)
        self.assertEqual(self.git("branch", "--list", "compose/p"), "")
        self.assertEqual(set(self.status().values()), {"available"})
        self.init()

    def cap(self, n):
        (self.repo / "treehouse.toml").write_text(f"max_trees = {n}\n")
        self.git("add", "treehouse.toml"); self.git("commit", "-qm", "cap the pool")

    def test_testcrews_skips_finished_tasks_and_a_full_pool_stops_before_any_lease(self):
        self.cap(2)
        wt, proj = self.init()  # the project holds one of the two slots
        task = lambda tid, **kw: {"id": tid, "title": tid, "files": [], "protected": [f"{tid}_test.txt"], "test": "true", "body": "", **kw}
        (proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": [
            task("001"), task("002", linear_state="Canceled"), task("003"), task("004"), task("005", linear_state="Done")]}))
        (proj / "results" / "001.json").write_text(json.dumps({"id": "001", "status": "hand_done"}))
        (proj / "results" / "contract.md").write_text("c")
        started = []
        run = lambda: fc.fc_briefs.cmd_testcrews(mock.Mock(repo=str(self.repo), project="p", contract=None, only=None, print_=False, collect=False, budget=None, redo=False, parallel=None))
        with mock.patch.object(fc.fc_core, "project_dir", return_value=proj), mock.patch.object(fc.fc_herdr, "herdr_space"), \
             mock.patch.object(fc.fc_crew, "cmd_crew", lambda ns: started.append(ns.role)):
            with self.assertRaises(SystemExit) as e:
                run()  # 003 and 004 need two slots, one is free
            msg = str(e.exception.code)
            self.assertNotIn("\n", msg)
            for s in ("2 worktree", "1 free", "compose:p:project"):
                self.assertIn(s, msg)
            self.assertEqual(sorted(self.status().values()), ["leased"])  # nothing leased, nothing started
            self.assertEqual(started, [])
            (proj / "results" / "004.json").write_text(json.dumps({"id": "004", "status": "passed"}))
            run()
        self.assertEqual(started, ["tests-003"])
        self.assertEqual(list(fc.fc_worktree.slots(proj)), ["tests-003"])

    def test_collect_hands_the_collected_writers_slot_to_the_chained_next_writer_without_a_gap(self):
        self.cap(2)  # the project holds one slot, the first writer the other: the pool is full
        wt, proj = self.init()
        task = lambda tid: {"id": tid, "title": tid, "files": [], "protected": ["t_test.txt"], "test": "true", "body": ""}
        (proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": [task("001"), task("002")]}))
        (proj / "results" / "contract.md").write_text("c")
        slot = fc.fc_briefs.test_worktree(proj, "001")
        (slot / "t_test.txt").write_text("t\n")
        self.git("add", "-A", cwd=slot); self.git("commit", "-qm", "Test A", cwd=slot)
        fc.fc_crew.write_report(proj, "p-tests-001", "working", "test ready: x")
        fc.fc_briefs.waiting_writers(proj, {"002": {"contract": str(proj / "results" / "contract.md"), "budget": None, "redo": False}})
        real_release, started = fc.fc_worktree.release_slot, []
        def release_then_another_projects_writer_leases(repo, path):
            real_release(repo, path)
            fc.fc_worktree.slot_on(repo, "main", "compose:other:tests-001", detach=True)
        with mock.patch.object(fc.fc_core, "project_dir", return_value=proj), mock.patch.object(fc.fc_herdr, "herdr_space"), \
             mock.patch.object(fc.fc_crew, "cmd_crew", lambda ns: started.append((ns.role, ns.cwd))), \
             mock.patch.object(fc.fc_worktree, "release_slot", release_then_another_projects_writer_leases):
            fc.fc_briefs.collect_tests(proj)
        self.assertEqual([r for r, _ in started], ["tests-002"])
        self.assertEqual(Path(started[0][1]).resolve(), slot.resolve())
        self.assertEqual(self.git("branch", "--show-current", cwd=slot), "compose/p-tests-002")
        self.assertEqual(list(fc.fc_worktree.slots(proj)), ["tests-002"])
        self.assertEqual(self.status()[slot.resolve()], "leased")
        self.assertNotIn("compose/p-tests-001", self.git("branch", "--list", "compose/p-tests-001"))

    def test_collect_returns_a_kept_slot_when_the_waiting_writer_does_not_start(self):
        wt, proj = self.init()
        (proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": [{"id": "001", "title": "A", "files": [], "protected": [], "test": "true", "body": ""}]}))
        slot = fc.fc_briefs.test_worktree(proj, "001")
        fc.fc_crew.write_report(proj, "p-tests-001", "working", "test ready: x")
        fc.fc_briefs.waiting_writers(proj, {"002": {"contract": "c", "budget": None, "redo": False}})
        with mock.patch.object(fc.fc_briefs, "cmd_testcrews", side_effect=SystemExit("testcrews: no slot")):
            with self.assertRaises(SystemExit):
                fc.fc_briefs.collect_tests(proj)
        self.assertEqual(self.status()[slot.resolve()], "available")
        self.assertEqual(fc.fc_worktree.slots(proj), {})

    def ready_writer(self, proj):
        (proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": [{"id": "001", "title": "A", "files": [], "protected": [], "test": "true", "body": ""}]}))
        slot = fc.fc_briefs.test_worktree(proj, "001")
        (slot / "t_test.txt").write_text("t\n")
        self.git("add", "-A", cwd=slot); self.git("commit", "-qm", "Test A", cwd=slot)
        fc.fc_crew.write_report(proj, "p-tests-001", "working", "test ready: x")
        return slot

    def test_collect_deletes_the_branch_of_a_writer_whose_slot_the_project_no_longer_records(self):
        wt, proj = self.init()
        slot = self.ready_writer(proj)
        fc.fc_worktree.slots(proj, {"tests-001": None})
        fc.fc_briefs.collect_tests(proj)
        self.assertTrue((wt / "t_test.txt").exists())
        self.assertEqual(self.git("branch", "--list", "compose/p-tests-001"), "")
        self.assertFalse(fc.fc_briefs.test_open(proj, "001"))
        self.assertEqual(self.status()[slot.resolve()], "available")  # found through git, and returned
        self.assertEqual(fc.fc_worktree.slots(proj), {})

    def test_collect_frees_the_branch_of_a_writer_whose_slot_treehouse_cannot_return(self):
        # a live writer session respawns its children while `treehouse return` terminates them: the return fails, the slot stays leased
        wt, proj = self.init()
        slot = self.ready_writer(proj)
        real = fc.fc_worktree.treehouse
        def stuck(repo, *args, **kw):
            if args[:1] == ("return",):
                return subprocess.CompletedProcess(args, 1, "", "failed to return worktree: worktree still has live processes after termination: sleep (1)")
            return real(repo, *args, **kw)
        with mock.patch.object(fc.fc_worktree, "treehouse", stuck):
            fc.fc_briefs.collect_tests(proj)
        self.assertTrue((wt / "t_test.txt").exists())
        self.assertEqual(self.git("branch", "--list", "compose/p-tests-001"), "")
        self.assertFalse(fc.fc_briefs.test_open(proj, "001"))
        self.assertEqual(self.git("branch", "--show-current", cwd=slot), "")  # detached, so nothing holds the branch
        self.assertEqual(self.status()[slot.resolve()], "leased")
        self.assertEqual(fc.fc_worktree.slots(proj), {"spare-001": str(slot)})  # still on record, for the next writer or `compose clean`

    def test_a_lease_from_a_full_pool_exits_with_one_line_naming_the_holders(self):
        self.cap(1)
        wt, proj = self.init()
        with self.assertRaises(SystemExit) as e:
            fc.fc_worktree.slot_on(self.repo, "main", "compose:p:stackroot")
        msg = str(e.exception.code)
        self.assertNotIn("\n", msg)
        for s in ("1 worktree", "0 free", "compose:p:project"):
            self.assertIn(s, msg)

    def test_abandon_hands_the_unmerged_projects_slots_back_without_treehouse_return_force(self):
        wt, proj = self.init()
        stack = fc.fc_worktree.stack_worktree(wt, proj, "compose/p")
        (wt / "b.txt").write_text("b\n")
        self.git("add", "b.txt", cwd=wt); self.git("commit", "-qm", "Add b", cwd=wt)  # unmerged: a plain clean keeps it
        kept = subprocess.run([CLI, "clean", "--project", "p", "--repo", str(self.repo)], capture_output=True, text=True, env=self.env)
        self.assertEqual(self.status()[wt.resolve()], "leased", kept.stdout)
        p = subprocess.run([CLI, "clean", "--abandon", "--project", "p", "--repo", str(self.repo)], capture_output=True, text=True, env=self.env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("returned to the treehouse pool", p.stdout)
        st = self.status()
        self.assertEqual((st[wt.resolve()], st[stack.resolve()]), ("available", "available"))
        self.assertFalse((wt / ".compose").exists()); self.assertEqual(self.git("branch", "--list", "compose/p"), "")
        self.assertEqual(self.git("branch", "--show-current"), "main")

    def test_stack_slot_is_reused_and_clean_hands_every_slot_back(self):
        wt, proj = self.init()
        first = fc.fc_worktree.stack_worktree(wt, proj, "compose/p")
        self.assertEqual(fc.fc_worktree.stack_worktree(wt, proj, "compose/p"), first)
        head = self.git("rev-parse", "HEAD")
        for ref in ("refs/compose/p/C1/001", f"refs/compose/replaced/p/001/{head}", "refs/compose/pq/C1/001"):
            self.git("update-ref", ref, head)
        p = subprocess.run([CLI, "clean", "--project", "p", "--delete-unmerged", "--repo", str(self.repo)], capture_output=True, text=True, env=self.env)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        st = self.status()
        self.assertEqual(st[first.resolve()], "available")
        self.assertEqual(st[wt.resolve()], "available")
        self.assertFalse((wt / ".compose").exists())  # no stale project results for the next lease
        self.assertEqual(self.git("branch", "--list", "compose/p"), "")
        refs = self.git("for-each-ref", "--format=%(refname)", "refs/compose/").split()
        self.assertEqual(refs, ["refs/compose/pq/C1/001"])  # the project's change and replaced-tip refs go with it; another project's stay

    def test_clean_run_inside_the_slot_through_a_pipe_finishes_and_leaves_the_project_for_the_team_leads_done(self):
        wt, proj = self.init()
        (wt / "b.txt").write_text("b\n")
        self.git("add", "b.txt", cwd=wt); self.git("commit", "-qm", "Add b", cwd=wt)
        self.git("merge", "-q", "--ff-only", "compose/p")
        sitter = subprocess.Popen(["sleep", "60"], cwd=wt)  # the team lead's own processes in its slot (its MCP servers, its shell)
        self.addCleanup(sitter.kill)
        p = subprocess.run(["bash", "-c", '"$0" clean --repo "$PWD" --project p 2>&1 | tail -50; echo "exit ${PIPESTATUS[*]}"', CLI],
                           cwd=wt, capture_output=True, text=True, env=self.env)  # how the team lead ran it: returning the slot ended its tail
        self.assertIn("exit 0 0", p.stdout, p.stdout + p.stderr)
        self.assertIn("kept while this command runs inside it", p.stdout)
        self.assertIsNone(sitter.poll())
        self.assertEqual(self.status()[wt.resolve()], "leased")
        r = subprocess.run([CLI, "report", "--repo", str(self.repo), "--project", "p", "--as", "p-orchestrator", "done", "x"], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"compose clean --repo {self.repo} --project p", r.stdout)
        p = subprocess.run([CLI, "clean", "--repo", str(self.repo), "--project", "p"], cwd=self.repo, capture_output=True, text=True, env=self.env)
        self.assertIn("removed worktree", p.stdout, p.stdout + p.stderr)
        self.assertEqual(self.status()[wt.resolve()], "available")
        self.assertEqual(self.git("branch", "--list", "compose/p"), "")

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


class AllProjectsBranch(unittest.TestCase):
    """Real temp repo with linked worktrees: one git call reads every branch."""
    def setUp(self):
        p = mock.patch.dict(os.environ, GIT); p.start(); self.addCleanup(p.stop)
        self.base = Path(tempfile.mkdtemp()).resolve(); self.addCleanup(shutil.rmtree, self.base, True)
        self.repo = self.base / "app"; self.repo.mkdir()
        self.git(self.repo, "init", "-q", "-b", "main"); self.git(self.repo, "commit", "-q", "--allow-empty", "-m", "init")

    def git(self, cwd, *a):
        return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()

    def add(self, name, *flags):
        wt = self.base / name
        self.git(self.repo, "worktree", "add", "-q", *flags, str(wt))
        return wt

    def listed(self):
        return [Path(l[len("worktree "):]) for l in self.git(self.repo, "worktree", "list", "--porcelain").splitlines() if l.startswith("worktree ")]

    def project(self, wt, name="p"):
        (wt / ".compose" / name).mkdir(parents=True); (wt / ".compose" / name / "verify.json").write_text("{}")

    def test_branch_per_worktree_in_git_order(self):
        wt = self.add("wt", "-b", "compose/p"); det = self.add("det", "--detach")
        branch, listed = {self.repo: "main", wt: "compose/p", det: ""}, self.listed()
        self.assertEqual(fc.fc_core.worktree_branches(self.repo), [(d, branch[d]) for d in listed])
        self.assertEqual(fc.fc_core.worktrees(self.repo), listed)

    def test_git_order_holds_whatever_the_directory_times_and_a_gone_directory_is_listed(self):
        a = self.add("a", "-b", "compose/a"); b = self.add("b", "-b", "compose/b"); c = self.add("c", "--detach")
        for i, d in enumerate((a, b, c)): os.utime(d, (1_000_000 - i * 1000, 1_000_000 - i * 1000))  # the first listed is the newest
        listed = self.listed()
        self.assertEqual(sorted(listed), sorted([self.repo, a, b, c]))
        self.assertEqual(fc.fc_core.worktrees(self.repo), listed)
        shutil.rmtree(b)  # git still lists it until pruned
        self.assertEqual(fc.fc_core.worktrees(self.repo), listed)
        self.assertEqual(dict(fc.fc_core.worktree_branches(self.repo))[b], "compose/b")

    def test_no_git_gives_the_folder_with_no_branch(self):
        self.assertEqual(fc.fc_core.worktree_branches(self.base), [(self.base, "")])

    def test_own_worktree_wins_with_one_git_process(self):
        wt = self.add("wt", "-b", "compose/p")
        self.project(self.repo); self.project(wt)  # merged: the main checkout shows the folder too
        real, calls = subprocess.run, []
        def spy(cmd, *a, **k): calls.append(cmd); return real(cmd, *a, **k)
        with mock.patch("subprocess.run", side_effect=spy):
            found = fc.fc_core.all_projects(self.repo)
        self.assertEqual(found["p"], (wt, wt / ".compose" / "p"))
        self.assertEqual(len([c for c in calls if c[0] == "git"]), 1)

    def test_detached_worktree_never_wins(self):
        det = self.add("det", "--detach"); self.project(self.repo); self.project(det)
        self.assertEqual(fc.fc_core.all_projects(self.repo)["p"][0], self.repo)


if __name__ == "__main__":
    unittest.main()
