import importlib.machinery, importlib.util, io, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)

CLI = str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")
ENV = {"FAST_CODING_NO_GRAFT": "1", "HERDR_ENV": "", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def repo():
    r = Path(tempfile.mkdtemp()).resolve() / "repo"
    r.mkdir()
    run = lambda *a, cwd=r: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True)
    run("init", "-q", "-b", "main")
    (r / "a.txt").write_text("base\n")
    (r / ".git" / "info" / "exclude").write_text("/.fast-coding/\n")
    run("add", "-A"); run("commit", "-qm", "init")
    return r, run


class TestCrewWorktrees(unittest.TestCase):
    """Test crews write on their own branches; collect brings their commits back in task order."""
    def setUp(self):
        self.env = mock.patch.dict(os.environ, ENV); self.env.start(); self.addCleanup(self.env.stop)
        self.repo, self.run = repo()
        self.proj = self.repo / ".fast-coding" / "p"
        (self.proj / "results").mkdir(parents=True)
        tasks = [{"id": "001", "title": "A", "files": ["a.go"], "protected": ["a_test.go"], "test": "true", "body": "a"},
                 {"id": "002", "title": "B", "files": ["b.go"], "protected": ["b_test.go"], "test": "true", "body": "b", "test_lines": "25"}]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))
        for p in (mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch.object(fc, "project_worktree", return_value=self.repo)):
            p.start(); self.addCleanup(p.stop)

    def crew_commits(self, tid, name, text):
        wt = fc.test_worktree(self.proj, tid)
        (wt / name).write_text(text)
        self.run("add", name, cwd=wt); self.run("commit", "-qm", f"Test {name}", cwd=wt)

    def test_each_crew_has_its_own_branch_and_collect_lands_them_in_order(self):
        self.crew_commits("002", "b_test.go", "b\n")
        self.crew_commits("001", "a_test.go", "a\n")
        self.assertEqual(self.run("branch", "--show-current").stdout.strip(), "main")  # the project checkout never moved
        fc.collect_tests(self.proj)
        log = self.run("log", "--format=%s", "-3").stdout.split("\n")
        self.assertEqual(log[:2], ["Test b_test.go", "Test a_test.go"])  # 001 first, then 002
        self.assertTrue((self.repo / "a_test.go").exists() and (self.repo / "b_test.go").exists())
        self.assertEqual(self.run("branch", "--list", "fast/p/tests-*").stdout.strip(), "")
        self.assertFalse((self.proj / "worktrees" / "tests-001").exists())

    def test_run_collects_finished_test_crews_and_waits_for_busy_ones(self):
        from types import SimpleNamespace
        self.crew_commits("001", "a_test.go", "a\n")
        a = SimpleNamespace(repo=str(self.repo), project="p", only=None, redo=False)
        with mock.patch.object(fc, "run_tasks") as rt, mock.patch.object(fc, "crew_reports", return_value=[{"state": "working"}]):
            with self.assertRaises(SystemExit) as e:
                fc.cmd_run(a)
            self.assertIn("tests-001", str(e.exception)); rt.assert_not_called()
        with mock.patch.object(fc, "run_tasks") as rt, mock.patch.object(fc, "crew_reports", return_value=[{"state": "done"}]):
            fc.cmd_run(a)
            rt.assert_called_once()
        self.assertTrue((self.repo / "a_test.go").exists())  # collected before the run

    def test_a_conflict_names_the_task_and_keeps_its_branch(self):
        self.crew_commits("001", "a.txt", "crew\n")
        (self.repo / "a.txt").write_text("main\n"); self.run("commit", "-qam", "main moved")
        with self.assertRaises(SystemExit) as e:
            fc.collect_tests(self.proj)
        self.assertIn("tests-001", str(e.exception))
        self.assertIn("fast/p/tests-001", self.run("branch", "--list", "fast/p/tests-001").stdout)
        self.assertEqual(self.run("status", "--porcelain").stdout.strip(), "")  # the cherry-pick was aborted cleanly

    def test_brief_states_the_line_budget(self):
        tasks = fc.load_tasks(self.proj)
        self.assertIn("at most 60 lines", fc.test_brief(tasks[0], "c"))
        self.assertIn("at most 25 lines", fc.test_brief(tasks[1], "c"))  # the task's test_lines wins
        self.assertIn("at most 40 lines", fc.test_brief(tasks[0], "c", 40))


def server(cwd):
    p = subprocess.Popen([sys.executable, "-m", "http.server", "0", "--bind", "127.0.0.1"], cwd=cwd,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(50):
        if str(p.pid) in subprocess.run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-t"], capture_output=True, text=True).stdout.split():
            return p
        time.sleep(0.1)
    raise AssertionError("server never listened")


class Leftovers(unittest.TestCase):
    """Servers a crew or run leaves in the project end with teardown; anything else is left alone."""
    def test_teardown_stops_servers_in_the_project_only(self):
        proj_wt = Path(tempfile.mkdtemp()).resolve()
        proj = proj_wt / ".fast-coding" / "p"
        scratch = fc.scratch_dir(proj, "p-groundwork"); scratch.mkdir(parents=True)
        mine, other = server(scratch), server(tempfile.mkdtemp())
        self.addCleanup(lambda: [(p.kill(), p.wait()) for p in (mine, other)])
        with mock.patch.object(fc, "project_worktree", return_value=proj_wt), mock.patch.dict(os.environ, {"HERDR_ENV": ""}), \
                mock.patch("sys.stdout", io.StringIO()):
            fc.teardown(proj)
        self.assertIsNotNone(mine.wait(timeout=5))
        self.assertIsNone(other.poll())
        self.assertFalse(fc.scratch_dir(proj).exists())

    def test_preamble_points_scratch_inside_the_project(self):
        proj = Path(tempfile.mkdtemp()) / ".fast-coding" / "shop"
        with mock.patch.object(fc, "project_worktree", return_value=proj.parent.parent):
            pre = fc.crew_preamble(proj, "shop-groundwork", "groundwork")
        self.assertIn(str(proj / "scratch" / "shop-groundwork"), pre)
        self.assertIn("never /tmp", pre)

    def test_only_daemons_started_since_the_snapshot_end(self):
        spawn = lambda: subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "browser_harness.daemon"])
        old = spawn(); self.addCleanup(lambda: (old.kill(), old.wait()))
        time.sleep(0.2)
        before = fc.harness_daemons()
        new = spawn(); self.addCleanup(lambda: (new.kill(), new.wait()))
        time.sleep(0.2)
        self.assertIn(str(new.pid), fc.end_new_daemons(before))
        self.assertIsNotNone(new.wait(timeout=5))
        self.assertIsNone(old.poll())


class StartOver(unittest.TestCase):
    def test_delete_unmerged_removes_the_project_folder_with_its_ignored_files(self):
        r, run = repo()
        env = {**os.environ, **ENV}
        subprocess.run([CLI, "init", "--project", "p", "--repo", str(r)], check=True, capture_output=True, env=env)
        wt = r.parent / "fast-coding-p"
        (wt / ".fast-coding" / "p" / "results" / "x.json").parent.mkdir(parents=True, exist_ok=True)
        (wt / ".fast-coding" / "p" / "results" / "x.json").write_text("{}")
        (wt / "feature.txt").write_text("f\n")
        subprocess.run(["git", "add", "feature.txt"], cwd=wt, check=True, env=env)
        subprocess.run(["git", "commit", "-qm", "feature"], cwd=wt, check=True, env=env)
        subprocess.run([CLI, "clean", "--project", "p", "--delete-unmerged", "--repo", str(r)], check=True, capture_output=True, env=env)
        self.assertFalse(wt.exists())
        self.assertEqual(run("branch", "--list", "fast-coding/p").stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
