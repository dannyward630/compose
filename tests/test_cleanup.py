import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, io, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"  # these cover the plain-worktree path; test_treehouse covers the pool
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)

CLI = str(Path(__file__).resolve().parents[1] / "bin" / "compose")
ENV = {"COMPOSE_NO_TRAIL": "1", "HERDR_ENV": "", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def repo():
    r = Path(tempfile.mkdtemp()).resolve() / "repo"
    r.mkdir()
    run = lambda *a, cwd=r: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True)
    run("init", "-q", "-b", "main")
    (r / "a.txt").write_text("base\n")
    (r / ".git" / "info" / "exclude").write_text("/.compose/\n")
    run("add", "-A"); run("commit", "-qm", "init")
    return r, run


def own_file_commit(run, cwd, base, name, msg):
    """A commit on `base` that adds one file of its own, so merging it into base changes base's tree."""
    blob = run("hash-object", "-w", "/dev/null", cwd=cwd).stdout.strip()
    entries = run("ls-tree", f"{base}^{{tree}}", cwd=cwd).stdout + f"100644 blob {blob}\t{name}\n"
    tree = subprocess.run(["git", "mktree"], cwd=cwd, input=entries, check=True, capture_output=True, text=True).stdout.strip()
    return run("commit-tree", tree, "-p", base, "-m", msg, cwd=cwd).stdout.strip()


class TestCrewWorktrees(unittest.TestCase):
    """Test-writing teammates write on their own branches; collect brings their commits back in task order."""
    def setUp(self):
        self.env = mock.patch.dict(os.environ, ENV); self.env.start(); self.addCleanup(self.env.stop)
        self.repo, self.run = repo()
        self.proj = self.repo / ".compose" / "p"
        (self.proj / "results").mkdir(parents=True)
        tasks = [{"id": "001", "title": "A", "files": ["a.go"], "protected": ["a_test.go"], "test": "true", "body": "a"},
                 {"id": "002", "title": "B", "files": ["b.go"], "protected": ["b_test.go"], "test": "true", "body": "b", "test_lines": "25"}]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))
        for p in (mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch.object(fc.fc_herdr, "project_worktree", return_value=self.repo)):
            p.start(); self.addCleanup(p.stop)

    def crew_commits(self, tid, name, text, state="working"):
        wt = fc.fc_briefs.test_worktree(self.proj, tid)
        (wt / name).write_text(text)
        self.run("add", name, cwd=wt); self.run("commit", "-qm", f"Test {name}", cwd=wt)
        if state:
            fc.fc_crew.write_report(self.proj, f"p-tests-{tid}", state, "test ready: x")
        return wt

    def writer_branches(self):
        return self.run("branch", "--list", "--format=%(refname:short)", "*tests-*").stdout.split()

    def test_testcrews_puts_writers_on_the_project_branch_name(self):
        (self.proj / "verify.json").write_text(json.dumps({"branch": "team/p"}))
        self.run("branch", "fast/pq/001")  # another project's legacy branch leaves this one on new names
        self.start_writers([])
        self.assertEqual(self.writer_branches(), ["team/p-tests-001", "team/p-tests-002"])

    def test_a_project_with_legacy_branches_keeps_its_writers_on_them(self):
        self.run("branch", "fast/p/001")
        self.crew_commits("001", "a_test.go", "a\n")
        self.assertEqual(self.writer_branches(), ["fast/p/tests-001"])
        fc.fc_briefs.collect_tests(self.proj)
        self.assertTrue((self.repo / "a_test.go").exists())
        self.assertEqual(self.writer_branches(), [])

    def test_a_recorded_task_prefix_names_the_writer_branch(self):
        (self.proj / "verify.json").write_text(json.dumps({"branch": "compose/p", "task_prefix": "team/p-"}))
        self.assertEqual(fc.fc_briefs.test_branch(self.proj, "007"), "team/p-tests-007")

    def add_task(self, tid, protected, after="", test="true"):
        f = self.proj / "results" / "tasks.json"
        task = {"id": tid, "title": tid, "files": [], "protected": protected.split(), "test": test, "body": tid, "after": after}
        f.write_text(json.dumps({"feature": {}, "tasks": json.loads(f.read_text())["tasks"] + [task]}))

    def start_writers(self, started):
        (self.proj / "results" / "contract.md").write_text("c")
        out = io.StringIO()
        with mock.patch.object(fc.fc_herdr, "herdr_space"), mock.patch.object(fc.fc_crew, "cmd_crew", lambda ns: started.append(ns.role)), \
             mock.patch("sys.stdout", out):
            fc.fc_briefs.cmd_testcrews(SimpleNamespace(repo=str(self.repo), project="p", contract=None, only=None, print_=False, collect=False, budget=None))
        return out.getvalue()

    def test_writers_of_one_test_file_start_one_after_another(self):
        self.add_task("003", "a_test.go", after="001")
        started = []
        out = self.start_writers(started)
        self.assertEqual(sorted(started), ["tests-001", "tests-002"])  # 003 shares a_test.go with 001: both creating it conflicted
        self.assertIn("tests-003 waits for tests-001", out)
        self.crew_commits("001", "a_test.go", "a\n", state="done")
        self.crew_commits("002", "b_test.go", "b\n", state="done")
        with mock.patch.object(fc.fc_herdr, "herdr_space"), mock.patch.object(fc.fc_crew, "cmd_crew", lambda ns: started.append(ns.role)), \
             mock.patch.object(fc.fc_run, "run_tasks") as rt, self.assertRaises(SystemExit) as e:
            fc.fc_run.cmd_run(SimpleNamespace(repo=str(self.repo), project="p", only=None, redo=False))
        self.assertIn("tests-003", str(e.exception)); rt.assert_not_called()  # its test is still to be written
        self.assertEqual(started[-1], "tests-003")  # started by the collect, off the branch that now holds 001's test
        wt = self.crew_commits("003", "a_test.go", "a\nc\n")
        self.assertEqual(self.run("log", "--format=%s", "-3", cwd=wt).stdout.split("\n")[:3], ["Test a_test.go", "Test b_test.go", "Test a_test.go"])
        fc.fc_briefs.collect_tests(self.proj)
        self.assertEqual((self.repo / "a_test.go").read_text(), "a\nc\n")
        self.assertEqual(self.writer_branches(), [])

    def test_a_redone_writer_that_waits_for_another_writer_is_started_by_the_collect(self):
        """A re-plan changed passed tasks 001 and 003, which share a_test.go: --redo starts 001's writer, and the collect starts 003's."""
        self.add_task("003", "a_test.go")
        for tid in ("001", "003"):
            (self.proj / "results" / f"{tid}.json").write_text('{"status": "passed"}')
        (self.proj / "results" / "contract.md").write_text("c")
        started, out = [], io.StringIO()
        crews = (mock.patch.object(fc.fc_herdr, "herdr_space"), mock.patch.object(fc.fc_crew, "cmd_crew", lambda ns: started.append(ns.role)))
        with crews[0], crews[1], mock.patch("sys.stdout", out):
            fc.fc_briefs.cmd_testcrews(SimpleNamespace(repo=str(self.repo), project="p", contract=None, only="001,003", print_=False, collect=False,
                                                       budget=None, redo=True))
        self.assertEqual(started, ["tests-001"])
        self.assertIn("tests-003 waits for tests-001", out.getvalue())
        self.crew_commits("001", "a_test.go", "a\n", state="done")
        with crews[0], crews[1], mock.patch("sys.stdout", io.StringIO()):
            fc.fc_briefs.collect_tests(self.proj)
        self.assertEqual(started, ["tests-001", "tests-003"])

    def test_writers_of_a_protected_file_that_already_exists_start_together(self):
        (self.repo / "a_test.go").write_text("pinned\n"); self.run("add", "a_test.go"); self.run("commit", "-qm", "stubs")  # groundwork wrote it, no writer edits it
        self.add_task("003", "c_test.go a_test.go", after="001", test="go test ./c_test.go")  # its test runs c_test.go: a_test.go only pins names
        started = []
        out = self.start_writers(started)
        self.assertEqual(sorted(started), ["tests-001", "tests-002", "tests-003"])
        self.assertNotIn("waits for", out)

    def test_writers_whose_tests_run_one_existing_file_start_one_after_another(self):
        self.main_commits("a_test.go", "package a\n", "stubs")  # each writer appends its test to it: started together, the second collect conflicted
        self.add_task("003", "a_test.go", test="go test ./a_test.go -run C")
        started = []
        out = self.start_writers(started)
        self.assertEqual(sorted(started), ["tests-001", "tests-002"])
        self.assertIn("tests-003 waits for tests-001", out)

    def test_collect_skips_a_writer_that_has_not_reported_test_ready(self):
        fc.fc_crew.write_report(self.proj, "p-tests-001", "working", "started")
        wt = fc.fc_briefs.test_worktree(self.proj, "001")  # started, nothing committed yet
        self.crew_commits("002", "b_test.go", "b\n", state=None)
        fc.fc_crew.write_report(self.proj, "p-tests-002", "done", "d")
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            fc.fc_briefs.collect_tests(self.proj)
        self.assertIn("tests-001 skipped", out.getvalue())
        self.assertTrue(wt.exists())  # its worktree and branch stay for the writer still in it
        self.assertEqual(self.writer_branches(), ["compose/p-tests-001"])
        self.assertTrue((self.repo / "b_test.go").exists())

    def test_a_collected_writer_counts_as_done_so_its_ended_session_is_no_stall(self):
        self.crew_commits("001", "a_test.go", "a\n")  # test ready, still working: collect ends its session
        self.crew_commits("002", "b_test.go", "b\n", state="done")
        for n in ("p-tests-001", "p-tests-002"):
            (self.proj / "results" / "crew" / f"{n}.json").write_text(json.dumps({"name": n, "space": "w9"}))
        with mock.patch("sys.stdout", io.StringIO()):
            fc.fc_briefs.collect_tests(self.proj)
        self.assertEqual([r["state"] for r in fc.fc_crew.crew_reports(self.proj, "p-tests-001")], ["working", "done"])
        self.assertEqual(len(fc.fc_crew.crew_reports(self.proj, "p-tests-002")), 1)  # already done: nothing added
        with mock.patch.object(fc.fc_herdr, "herdr", return_value={"agents": []}):
            snap = fc.fc_watch.watch_snapshot(self.repo, self.proj)
        self.assertEqual(snap["closed"], ["p-tests-001", "p-tests-002"])
        self.assertEqual([e for e in fc.fc_watch.watch_stalls(self.proj, snap, 240) if "stall=ended" in e], [])

    def test_each_crew_has_its_own_branch_and_collect_lands_them_in_order(self):
        self.crew_commits("002", "b_test.go", "b\n")
        self.crew_commits("001", "a_test.go", "a\n")
        self.assertEqual(self.run("branch", "--show-current").stdout.strip(), "main")  # the project checkout never moved
        fc.fc_briefs.collect_tests(self.proj)
        log = self.run("log", "--format=%s", "-3").stdout.split("\n")
        self.assertEqual(log[:2], ["Test b_test.go", "Test a_test.go"])  # 001 first, then 002
        self.assertTrue((self.repo / "a_test.go").exists() and (self.repo / "b_test.go").exists())
        self.assertEqual(self.writer_branches(), [])
        self.assertFalse((self.proj / "worktrees" / "tests-001").exists())

    def test_run_collects_finished_test_crews_and_waits_for_busy_ones(self):
        from types import SimpleNamespace
        self.crew_commits("001", "a_test.go", "a\n")
        self.crew_commits("002", "b_test.go", "b\n")
        a = SimpleNamespace(repo=str(self.repo), project="p", only=None, redo=False)
        with mock.patch.object(fc.fc_run, "run_tasks") as rt, mock.patch.object(fc.fc_crew, "crew_reports", return_value=[{"state": "working"}]):
            with self.assertRaises(SystemExit) as e:
                fc.fc_run.cmd_run(a)
            self.assertIn("tests-001", str(e.exception)); rt.assert_not_called()
        with mock.patch.object(fc.fc_run, "run_tasks") as rt, mock.patch.object(fc.fc_crew, "crew_reports", return_value=[{"state": "done"}]):
            fc.fc_run.cmd_run(a)
            rt.assert_called_once()
        self.assertTrue((self.repo / "a_test.go").exists())  # collected before the run

    def test_run_refuses_a_task_whose_protected_test_is_not_on_the_project_branch(self):
        self.main_commits("a_test.go", "a\n", "Test a")
        with mock.patch.object(fc.fc_run, "run_tasks") as rt, self.assertRaises(SystemExit) as e:
            fc.fc_run.cmd_run(SimpleNamespace(repo=str(self.repo), project="p", only=None, redo=False))
        rt.assert_not_called()
        self.assertIn("002 b_test.go", str(e.exception))
        self.assertNotIn("a_test.go", str(e.exception))
        with mock.patch.object(fc.fc_run, "run_tasks") as rt:
            fc.fc_run.cmd_run(SimpleNamespace(repo=str(self.repo), project="p", only="001", redo=False))
        rt.assert_called_once()

    def test_a_conflict_names_the_task_and_keeps_its_branch(self):
        self.crew_commits("001", "a.txt", "teammate\n")
        self.crew_commits("002", "b_test.go", "b\n")
        (self.repo / "a.txt").write_text("main\n"); self.run("commit", "-qam", "main moved")
        with self.assertRaises(SystemExit) as e:
            fc.fc_briefs.collect_tests(self.proj)
        self.assertIn("tests-001", str(e.exception))
        self.assertEqual(self.writer_branches(), ["compose/p-tests-001"])
        self.assertTrue((self.repo / "b_test.go").exists())  # the writers after it are still collected, their worktrees freed
        self.assertEqual(self.run("status", "--porcelain").stdout.strip(), "")  # the cherry-pick was aborted cleanly

    def main_commits(self, name, text, msg):
        (self.repo / name).write_text(text); self.run("add", name); self.run("commit", "-qm", msg)

    def test_commits_already_picked_by_hand_or_by_patch_are_skipped_and_the_next_task_lands(self):
        f = self.proj / "results" / "tasks.json"
        f.write_text(json.dumps({"feature": {}, "tasks": json.loads(f.read_text())["tasks"] + [{"id": "003", "title": "C", "files": [], "protected": ["c_test.go"], "test": "true", "body": "c"}]}))
        self.main_commits("t.py", "import a, b\n\ndef one():\n    pass\n", "base")
        self.crew_commits("001", "t.py", "import a, b, c\n\ndef one():\n    pass\n\ndef two():\n    pass\n")
        self.crew_commits("002", "b_test.go", "b\n")
        self.main_commits("t.py", "import a, b, d\n\ndef one():\n    pass\n\ndef three():\n    pass\n", "another task's test")
        with self.assertRaises(subprocess.CalledProcessError):
            self.run("cherry-pick", "compose/p-tests-001")  # the team lead picks it by hand and resolves the conflict
        (self.repo / "t.py").write_text("import a, b, c, d\n\ndef one():\n    pass\n\ndef three():\n    pass\n\ndef two():\n    pass\n")
        self.run("add", "t.py"); self.run("-c", "core.editor=true", "cherry-pick", "--continue")
        trimmed = "import a, b, c, d\n\ndef one():\n    pass\n\ndef three():\n    pass\n"
        self.main_commits("t.py", trimmed, "Drop test two")  # then edits it on the branch: a replay would bring it back
        self.run("cherry-pick", "compose/p-tests-002")  # a clean hand pick: same patch
        self.crew_commits("003", "c_test.go", "c\n")
        fc.fc_briefs.collect_tests(self.proj)
        self.assertEqual((self.repo / "t.py").read_text(), trimmed)
        self.assertEqual(self.run("log", "--format=%s", "-2").stdout.split("\n")[:2], ["Test c_test.go", "Test b_test.go"])
        self.assertEqual(self.run("status", "--porcelain").stdout.strip(), "")
        self.assertEqual(self.writer_branches(), [])

    def test_brief_states_the_line_budget(self):
        tasks = fc.fc_tasks.load_tasks(self.proj)
        self.assertIn("at most 60 lines", fc.fc_briefs.test_brief(tasks[0], "c"))
        self.assertIn("at most 25 lines", fc.fc_briefs.test_brief(tasks[1], "c"))  # the task's test_lines wins
        self.assertIn("at most 40 lines", fc.fc_briefs.test_brief(tasks[0], "c", 40))


def server(cwd):
    p = subprocess.Popen([sys.executable, "-m", "http.server", "0", "--bind", "127.0.0.1"], cwd=cwd,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        if str(p.pid) in subprocess.run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-t"], capture_output=True, text=True).stdout.split():
            return p
        time.sleep(0.1)
    raise AssertionError("server never listened")


class Leftovers(unittest.TestCase):
    """Servers a teammate or run leaves in the project end with teardown; anything else is left alone."""
    def test_teardown_stops_servers_in_the_project_only(self):
        proj_wt = Path(tempfile.mkdtemp()).resolve()
        proj = proj_wt / ".compose" / "p"
        scratch = fc.fc_crew.scratch_dir(proj, "p-groundwork"); scratch.mkdir(parents=True)
        mine, other = server(scratch), server(tempfile.mkdtemp())
        self.addCleanup(lambda: [(p.kill(), p.wait()) for p in (mine, other)])
        with mock.patch.object(fc.fc_herdr, "project_worktree", return_value=proj_wt), mock.patch.dict(os.environ, {"HERDR_ENV": ""}), \
                mock.patch("sys.stdout", io.StringIO()):
            fc.fc_crew.teardown(proj)
        self.assertIsNotNone(mine.wait(timeout=5))
        self.assertIsNone(other.poll())
        self.assertTrue(fc.fc_crew.scratch_dir(proj).exists())

    def test_preamble_points_scratch_inside_the_project(self):
        proj = Path(tempfile.mkdtemp()) / ".compose" / "shop"
        with mock.patch.object(fc.fc_herdr, "project_worktree", return_value=proj.parent.parent):
            pre = fc.fc_crew.crew_preamble(proj, "shop-groundwork", "groundwork")
        self.assertIn(str(proj / "scratch" / "shop-groundwork"), pre)
        self.assertIn("never /tmp", pre)

    def test_a_stage_ends_only_its_own_new_daemons(self):
        def spawn(name):
            p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "browser_harness.daemon"], env={**os.environ, "BU_NAME": name})
            self.addCleanup(lambda: (p.kill(), p.wait()))
            return p
        mine_name, other_name = f"fc-test-{os.getpid()}-a", f"fc-test-{os.getpid()}-b"  # unique: suites may run at once
        shared = spawn(mine_name)  # running before the stage under its name (shared through e2e_env): kept
        time.sleep(0.2)
        before = fc.fc_jev.harness_daemons(mine_name)
        mine, other = spawn(mine_name), spawn(other_name)  # another project's stage starts one meanwhile: kept
        time.sleep(0.2)
        self.assertEqual(fc.fc_jev.end_new_daemons(mine_name, before), {str(mine.pid)})
        self.assertIsNotNone(mine.wait(timeout=5))
        self.assertIsNone(shared.poll())
        self.assertIsNone(other.poll())


class StartOver(unittest.TestCase):
    def test_delete_unmerged_removes_the_project_folder_with_its_ignored_files(self):
        r, run = repo()
        env = {**os.environ, **ENV}
        subprocess.run([CLI, "init", "--project", "p", "--repo", str(r)], check=True, capture_output=True, env=env)
        wt = r.parent / "compose-p"
        (wt / ".compose" / "p" / "results" / "x.json").parent.mkdir(parents=True, exist_ok=True)
        (wt / ".compose" / "p" / "results" / "x.json").write_text("{}")
        (wt / "feature.txt").write_text("f\n")
        subprocess.run(["git", "add", "feature.txt"], cwd=wt, check=True, env=env)
        subprocess.run(["git", "commit", "-qm", "feature"], cwd=wt, check=True, env=env)
        subprocess.run([CLI, "clean", "--project", "p", "--delete-unmerged", "--repo", str(r)], check=True, capture_output=True, env=env)
        self.assertFalse(wt.exists())
        self.assertEqual(run("branch", "--list", "compose/p").stdout.strip(), "")


class CleanSafety(unittest.TestCase):
    """A repo-wide clean only removes projects whose work is provably done, and never one with live crew."""
    def setUp(self):
        self.r, self.run = repo()
        self.env = {**os.environ, **ENV}
        for n in ("empty", "work"):
            subprocess.run([CLI, "init", "--project", n, "--repo", str(self.r)], check=True, capture_output=True, env=self.env)
        self.wt = {n: self.r.parent / f"compose-{n}" for n in ("empty", "work")}
        (self.wt["work"] / "f.txt").write_text("f\n")
        subprocess.run(["git", "add", "-A"], cwd=self.wt["work"], check=True, env=self.env)
        subprocess.run(["git", "commit", "-qm", "work"], cwd=self.wt["work"], check=True, env=self.env)
        self.run("merge", "-q", "--ff-only", "compose/work")

    def clean(self, *args):
        return subprocess.run([CLI, "clean", "--repo", str(self.r), *args], capture_output=True, text=True, env=self.env)

    def crew(self, n, state):
        d = self.wt[n] / ".compose" / n / "results" / "crew"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{n}-b1.json").write_text(json.dumps({"name": f"{n}-b1", "title": "b1"}))
        (d / f"{n}-b1.status").write_text(json.dumps({"state": state, "message": "m"}) + "\n")

    def test_repo_wide_clean_removes_the_merged_project_and_keeps_the_empty_one(self):
        out = self.clean().stdout
        self.assertFalse(self.wt["work"].exists())
        self.assertTrue(self.wt["empty"].exists())
        self.assertIn("no commits of its own", out)

    def test_naming_the_empty_project_removes_it(self):
        self.clean("--project", "empty")
        self.assertFalse(self.wt["empty"].exists())

    def test_live_crew_keeps_a_merged_project_until_forced_by_name(self):
        self.crew("work", "working")
        self.assertIn("live crew", self.clean().stdout)
        self.assertTrue(self.wt["work"].exists())
        self.clean("--force")  # --force alone never overrides a repo-wide clean
        self.assertTrue(self.wt["work"].exists())
        self.clean("--project", "work", "--force")
        self.assertFalse(self.wt["work"].exists())

    def test_a_done_teammate_is_not_live_crew(self):
        self.crew("work", "done")
        self.clean()
        self.assertFalse(self.wt["work"].exists())


class SharedSpaceClean(unittest.TestCase):
    """In the space compose was started from, clean closes the project's tabs, never the space, and other agents there are not its crew."""
    def herdr(self, *args, check=False, timeout=120):
        self.calls.append(args)
        if args[:2] == ("workspace", "list"):
            return {"workspaces": getattr(self, "spaces", [{"workspace_id": "w7", "label": "shop"}])}
        if args[:2] == ("tab", "list"):
            tabs = getattr(self, "tabs", (("t1", "1"), ("t2", "shop shell"), ("t3", "shop status"), ("t4", "cart status")))
            return {"tabs": [{"tab_id": t, "label": l} for t, l in tabs]}
        if args[:2] == ("agent", "list"):
            return {"agents": [{"name": "manager", "tab_id": "t1", "workspace_id": "w7"}, {"name": "cart-orchestrator", "tab_id": "t4", "workspace_id": "w7"}]}
        return {}

    def test_a_teammate_whose_tab_closed_while_working_is_not_live_crew(self):
        wt = Path(tempfile.mkdtemp()); proj = wt / ".compose" / "shop"
        crew = proj / "results" / "crew"; crew.mkdir(parents=True)
        fc.fc_herdr.space_record(proj).write_text(json.dumps({"space": "w7"}))
        for n in ("shop-tests-002", "manager"):  # herdr lists no shop-tests-002: its session ended after it reported
            (crew / f"{n}.json").write_text(json.dumps({"name": n, "agent": n, "title": n, "space": "w7", "tab": "t9"}))
            (crew / f"{n}.status").write_text(json.dumps({"state": "working", "message": "test ready"}) + "\n")
        self.calls = []
        with mock.patch.object(fc.fc_herdr, "herdr", self.herdr), mock.patch.object(fc.fc_herdr, "herdr_env", return_value=True):
            self.assertEqual(fc.fc_init.live_crew(proj), ["manager last reported working"])

    def test_clean_closes_the_projects_tabs_and_counts_only_its_agents(self):
        wt = Path(tempfile.mkdtemp()); proj = wt / ".compose" / "shop"
        (proj / "results").mkdir(parents=True)
        fc.fc_herdr.space_record(proj).write_text(json.dumps({"space": "w7"}))
        self.calls = []
        with mock.patch.object(fc.fc_herdr, "herdr", self.herdr), mock.patch.object(fc.fc_herdr, "herdr_env", return_value=True):
            self.assertEqual(fc.fc_init.live_crew(proj), [])
            fc.fc_init.close_space(proj, "shop")
        self.assertEqual([c for c in self.calls if c[0] in ("tab", "workspace") and c[1] == "close"], [("tab", "close", "t2"), ("tab", "close", "t3")])

    def clean(self, proj, crew):
        """crew maps a teammate to (its tab, its reports oldest first); returns the close calls and the `clean left` lines."""
        d = fc.fc_crew.crew_dir(proj)
        for n, (tab, states) in crew.items():
            (d / f"{n}.json").write_text(json.dumps({"name": n, "title": "t", "space": "w7", "tab": tab}))
            for st in states: fc.fc_crew.write_report(proj, n, st, "m")
        self.calls, out = [], io.StringIO()
        with mock.patch.object(fc.fc_herdr, "herdr", self.herdr), mock.patch.object(fc.fc_herdr, "herdr_env", return_value=True), mock.patch("sys.stdout", out):
            fc.fc_init.close_space(proj, "shop")
        return [c for c in self.calls if c[0] in ("tab", "workspace") and c[1] == "close"], sorted(l for l in out.getvalue().splitlines() if "left" in l)

    def test_clean_keeps_the_tabs_of_teammates_whose_last_report_is_not_done(self):
        proj = Path(tempfile.mkdtemp()) / ".compose" / "shop"
        (proj / "results").mkdir(parents=True)
        fc.fc_herdr.space_record(proj).write_text(json.dumps({"space": "w7"}))
        lead = fc.fc_herdr.agent_name("shop", "orchestrator")
        self.tabs = (("t1", "1"), ("t2", "shop shell"), ("t3", "shop status"), ("t4", "cart status"), ("t5", "shop tests-001"),
                     ("t6", "shop tests-002"), ("t7", "shop tests-003"), ("t8", "shop orchestrator"), ("t9", "shop tests-004"))
        closes, lines = self.clean(proj, {"shop-tests-001": ("t5", ["needs-user"]), "shop-tests-002": ("t6", ["done", "working"]),
                                          "shop-tests-003": ("t7", ["working", "done"]), lead: ("t8", ["blocked"]),
                                          "shop-tests-004": ("t9", []), "shop-tests-005": ("t99", ["working"])})
        self.assertEqual(closes, [("tab", "close", "t2"), ("tab", "close", "t3"), ("tab", "close", "t7")])
        self.assertEqual(lines, sorted([f"clean left {lead} open (last report: blocked)", "clean left shop-tests-001 open (last report: needs-user)",
                                        "clean left shop-tests-002 open (last report: working)", "clean left shop-tests-004 open (last report: nothing)"]))

    def test_a_space_of_its_own_stays_open_while_a_tab_is_kept(self):
        wt = Path(tempfile.mkdtemp()).resolve(); proj = wt / ".compose" / "shop"
        (proj / "results").mkdir(parents=True)
        self.spaces = [{"workspace_id": "w8", "label": "shop", "worktree": {"checkout_path": str(wt)}}]
        self.tabs = (("t1", "shell"), ("t2", "status"), ("t3", "tests-001"))
        closes, lines = self.clean(proj, {"shop-tests-001": ("t3", ["done"])})
        self.assertEqual((closes, lines), ([("workspace", "close", "w8")], []))
        closes, lines = self.clean(proj, {"shop-tests-001": ("t3", ["done", "working"])})
        self.assertEqual(closes, [("tab", "close", "t1"), ("tab", "close", "t2")])
        self.assertEqual(lines, ["clean left shop-tests-001 open (last report: working)"])


class ProjectBranch(unittest.TestCase):
    """A project's branch is stored in its verify.json: init --branch names it, --after and clean follow it, init --branch again renames it."""
    def setUp(self):
        self.r, self.run = repo()
        self.env = {**os.environ, **ENV}

    def cli(self, *a):
        return subprocess.run([CLI, *a, "--repo", str(self.r)], check=True, capture_output=True, text=True, env=self.env)

    def branches(self):
        return self.run("branch", "--format=%(refname:short)").stdout.split()

    def test_custom_branch_is_created_stored_renamed_built_on_and_cleaned(self):
        self.cli("init", "--project", "p", "--branch", "js-1-p")
        wt = self.r.parent / "compose-p"
        self.assertIn("js-1-p", self.branches())
        self.assertNotIn("compose/p", self.branches())
        self.assertEqual(json.loads((wt / ".compose" / "p" / "verify.json").read_text())["branch"], "js-1-p")
        self.cli("init", "--project", "q", "--after", "p")  # resolves p's stored branch, not compose/p
        qcfg = json.loads((self.r.parent / "compose-q" / ".compose" / "q" / "verify.json").read_text())
        self.assertEqual((qcfg["review_base"], qcfg["after"]), ("js-1-p", "p"))
        self.cli("init", "--project", "p", "--branch", "js-2-p")  # an existing project moves to the new name
        self.assertEqual(self.run("branch", "--show-current", cwd=wt).stdout.strip(), "js-2-p")
        self.assertNotIn("js-1-p", self.branches())
        self.assertEqual(json.loads((self.r.parent / "compose-q" / ".compose" / "q" / "verify.json").read_text())["review_base"], "js-2-p")
        self.cli("clean", "--project", "q", "--delete-unmerged")
        self.cli("clean", "--project", "p", "--delete-unmerged")
        self.assertEqual(self.branches(), ["main"])

    def test_init_names_the_cut_team_lead_a_long_project_name_gets(self):
        """herdr names stop at 32 characters: a project name over 19 cuts `<slug>-orchestrator`, so init says the name herdr will hold."""
        out = self.cli("init", "--project", "clean-recut-branches").stdout
        self.assertIn("clean-recut-branche-orchestrator", out)
        self.assertNotIn("orchestrator", self.cli("init", "--project", "clean-recut-branche").stdout)  # 19 characters: uncut, nothing to say

    def test_a_project_without_a_stored_branch_keeps_compose_slash_slug(self):
        self.cli("init", "--project", "old")
        f = self.r.parent / "compose-old" / ".compose" / "old" / "verify.json"
        f.write_text(json.dumps({k: v for k, v in json.loads(f.read_text()).items() if k != "branch"}))
        self.assertEqual(fc.fc_core.project_branch(f.parent), "compose/old")
        self.assertIn("compose/old", self.branches())

    def config(self, cfg):
        f = Path(self.env["COMPOSE_CONFIG"]); f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(cfg))

    def test_init_names_and_stores_the_project_branch_from_branch_prefix(self):
        ws = {"branch_prefix": "top/", "workspace": "w", "workspaces": {"w": {"branch_prefix": "ws/"}}}
        for cfg, args, want in (({}, (), "compose/p"), ({"branch_prefix": ""}, (), "p"), ({"branch_prefix": "team/"}, (), "team/p"),
                                (ws, (), "ws/p"), (ws, ("--branch", "js-1-p"), "js-1-p")):
            with self.subTest(cfg=cfg, args=args):
                self.r, self.run = repo()
                self.config(cfg)
                self.cli("init", "--project", "p", *args)
                wt = self.r.parent / "compose-p"
                self.assertEqual(self.run("branch", "--show-current", cwd=wt).stdout.strip(), want)
                self.assertEqual(json.loads((wt / ".compose" / "p" / "verify.json").read_text())["branch"], want)

    def test_after_a_project_with_no_record_builds_on_its_prefixed_branch(self):
        self.config({"branch_prefix": "team/"})
        self.run("branch", "team/x")
        self.cli("init", "--project", "q", "--after", "x")
        self.assertEqual(json.loads((self.r.parent / "compose-q" / ".compose" / "q" / "verify.json").read_text())["review_base"], "team/x")

    def test_clean_removes_only_its_own_merged_branches_then_drops_the_task_prefix(self):
        self.cli("init", "--project", "p")
        wt = self.r.parent / "compose-p"; f = wt / ".compose" / "p" / "verify.json"
        git = lambda *a: self.run("-c", "user.name=t", "-c", "user.email=t@t", *a, cwd=wt).stdout.strip()
        (wt / "f.txt").write_text("f\n"); git("add", "f.txt"); git("commit", "-qm", "f")  # unmerged project: its worktree stays
        for b in ("compose/p-001", "compose/p-tests-001", "compose/p-002-bench-x", "compose/p-layer-01", "compose/p-2", "compose/p-2-001", "compose/p-2-tests-001"):
            git("branch", b, "compose/p")
        git("branch", "compose/p-003", own_file_commit(self.run, wt, "main", "p003.txt", "unmerged"))
        f.write_text(json.dumps({**json.loads(f.read_text()), "task_prefix": "compose/p-"}))
        self.cli("clean", "--project", "p")
        self.assertEqual(sorted(b for b in self.branches() if b.startswith("compose/p-")), ["compose/p-003", "compose/p-2", "compose/p-2-001", "compose/p-2-tests-001"])
        self.assertEqual(json.loads(f.read_text())["task_prefix"], "compose/p-")
        git("branch", "-D", "compose/p-003")
        self.cli("clean", "--project", "p")
        self.assertNotIn("task_prefix", json.loads(f.read_text()))

    def test_clean_still_removes_a_legacy_projects_merged_task_branches(self):
        self.cli("init", "--project", "p")
        for b in ("fast/p/001", "fast/p/tests-001"):
            self.run("branch", b, "compose/p")
        self.cli("clean", "--project", "p")
        self.assertEqual([b for b in self.branches() if b.startswith("fast/")], [])


class FakeLinear:
    """Linear in memory: issues by identifier, each with a state and a parent. A state's id is its name."""
    TYPES = {"Todo": "unstarted", "In Progress": "started", "In Review": "started", "Done": "completed", "Canceled": "canceled"}

    def __init__(self, **issues):
        self.issues = {k.replace("_", "-"): {"state": s, "parent": p} for k, (s, p) in issues.items()}

    def __call__(self, query, variables):
        if "issueUpdate" in query:
            self.issues[variables["id"]]["state"] = variables["s"]
            return {"issueUpdate": {"success": True}}
        ident, d = variables["id"], self.issues[variables["id"]]
        st = lambda n: {"name": n, "type": self.TYPES[n]}
        return {"issue": {"id": ident, "identifier": ident, "state": st(d["state"]),
                          "team": {"states": {"nodes": [{"id": n, "name": n, "type": t} for n, t in self.TYPES.items()]}},
                          "parent": {"identifier": d["parent"]} if d["parent"] else None,
                          "children": {"nodes": [{"identifier": c, "state": st(cd["state"])} for c, cd in self.issues.items() if cd["parent"] == ident]}}}

    def states(self, *idents):
        return [self.issues[i]["state"] for i in idents]


class LocallyMergedLayers(unittest.TestCase):
    """main fast-forwarded to a layer built locally: the layer holds copies of the task commits, and no layers.json says whose."""
    def test_clean_counts_tasks_whose_patches_are_in_main_merged_and_moves_linear(self):
        r, run = repo()
        subprocess.run([CLI, "init", "--project", "p", "--repo", str(r)], check=True, capture_output=True, env={**os.environ, **ENV})
        wt = r.parent / "compose-p"; proj = wt / ".compose" / "p"
        def commit(f, cwd=wt):
            (cwd / f).parent.mkdir(exist_ok=True); (cwd / f).write_text(f"{f}\n")
            run("add", f, cwd=cwd); run("commit", "-qm", f, cwd=cwd)
            return run("rev-parse", "HEAD", cwd=cwd).stdout.strip()
        tests = [commit("tests/t001.txt"), commit("tests/t002.txt")]
        run("checkout", "-q", "-b", "fast/p/001", cwd=wt); one = commit("src001.txt")
        run("checkout", "-q", "-b", "fast/p/002", cwd=wt); two = commit("src002.txt")
        run("checkout", "-q", "compose/p", cwd=wt)
        run("checkout", "-q", "-b", "fast/p/layer-01")  # each task's test sits next to it, so every pick is a new commit
        for c in (tests[0], one, tests[1], two):
            run("cherry-pick", c)
        run("checkout", "-q", "main"); run("merge", "-q", "--ff-only", "fast/p/layer-01")
        tasks = [{"id": t, "title": t, "files": [], "protected": [], "linear": l, "after": ""} for t, l in (("001", "ENG-3"), ("002", "ENG-4"))]
        (proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))
        (proj / "linear.json").write_text('{"feature": "ENG-1"}')
        linear = FakeLinear(ENG_1=("In Review", None), ENG_2=("In Review", "ENG-1"), ENG_3=("In Review", "ENG-2"), ENG_4=("In Review", "ENG-2"))
        with mock.patch.dict(os.environ, ENV), mock.patch("sys.stdout", io.StringIO()), \
                mock.patch.object(fc.fc_linear, "linear_gql", linear), mock.patch.object(fc.fc_config, "LINEAR_KEY", "k"):
            fc.fc_init.clean_project(r, "p", wt, proj, explicit=True)
        self.assertEqual(run("branch", "--format=%(refname:short)").stdout.split(), ["main"])
        self.assertFalse(wt.exists())
        self.assertEqual(linear.states("ENG-3", "ENG-4", "ENG-2", "ENG-1"), ["Done", "Done", "Done", "Done"])


class SquashMergedLayers(unittest.TestCase):
    """Layers are squash-merged by PR: task branches were never PRs and ancestry is rewritten, so the merged layer that held a task proves it."""
    def setUp(self):
        self.r, self.run = repo()
        self.bin = Path(tempfile.mkdtemp()).resolve()
        (self.bin / "gh").write_text('''#!/usr/bin/env python3
import json, sys
a = sys.argv[1:]
merged = open(__file__ + ".merged").read().split()
head = a[a.index("--head") + 1] if "--head" in a else ""
print(json.dumps([{"number": 7, "mergedAt": "2026-10-15T00:00:00Z"}] if head in merged else []))
''')
        (self.bin / "gh").chmod(0o755)
        (self.bin / "gh.merged").write_text("fast/p/layer-01\n")
        self.env = {**os.environ, **ENV, "PATH": f"{self.bin}:{os.environ['PATH']}"}
        remote = self.r.parent / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        self.run("remote", "add", "origin", str(remote)); self.run("push", "-q", "origin", "main")
        subprocess.run([CLI, "init", "--project", "p", "--repo", str(self.r)], check=True, capture_output=True, env=self.env)
        self.proj = self.r.parent / "compose-p" / ".compose" / "p"
        tip = self.run("rev-parse", "main").stdout.strip()
        for b in ("fast/p/001", "fast/p/002", "fast/p/layer-01", "fast/p/layer-02"):  # commits on top of main: never ancestors of it
            self.run("branch", b, own_file_commit(self.run, self.r, tip, b.replace("/", "-") + ".txt", b))
        self.run("push", "-q", "origin", "fast/p/layer-01", "fast/p/layer-02")
        (self.proj / "layers.json").write_text(json.dumps({"fast/p/layer-01": ["001"], "fast/p/layer-02": ["002"]}))

    def test_clean_drops_tasks_of_a_squash_merged_layer_and_its_remote_branch_and_keeps_the_rest(self):
        out = subprocess.run([CLI, "clean", "--project", "p", "--repo", str(self.r)], capture_output=True, text=True, env=self.env).stdout
        left = self.run("branch", "--format=%(refname:short)").stdout.split()
        self.assertNotIn("fast/p/001", left); self.assertNotIn("fast/p/layer-01", left)
        self.assertIn("fast/p/002", left); self.assertIn("fast/p/layer-02", left)
        remote = self.run("ls-remote", "--heads", "origin").stdout
        self.assertNotIn("fast/p/layer-01", remote); self.assertIn("fast/p/layer-02", remote)
        self.assertIn("deleted origin/fast/p/layer-01", out)
        self.assertIn("kept unmerged: fast/p/002, fast/p/layer-02", out)
        (self.bin / "gh.merged").write_text("fast/p/layer-01\nfast/p/layer-02\n")  # the last layer merges: everything goes
        subprocess.run([CLI, "clean", "--project", "p", "--repo", str(self.r)], capture_output=True, text=True, env=self.env)
        self.assertEqual(self.run("branch", "--format=%(refname:short)").stdout.split(), ["main"])
        self.assertFalse((self.r.parent / "compose-p").exists())
        self.assertEqual(self.run("ls-remote", "--heads", "origin").stdout.count("fast/p/"), 0)

    def test_clean_removes_the_project_branch_once_every_layer_built_from_it_is_merged(self):
        wt = self.r.parent / "compose-p"
        (wt / "stub.txt").write_text("groundwork\n")  # the project branch's own commit: layers squash it, so ancestry never sees it
        self.run("add", "stub.txt", cwd=wt); self.run("commit", "-qm", "groundwork", cwd=wt)
        clean = lambda *a: subprocess.run([CLI, "clean", "--project", "p", "--repo", str(self.r), *a], capture_output=True, text=True, env=self.env).stdout
        out = clean()  # layer-02 is not merged: everything of the project stays
        self.assertIn("kept unmerged", out)
        self.assertTrue(wt.exists())
        (self.bin / "gh.merged").write_text("fast/p/layer-01\nfast/p/layer-02\n")
        out = clean()
        self.assertIn("every layer built from it is merged", out)
        self.assertFalse(wt.exists())
        self.assertNotIn("compose/p", self.run("branch", "--format=%(refname:short)").stdout.split())

    def linear_project(self):
        """Tasks 001 and 002 with issues under story ENG-2 of feature ENG-1, and 003, canceled and re-split, whose branch sits on main."""
        tasks = [{"id": t, "title": t, "files": [], "protected": [], "linear": l, "after": ""} for t, l in (("001", "ENG-3"), ("002", "ENG-4"), ("003", "ENG-5"))]
        (self.proj / "results").mkdir(exist_ok=True)
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))
        (self.proj / "linear.json").write_text('{"feature": "ENG-1"}')
        self.run("branch", "fast/p/003", "main")

    def clean_here(self):
        out = io.StringIO()
        with mock.patch.dict(os.environ, self.env), mock.patch("sys.stdout", out):
            fc.fc_init.clean_project(self.r, "p", self.r.parent / "compose-p", self.proj, explicit=True)
        return out.getvalue()

    def test_clean_moves_the_tasks_it_proves_merged_to_done_and_rolls_the_story_and_the_feature_up(self):
        self.linear_project()
        linear = FakeLinear(ENG_1=("In Review", None), ENG_2=("In Review", "ENG-1"), ENG_3=("In Review", "ENG-2"), ENG_4=("In Review", "ENG-2"), ENG_5=("Canceled", "ENG-2"))
        with mock.patch.object(fc.fc_linear, "linear_gql", linear), mock.patch.object(fc.fc_config, "LINEAR_KEY", "k"):
            out = self.clean_here()  # layer-01 merged: 001 is Done, 003 stays Canceled, the story waits for 002, the feature for the project branch
            self.assertEqual(linear.states("ENG-3", "ENG-4", "ENG-5", "ENG-2", "ENG-1"), ["Done", "In Review", "Canceled", "In Review", "In Review"])
            self.assertIn("linear ENG-3 -> Done", out)
            (self.bin / "gh.merged").write_text("fast/p/layer-01\nfast/p/layer-02\n")
            self.clean_here()  # every layer and the project branch merged: the story and the feature are Done too
            self.assertEqual(linear.states("ENG-3", "ENG-4", "ENG-5", "ENG-2", "ENG-1"), ["Done", "Done", "Canceled", "Done", "Done"])
        self.assertFalse((self.r.parent / "compose-p").exists())

    def test_clean_without_a_linear_key_says_so_in_one_line_and_calls_nothing(self):
        self.linear_project()
        with mock.patch.object(fc.fc_linear, "linear_gql", side_effect=AssertionError("Linear called without a key")), \
                mock.patch.object(fc.fc_config, "LINEAR_KEY", ""), mock.patch.object(fc.fc_linear, "_linear_warned", []):
            out = self.clean_here()
        self.assertEqual(out.count("linear skipped"), 1, out)
        self.assertIn("fast/p/001", out)  # the branches are still cleaned

    def test_with_task_branches_gone_merged_layers_move_their_tasks_story_and_feature_to_done(self):
        self.linear_project()
        wt = self.r.parent / "compose-p"
        (wt / "stub.txt").write_text("groundwork\n")  # the project branch's own commit: only its layers prove it merged
        self.run("add", "stub.txt", cwd=wt); self.run("commit", "-qm", "groundwork", cwd=wt)
        self.run("branch", "-D", "fast/p/001", "fast/p/002")
        (self.bin / "gh.merged").write_text("fast/p/layer-01\nfast/p/layer-02\n")
        linear = FakeLinear(ENG_1=("In Review", None), ENG_2=("In Review", "ENG-1"), ENG_3=("In Review", "ENG-2"), ENG_4=("In Progress", "ENG-2"), ENG_5=("Canceled", "ENG-2"))
        with mock.patch.object(fc.fc_linear, "linear_gql", linear), mock.patch.object(fc.fc_config, "LINEAR_KEY", "k"):
            out = self.clean_here()
        self.assertIn("every layer built from it is merged", out)
        self.assertEqual(linear.states("ENG-3", "ENG-4", "ENG-5", "ENG-2", "ENG-1"), ["Done", "Done", "Canceled", "Done", "Done"])

    def merged_ids(self):
        with mock.patch.object(fc.fc_linear, "linear_merged") as lm:
            self.clean_here()
        _, metas, project_merged = lm.call_args.args
        return [m["id"] for m in metas], project_merged

    def test_a_task_held_by_any_layer_not_merged_is_not_counted(self):
        self.linear_project()
        self.run("branch", "-D", "fast/p/001", "fast/p/002")
        (self.proj / "layers.json").write_text(json.dumps({"fast/p/layer-01": ["001", "002"], "fast/p/layer-02": ["002"]}))
        ids, project_merged = self.merged_ids()  # only layer-01 is merged: 002 waits for layer-02
        self.assertEqual(sorted(ids), ["001", "003"])
        self.assertFalse(project_merged)

    def test_a_task_proven_merged_by_its_branch_and_its_layer_is_counted_once(self):
        self.linear_project()
        ids, _ = self.merged_ids()
        self.assertEqual(sorted(ids), ["001", "003"])


class CleanLinearLine(unittest.TestCase):
    """Once the project is linked to a feature, clean always says what it did about Linear."""
    NOTHING = "linear  nothing proven merged; states unchanged"

    def lines(self, feature, metas, project_merged, key="k", linear=None):
        gql = linear or mock.Mock(side_effect=AssertionError("Linear called"))
        out = io.StringIO()
        with mock.patch.object(fc.fc_config, "LINEAR_KEY", key), mock.patch.object(fc.fc_linear, "_linear_warned", []), \
             mock.patch.object(fc.fc_linear, "linear_gql", gql), mock.patch("sys.stdout", out):
            fc.fc_linear.linear_merged(feature, metas, project_merged)
        return [line.split("] ", 1)[1] for line in out.getvalue().splitlines()]

    def test_with_a_key_and_nothing_merged_one_line_says_states_are_unchanged(self):
        self.assertEqual(self.lines("ENG-1", [], False), [self.NOTHING])

    def test_without_a_key_and_nothing_merged_one_line_says_linear_is_skipped(self):
        out = self.lines("ENG-1", [], False, key="")
        self.assertEqual(len(out), 1)
        self.assertIn("linear skipped", out[0])

    def test_no_feature_and_nothing_merged_says_nothing(self):
        for key in ("k", ""):
            for project_merged in (False, True):
                self.assertEqual(self.lines(None, [], project_merged, key=key), [])

    def test_merged_tasks_move_to_done_as_before(self):
        linear = FakeLinear(ENG_1=("In Review", None), ENG_2=("In Review", "ENG-1"), ENG_3=("In Review", "ENG-2"), ENG_4=("Done", "ENG-2"))
        out = self.lines("ENG-1", [{"id": "001", "linear": "ENG-3"}], False, linear=linear)
        self.assertEqual(out, ["linear ENG-3 -> Done", "linear ENG-2 -> Done"])
        self.assertEqual(linear.states("ENG-3", "ENG-2", "ENG-1"), ["Done", "Done", "In Review"])

    def test_merged_tasks_without_a_key_are_skipped_once_without_calling_linear(self):
        out = self.lines("ENG-1", [{"id": "001", "linear": "ENG-3"}], True, key="")
        self.assertEqual(len(out), 1)
        self.assertIn("linear skipped", out[0])

    def test_a_merged_project_with_no_merged_task_still_rolls_the_feature_up(self):
        linear = FakeLinear(ENG_1=("In Review", None), ENG_2=("Done", "ENG-1"))
        self.assertEqual(self.lines("ENG-1", [], True, linear=linear), ["linear ENG-1 -> Done"])


class CleanUnderTheTeamLead(unittest.TestCase):
    """clean finishes every Linear roll-up before the merged project's worktree goes, and never takes it from under the team lead
    or from under itself: the team lead's last report still finds the project, and its done finishes the removal."""
    def setUp(self):
        self.r, self.run = repo()
        self.env = {**os.environ, **ENV}
        subprocess.run([CLI, "init", "--project", "p", "--repo", str(self.r)], check=True, capture_output=True, env=self.env)
        self.wt = self.r.parent / "compose-p"; self.proj = self.wt / ".compose" / "p"
        self.run("checkout", "-q", "-b", "compose/p-001", cwd=self.wt)
        (self.wt / "f.txt").write_text("f\n"); self.run("add", "f.txt", cwd=self.wt); self.run("commit", "-qm", "Add f", cwd=self.wt)
        self.run("checkout", "-q", "compose/p", cwd=self.wt); self.run("merge", "-q", "--ff-only", "compose/p-001", cwd=self.wt)
        self.run("merge", "-q", "--ff-only", "compose/p")
        task = {"id": "001", "title": "f", "files": [], "protected": [], "linear": "ENG-3", "after": ""}
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": [task]}))
        (self.proj / "linear.json").write_text('{"feature": "ENG-1"}')

    def lead(self, state):
        d = fc.fc_crew.crew_dir(self.proj)
        (d / "p-orchestrator.json").write_text(json.dumps({"name": "p-orchestrator", "title": "lead", "space": "w1", "tab": "t1", "pane": "p1"}))
        fc.fc_crew.write_report(self.proj, "p-orchestrator", state, "m")

    def cli(self, *args, cwd=None):
        return subprocess.run([CLI, *args], cwd=cwd or self.r, capture_output=True, text=True, env=self.env)

    def test_every_roll_up_is_done_while_the_worktree_is_still_there(self):
        linear, seen = FakeLinear(ENG_1=("In Review", None), ENG_2=("In Review", "ENG-1"), ENG_3=("In Review", "ENG-2")), []
        def gql(query, variables):
            if "issueUpdate" in query:
                seen.append((variables["id"], self.wt.exists()))
            return linear(query, variables)
        with mock.patch.dict(os.environ, ENV), mock.patch("sys.stdout", io.StringIO()), \
                mock.patch.object(fc.fc_linear, "linear_gql", gql), mock.patch.object(fc.fc_config, "LINEAR_KEY", "k"):
            fc.fc_init.clean_project(self.r, "p", self.wt, self.proj, explicit=True)
        self.assertEqual(seen, [("ENG-3", True), ("ENG-2", True), ("ENG-1", True)])
        self.assertFalse(self.wt.exists())

    def clean_with_a_second_story(self, linear, task016=None):
        """Task 016 (ENG-5) in story ENG-4 next to 001's story ENG-2, with no branch of its own, then a clean."""
        tasks = json.loads((self.proj / "results" / "tasks.json").read_text())
        tasks["tasks"].append({"id": "016", "title": "g", "files": [], "protected": [], "linear": "ENG-5", "after": ""})
        (self.proj / "results" / "tasks.json").write_text(json.dumps(tasks))
        if task016:
            self.assertEqual(self.cli(*task016).returncode, 0)
        with mock.patch.dict(os.environ, ENV), mock.patch("sys.stdout", io.StringIO()), \
                mock.patch.object(fc.fc_linear, "linear_gql", linear), mock.patch.object(fc.fc_config, "LINEAR_KEY", "k"):
            fc.fc_init.clean_project(self.r, "p", self.wt, self.proj, explicit=True)
        self.assertFalse(self.wt.exists())

    def test_a_merged_project_moves_its_task_done_by_hand_without_a_branch_and_rolls_up(self):
        linear = FakeLinear(ENG_1=("In Review", None), ENG_2=("In Review", "ENG-1"), ENG_3=("In Review", "ENG-2"),
                            ENG_4=("In Review", "ENG-1"), ENG_5=("In Review", "ENG-4"))
        self.clean_with_a_second_story(linear, ("done", "--project", "p", "--only", "016", "--note", "already green in 001's layer"))
        self.assertEqual(linear.states("ENG-3", "ENG-5", "ENG-2", "ENG-4", "ENG-1"), ["Done"] * 5)

    def test_a_merged_project_rolls_up_the_story_of_a_task_moved_to_done_outside_it(self):
        linear = FakeLinear(ENG_1=("In Review", None), ENG_2=("In Review", "ENG-1"), ENG_3=("In Review", "ENG-2"),
                            ENG_4=("In Review", "ENG-1"), ENG_5=("Done", "ENG-4"))
        self.clean_with_a_second_story(linear)
        self.assertEqual(linear.states("ENG-3", "ENG-5", "ENG-2", "ENG-4", "ENG-1"), ["Done"] * 5)

    def test_run_inside_the_worktree_it_rolls_linear_up_and_keeps_the_worktree(self):
        linear = FakeLinear(ENG_1=("In Review", None), ENG_2=("In Review", "ENG-1"), ENG_3=("In Review", "ENG-2"))
        out, here = io.StringIO(), os.getcwd()
        self.addCleanup(os.chdir, here)
        os.chdir(self.wt)
        with mock.patch.dict(os.environ, ENV), mock.patch("sys.stdout", out), \
                mock.patch.object(fc.fc_linear, "linear_gql", linear), mock.patch.object(fc.fc_config, "LINEAR_KEY", "k"):
            fc.fc_init.clean_project(self.r, "p", self.wt, self.proj, explicit=True)
        os.chdir(here)
        self.assertEqual(linear.states("ENG-3", "ENG-2", "ENG-1"), ["Done", "Done", "Done"])
        self.assertIn(f"kept while this command runs inside it: run `compose clean --repo {self.r} --project p` from outside it", out.getvalue())
        self.assertTrue((self.proj / "results" / "clean.json").exists())
        self.assertEqual(self.run("branch", "--list", "compose/p", "compose/p-001").stdout.split(), ["+", "compose/p"])

    def test_a_working_team_lead_keeps_the_worktree_until_its_done_and_force_by_name_overrides(self):
        self.lead("working")
        out = self.cli("clean").stdout
        self.assertIn("kept while p-orchestrator last reported working: they go when p-orchestrator reports done", out)
        self.assertTrue(self.proj.exists())
        r = self.cli("report", "--project", "p", "--as", "p-orchestrator", "done", "shipped")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("reported p-orchestrator done", r.stdout)
        self.assertIn(f"run `compose clean --repo {self.r} --project p` from outside {self.wt}", r.stdout)
        self.assertIn("removed worktree", self.cli("clean", "--project", "p").stdout)
        self.assertFalse(self.wt.exists())

    def test_force_by_name_removes_it_under_a_working_team_lead(self):
        self.lead("working")
        self.cli("clean", "--force")  # --force alone never overrides a repo-wide clean
        self.assertTrue(self.wt.exists())
        self.cli("clean", "--project", "p", "--force")
        self.assertFalse(self.wt.exists())

    def test_inside_herdr_the_team_leads_done_finishes_clean_from_outside_once_its_turn_ends(self):
        self.lead("working")
        (self.proj / "results" / "clean.json").write_text("{}")
        out, started, real = io.StringIO(), [], subprocess.Popen
        def popen(argv, **kw):  # git still runs; the detached finisher is only recorded
            return started.append((argv, kw)) if argv[0] == "sh" else real(argv, **kw)
        with mock.patch.object(fc.fc_herdr, "herdr_env", return_value=True), mock.patch.object(fc.fc_crew.subprocess, "Popen", popen), \
                mock.patch("sys.stdout", out):
            fc.fc_crew.finish_clean_after_turn(self.proj, "p-orchestrator")
        [(argv, kw)] = started
        self.assertEqual(argv[:3], ["sh", "-c", '"$0" agent wait "$1" --timeout 900000; "$2" clean --repo "$3" --project "$4"'])
        self.assertEqual(argv[4:], ["p-orchestrator", str(Path(CLI).resolve()), str(self.r), "p"])
        self.assertEqual((kw["cwd"], kw["start_new_session"]), (self.r, True))
        self.assertIn(f"clean  p: {self.wt.resolve()} and its branch go once this turn ends", out.getvalue())


class MergeChangesNothing(unittest.TestCase):
    """A branch whose merge into a target leaves the target's tree as it is counts as merged, whatever its patches say."""
    def test_a_merge_that_changes_nothing_proves_a_branch_merged_after_the_earlier_proofs(self):
        r, run = repo()
        def branch(name, text, extra=None):
            run("checkout", "-q", "-b", name, "main"); (r / "a.txt").write_text(text)
            if extra: (r / "b.txt").write_text(extra)
            run("add", "-A"); run("commit", "-qm", name)
        branch("b", "base\nx\n"); branch("same", "base\nx\n", "y\n"); branch("conf", "base\nz\n")  # same: b's change in another patch
        run("checkout", "-q", "-b", "pick", "main"); run("cherry-pick", "-x", "b")  # -x: a new commit, never b itself
        why = lambda b, *t: fc.fc_init.merge_evidence(r, b, list(t), False)
        self.assertEqual(why("b", "nope", "conf", "same"), "merging it into same changes nothing")
        self.assertEqual(why("main", "same"), "contained in same")
        self.assertEqual(why("b", "pick", "same"), "contained in pick by patch")
        self.assertEqual(why("b", "same", "pick"), "merging it into same changes nothing")  # targets in order
        self.assertIsNone(why("b", "main", "conf"))  # a real change, then a conflict

    GH = """#!/usr/bin/env python3
import json, subprocess, sys; from pathlib import Path
git = lambda *a: subprocess.run(["git", *a], capture_output=True, text=True).stdout.strip()
a = sys.argv[1:]
if a[:2] == ["stack", "--version"]: sys.exit(print("gh stack (fake)"))
f = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "fake-gh-stack.json"; s = json.loads(f.read_text()) if f.exists() else None
if a[:2] == ["stack", "init"]: f.write_text(json.dumps({"trunk": a[a.index("--base") + 1], "branches": [{"name": b} for b in a[4:]]}))
elif a[:2] == ["stack", "view"] and s and git("branch", "--show-current") in [b["name"] for b in s["branches"]]: print(json.dumps(s))
elif a[:2] == ["stack", "unstack"]: f.unlink(missing_ok=True)
else: sys.exit(1)
"""

    def test_clean_removes_a_stack_recut_on_a_moved_main_once_it_lands_and_moves_linear(self):
        r, run = repo()
        bin_ = Path(tempfile.mkdtemp()).resolve(); (bin_ / "gh").write_text(self.GH); (bin_ / "gh").chmod(0o755)
        env = {**os.environ, **ENV, "PATH": f"{bin_}:{os.environ['PATH']}"}
        pins = 'M = {\n    "core": ("now",),\n    "keys": ("key_status", "linear_connected", "save_key"),\n    "steps": ("FLOORS",),\n    "worktree": ("task_prefix", "task_branch"),\n}\n'
        (r / "pins.py").write_text(pins); run("add", "-A"); run("commit", "-qm", "pins")
        subprocess.run([CLI, "init", "--project", "p", "--repo", str(r)], check=True, capture_output=True, env=env)
        wt = r.parent / "compose-p"; proj = wt / ".compose" / "p"
        def commit(f, text, msg, cwd=wt):
            (cwd / f).parent.mkdir(parents=True, exist_ok=True); (cwd / f).write_text(text)
            run("add", "-A", cwd=cwd); run("commit", "-qm", msg, cwd=cwd)
        commit("pins.py", pins.replace('"linear_connected", ', ""), "groundwork")
        commit("tests/t001.txt", "t\n", "test 001"); commit("tests/t002.txt", "t\n", "test 002")
        tasks = [{"id": t, "title": t, "files": [f"src{t}.txt"], "protected": [f"tests/t{t}.txt"], "linear": l, "after": "", "test": "true"} for t, l in (("001", "ENG-3"), ("002", "ENG-4"))]
        (proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks})); (proj / "linear.json").write_text('{"feature": "ENG-1"}')
        for t in ("001", "002"):
            run("checkout", "-q", "-b", f"compose/p-{t}", "compose/p", cwd=wt); commit(f"src{t}.txt", "s\n", f"build {t}")
            run("checkout", "-q", "compose/p", cwd=wt)
        commit("pins.py", pins.replace('("task_prefix", "task_branch")', '("task_prefix", "rename", "task_branch")'), "main moves", cwd=r)  # inside the groundwork's diff context
        subprocess.run([CLI, "stack", "--repo", str(wt), "--project", "p"], check=True, capture_output=True, text=True, env=env)
        run("merge", "-q", "--ff-only", run("branch", "--list", "compose/p-layer-*", "--format=%(refname:short)").stdout.split()[-1])
        linear, out = FakeLinear(ENG_1=("In Review", None), ENG_2=("In Review", "ENG-1"), ENG_3=("In Review", "ENG-2"), ENG_4=("In Review", "ENG-2")), io.StringIO()
        with mock.patch.dict(os.environ, env), mock.patch("sys.stdout", out), \
                mock.patch.object(fc.fc_linear, "linear_gql", linear), mock.patch.object(fc.fc_config, "LINEAR_KEY", "k"):
            fc.fc_init.clean_project(r, "p", wt, proj, explicit=True)
        left = run("branch", "--format=%(refname:short)").stdout.split()
        self.assertEqual([b for b in left if b in ("compose/p", "compose/p-001", "compose/p-002")], [], out.getvalue())
        self.assertFalse(wt.exists())
        self.assertNotIn("UNMERGED", out.getvalue()); self.assertNotIn("kept unmerged", out.getvalue())
        self.assertEqual(linear.states("ENG-3", "ENG-4", "ENG-2", "ENG-1"), ["Done", "Done", "Done", "Done"])


class ReviewBaseFirst(unittest.TestCase):
    """Task branches are checked against the review base first, and each kept branch names its first commit with no patch there."""
    def setUp(self):
        self.r, self.run = repo()
        subprocess.run([CLI, "init", "--project", "p", "--repo", str(self.r)], check=True, capture_output=True, env={**os.environ, **ENV})
        self.wt = self.r.parent / "compose-p"; self.proj = self.wt / ".compose" / "p"

    def commit(self, branch, *subjects):
        """Commits on a new branch cut from compose/p (on compose/p itself when branch is None); their short shas, oldest first."""
        if branch:
            self.run("checkout", "-q", "-b", branch, "compose/p", cwd=self.wt)
        for s in subjects:
            (self.wt / s.replace(" ", "_")).write_text(f"{s}\n"); self.run("add", "-A", cwd=self.wt); self.run("commit", "-qm", s, cwd=self.wt)
        self.run("checkout", "-q", "compose/p", cwd=self.wt)
        return [self.run("rev-parse", "--short", f"{branch or 'compose/p'}~{i}").stdout.strip() for i in reversed(range(len(subjects)))]

    def clean(self, linear=None):
        out = io.StringIO()
        with mock.patch.dict(os.environ, ENV), mock.patch("sys.stdout", out), \
                mock.patch.object(fc.fc_linear, "linear_gql", linear), mock.patch.object(fc.fc_config, "LINEAR_KEY", "k"):
            fc.fc_init.clean_project(self.r, "p", self.wt, self.proj, explicit=True)
        return out.getvalue().splitlines()

    def test_task_branches_meet_the_review_base_first_and_kept_ones_name_their_first_unmatched_commit(self):
        self.commit("compose/p-002", "build 002"); self.run("merge", "-q", "--ff-only", "compose/p-002", cwd=self.wt)
        self.commit("compose/p-001", "build 001"); self.run("branch", "compose/base", "compose/p-001")  # 001 only in the review base
        three = self.commit("compose/p-003", "add three", "fix three")  # against main, build 002 would come first
        four, layer = self.commit("compose/p-004", "add four"), self.commit("compose/p-layer-01", "stack one")
        cfg = json.loads((self.proj / "verify.json").read_text()); cfg["review_base"] = "compose/base"
        (self.proj / "verify.json").write_text(json.dumps(cfg))
        tasks = [{"id": t, "title": t, "files": [], "protected": [], "linear": f"ENG-{n}", "after": "", "test": "true"} for n, t in enumerate(("001", "002", "003", "004"), 3)]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks})); (self.proj / "linear.json").write_text('{"feature": "ENG-1"}')
        linear = FakeLinear(ENG_1=("In Review", None), ENG_2=("In Review", "ENG-1"), **{f"ENG_{n}": ("In Review", "ENG-2") for n in range(3, 7)})
        lines = self.clean(linear)
        self.assertIn("clean  compose/p-001: contained in compose/base", lines)
        self.assertIn("clean  compose/p-002: contained in compose/base", lines)  # compose/p holds it too
        self.assertIn(f"clean  compose/p-003: kept unmerged, first unmatched commit {three[0]} add three and 1 more", lines)
        self.assertIn(f"clean  compose/p-004: kept unmerged, first unmatched commit {four[0]} add four", lines)
        self.assertIn(f"clean  compose/p-layer-01: kept unmerged, first unmatched commit {layer[0]} stack one", lines)
        self.assertEqual(self.run("branch", "--list", "compose/p-*", "--format=%(refname:short)").stdout.split(), ["compose/p-003", "compose/p-004", "compose/p-layer-01"])
        self.assertEqual(linear.states("ENG-3", "ENG-4", "ENG-5", "ENG-6"), ["Done", "Done", "In Review", "In Review"])

    def test_a_project_branch_kept_as_not_merged_yet_names_its_first_unmatched_commit_before_the_summary(self):
        first = self.commit(None, "groundwork one", "groundwork two")
        lines = self.clean()
        kept = f"clean  compose/p: kept unmerged, first unmatched commit {first[0]} groundwork one and 1 more"
        self.assertIn(kept, lines, lines)
        self.assertLess(lines.index(kept), next(i for i, l in enumerate(lines) if "project branch compose/p not merged yet" in l))
        self.assertTrue(self.wt.exists())


class ProjectBranchNamedFirst(unittest.TestCase):
    """The summary line of a removed project branch names the branch first, then why clean removed it, whatever the why."""
    def summary(self, branch, land, delete_unmerged=False):
        """Init project p on `branch` with one commit of its own, let `land` move main, clean, and return clean's lines and the worktree."""
        r, run = repo()
        subprocess.run([CLI, "init", "--project", "p", "--branch", branch, "--repo", str(r)], check=True, capture_output=True, env={**os.environ, **ENV})
        wt = r.parent / "compose-p"; proj = wt / ".compose" / "p"
        (wt / "a.txt").write_text("base\nx\n"); run("commit", "-qam", "groundwork", cwd=wt)
        land(r, run, proj)
        out = io.StringIO()
        with mock.patch.dict(os.environ, ENV), mock.patch("sys.stdout", out):
            fc.fc_init.clean_project(r, "p", wt, proj, explicit=True, delete_unmerged=delete_unmerged)
        return out.getvalue().splitlines(), wt

    def same_change_with_more(self, r, run, proj):  # main holds the groundwork's change inside a bigger patch
        (r / "a.txt").write_text("base\nx\n"); (r / "b.txt").write_text("y\n"); run("add", "-A"); run("commit", "-qm", "more")

    def layer_on_main(self, r, run, proj):  # main moves on its own; the one layer built from the branch sits in it
        (r / "c.txt").write_text("c\n"); run("add", "-A"); run("commit", "-qm", "main moves")
        run("branch", "compose/p-layer-01", "main"); (proj / "layers.json").write_text('{"compose/p-layer-01": ["001"]}')

    def test_each_why_reads_after_the_branch_name(self):
        for branch, land, why, delete_unmerged in (
                ("compose/p", lambda r, run, proj: run("merge", "-q", "--ff-only", "compose/p"), "contained in main", False),
                ("js-1-p", lambda r, run, proj: run("merge", "-q", "--ff-only", "js-1-p"), "contained in main", False),
                ("compose/p", lambda r, run, proj: run("cherry-pick", "-x", "compose/p"), "contained in main by patch", False),
                ("compose/p", self.same_change_with_more, "merging it into main changes nothing", False),
                ("compose/p", self.layer_on_main, "every layer built from it is merged (compose/p-layer-01)", False),
                ("compose/p", lambda r, run, proj: None, "UNMERGED, removed on --delete-unmerged", True)):
            with self.subTest(why=why, branch=branch):
                lines, wt = self.summary(branch, land, delete_unmerged)
                want = f"clean  p: task branches all merged and removed; project branch {branch}: {why}; removed worktree {wt} and branch {branch}"
                self.assertIn(want, lines, lines)
                self.assertFalse(wt.exists())


if __name__ == "__main__":
    unittest.main()
