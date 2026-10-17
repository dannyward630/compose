import importlib.machinery, importlib.util, io, json, os, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
os.environ["FAST_CODING_NO_TREEHOUSE"] = "1"  # these cover the plain-worktree path; test_treehouse covers the pool

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast_coding.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
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
    """Test-writing teammates write on their own branches; collect brings their commits back in task order."""
    def setUp(self):
        self.env = mock.patch.dict(os.environ, ENV); self.env.start(); self.addCleanup(self.env.stop)
        self.repo, self.run = repo()
        self.proj = self.repo / ".fast-coding" / "p"
        (self.proj / "results").mkdir(parents=True)
        tasks = [{"id": "001", "title": "A", "files": ["a.go"], "protected": ["a_test.go"], "test": "true", "body": "a"},
                 {"id": "002", "title": "B", "files": ["b.go"], "protected": ["b_test.go"], "test": "true", "body": "b", "test_lines": "25"}]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))
        for p in (mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch.object(fc.fc_herdr, "project_worktree", return_value=self.repo)):
            p.start(); self.addCleanup(p.stop)

    def crew_commits(self, tid, name, text):
        wt = fc.fc_briefs.test_worktree(self.proj, tid)
        (wt / name).write_text(text)
        self.run("add", name, cwd=wt); self.run("commit", "-qm", f"Test {name}", cwd=wt)

    def test_each_crew_has_its_own_branch_and_collect_lands_them_in_order(self):
        self.crew_commits("002", "b_test.go", "b\n")
        self.crew_commits("001", "a_test.go", "a\n")
        self.assertEqual(self.run("branch", "--show-current").stdout.strip(), "main")  # the project checkout never moved
        fc.fc_briefs.collect_tests(self.proj)
        log = self.run("log", "--format=%s", "-3").stdout.split("\n")
        self.assertEqual(log[:2], ["Test b_test.go", "Test a_test.go"])  # 001 first, then 002
        self.assertTrue((self.repo / "a_test.go").exists() and (self.repo / "b_test.go").exists())
        self.assertEqual(self.run("branch", "--list", "fast/p/tests-*").stdout.strip(), "")
        self.assertFalse((self.proj / "worktrees" / "tests-001").exists())

    def test_run_collects_finished_test_crews_and_waits_for_busy_ones(self):
        from types import SimpleNamespace
        self.crew_commits("001", "a_test.go", "a\n")
        a = SimpleNamespace(repo=str(self.repo), project="p", only=None, redo=False)
        with mock.patch.object(fc, "run_tasks") as rt, mock.patch.object(fc.fc_crew, "crew_reports", return_value=[{"state": "working"}]):
            with self.assertRaises(SystemExit) as e:
                fc.cmd_run(a)
            self.assertIn("tests-001", str(e.exception)); rt.assert_not_called()
        with mock.patch.object(fc, "run_tasks") as rt, mock.patch.object(fc.fc_crew, "crew_reports", return_value=[{"state": "done"}]):
            fc.cmd_run(a)
            rt.assert_called_once()
        self.assertTrue((self.repo / "a_test.go").exists())  # collected before the run

    def test_a_conflict_names_the_task_and_keeps_its_branch(self):
        self.crew_commits("001", "a.txt", "teammate\n")
        (self.repo / "a.txt").write_text("main\n"); self.run("commit", "-qam", "main moved")
        with self.assertRaises(SystemExit) as e:
            fc.fc_briefs.collect_tests(self.proj)
        self.assertIn("tests-001", str(e.exception))
        self.assertIn("fast/p/tests-001", self.run("branch", "--list", "fast/p/tests-001").stdout)
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
            self.run("cherry-pick", "fast/p/tests-001")  # the team lead picks it by hand and resolves the conflict
        (self.repo / "t.py").write_text("import a, b, c, d\n\ndef one():\n    pass\n\ndef three():\n    pass\n\ndef two():\n    pass\n")
        self.run("add", "t.py"); self.run("-c", "core.editor=true", "cherry-pick", "--continue")
        trimmed = "import a, b, c, d\n\ndef one():\n    pass\n\ndef three():\n    pass\n"
        self.main_commits("t.py", trimmed, "Drop test two")  # then edits it on the branch: a replay would bring it back
        self.run("cherry-pick", "fast/p/tests-002")  # a clean hand pick: same patch
        self.crew_commits("003", "c_test.go", "c\n")
        fc.fc_briefs.collect_tests(self.proj)
        self.assertEqual((self.repo / "t.py").read_text(), trimmed)
        self.assertEqual(self.run("log", "--format=%s", "-2").stdout.split("\n")[:2], ["Test c_test.go", "Test b_test.go"])
        self.assertEqual(self.run("status", "--porcelain").stdout.strip(), "")
        self.assertEqual(self.run("branch", "--list", "fast/p/tests-*").stdout.strip(), "")

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
        proj = proj_wt / ".fast-coding" / "p"
        scratch = fc.fc_crew.scratch_dir(proj, "p-groundwork"); scratch.mkdir(parents=True)
        mine, other = server(scratch), server(tempfile.mkdtemp())
        self.addCleanup(lambda: [(p.kill(), p.wait()) for p in (mine, other)])
        with mock.patch.object(fc.fc_herdr, "project_worktree", return_value=proj_wt), mock.patch.dict(os.environ, {"HERDR_ENV": ""}), \
                mock.patch("sys.stdout", io.StringIO()):
            fc.fc_crew.teardown(proj)
        self.assertIsNotNone(mine.wait(timeout=5))
        self.assertIsNone(other.poll())
        self.assertFalse(fc.fc_crew.scratch_dir(proj).exists())

    def test_preamble_points_scratch_inside_the_project(self):
        proj = Path(tempfile.mkdtemp()) / ".fast-coding" / "shop"
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
        before = fc.harness_daemons(mine_name)
        mine, other = spawn(mine_name), spawn(other_name)  # another project's stage starts one meanwhile: kept
        time.sleep(0.2)
        self.assertEqual(fc.end_new_daemons(mine_name, before), {str(mine.pid)})
        self.assertIsNotNone(mine.wait(timeout=5))
        self.assertIsNone(shared.poll())
        self.assertIsNone(other.poll())


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


class CleanSafety(unittest.TestCase):
    """A repo-wide clean only removes projects whose work is provably done, and never one with live crew."""
    def setUp(self):
        self.r, self.run = repo()
        self.env = {**os.environ, **ENV}
        for n in ("empty", "work"):
            subprocess.run([CLI, "init", "--project", n, "--repo", str(self.r)], check=True, capture_output=True, env=self.env)
        self.wt = {n: self.r.parent / f"fast-coding-{n}" for n in ("empty", "work")}
        (self.wt["work"] / "f.txt").write_text("f\n")
        subprocess.run(["git", "add", "-A"], cwd=self.wt["work"], check=True, env=self.env)
        subprocess.run(["git", "commit", "-qm", "work"], cwd=self.wt["work"], check=True, env=self.env)
        self.run("merge", "-q", "--ff-only", "fast-coding/work")

    def clean(self, *args):
        return subprocess.run([CLI, "clean", "--repo", str(self.r), *args], capture_output=True, text=True, env=self.env)

    def crew(self, n, state):
        d = self.wt[n] / ".fast-coding" / n / "results" / "crew"
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
        wt = self.r.parent / "fast-coding-p"
        self.assertIn("js-1-p", self.branches())
        self.assertNotIn("fast-coding/p", self.branches())
        self.assertEqual(json.loads((wt / ".fast-coding" / "p" / "verify.json").read_text())["branch"], "js-1-p")
        self.cli("init", "--project", "q", "--after", "p")  # resolves p's stored branch, not fast-coding/p
        qcfg = json.loads((self.r.parent / "fast-coding-q" / ".fast-coding" / "q" / "verify.json").read_text())
        self.assertEqual((qcfg["review_base"], qcfg["after"]), ("js-1-p", "p"))
        self.cli("init", "--project", "p", "--branch", "js-2-p")  # an existing project moves to the new name
        self.assertEqual(self.run("branch", "--show-current", cwd=wt).stdout.strip(), "js-2-p")
        self.assertNotIn("js-1-p", self.branches())
        self.assertEqual(json.loads((self.r.parent / "fast-coding-q" / ".fast-coding" / "q" / "verify.json").read_text())["review_base"], "js-2-p")
        self.cli("clean", "--project", "q", "--delete-unmerged")
        self.cli("clean", "--project", "p", "--delete-unmerged")
        self.assertEqual(self.branches(), ["main"])

    def test_a_project_without_a_stored_branch_keeps_fast_coding_slash_slug(self):
        self.cli("init", "--project", "old")
        f = self.r.parent / "fast-coding-old" / ".fast-coding" / "old" / "verify.json"
        f.write_text(json.dumps({k: v for k, v in json.loads(f.read_text()).items() if k != "branch"}))
        self.assertEqual(fc.fc_core.project_branch(f.parent), "fast-coding/old")
        self.assertIn("fast-coding/old", self.branches())


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
        self.proj = self.r.parent / "fast-coding-p" / ".fast-coding" / "p"
        tip = self.run("rev-parse", "main").stdout.strip()
        for b in ("fast/p/001", "fast/p/002", "fast/p/layer-01", "fast/p/layer-02"):  # commits on top of main: never ancestors of it
            c = self.run("commit-tree", "main^{tree}", "-p", tip, "-m", b).stdout.strip()
            self.run("branch", b, c)
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
        self.assertFalse((self.r.parent / "fast-coding-p").exists())
        self.assertEqual(self.run("ls-remote", "--heads", "origin").stdout.count("fast/p/"), 0)

    def test_clean_removes_the_project_branch_once_every_layer_built_from_it_is_merged(self):
        wt = self.r.parent / "fast-coding-p"
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
        self.assertNotIn("fast-coding/p", self.run("branch", "--format=%(refname:short)").stdout.split())

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
            fc.fc_init.clean_project(self.r, "p", self.r.parent / "fast-coding-p", self.proj, explicit=True)
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
        self.assertFalse((self.r.parent / "fast-coding-p").exists())

    def test_clean_without_a_linear_key_says_so_in_one_line_and_calls_nothing(self):
        self.linear_project()
        with mock.patch.object(fc.fc_linear, "linear_gql", side_effect=AssertionError("Linear called without a key")), \
                mock.patch.object(fc.fc_config, "LINEAR_KEY", ""), mock.patch.object(fc.fc_linear, "_linear_warned", []):
            out = self.clean_here()
        self.assertEqual(out.count("linear skipped"), 1, out)
        self.assertIn("fast/p/001", out)  # the branches are still cleaned



if __name__ == "__main__":
    unittest.main()
