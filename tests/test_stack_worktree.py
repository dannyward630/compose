import hermetic  # first: no test sees the real home
import contextlib, importlib.machinery, importlib.util, io, json, os, subprocess, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import sys
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"  # these cover the plain-worktree path; test_treehouse covers the pool
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)

ENV = {"HERDR_ENV": "", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


class StackWorktree(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, ENV); self.env.start(); self.addCleanup(self.env.stop)
        self.repo = Path(tempfile.mkdtemp())
        self.git("init", "-q", "-b", "main")
        (self.repo / "a.txt").write_text("base\n")
        self.git("add", "-A"); self.git("commit", "-qm", "init")
        self.proj = self.repo / ".compose" / "p"
        (self.proj / "results").mkdir(parents=True)
        (self.proj / "linear.json").write_text(json.dumps({"feature": "ENG-1"}))
        (self.repo / ".git" / "info" / "exclude").write_text("/.compose/\n")

    def git(self, *a):
        return subprocess.run(["git", *a], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def test_the_stack_worktree_sees_the_tool_dir(self):
        (self.proj / "e2e").mkdir(); (self.proj / "e2e" / "assert.sh").write_text("true\n")
        wt = fc.fc_worktree.stack_worktree(self.repo, self.proj, "main")
        self.assertTrue((wt / ".compose" / "p" / "e2e" / "assert.sh").exists())
        self.assertEqual(self.git("status", "--porcelain"), "")
        self.assertEqual(subprocess.run(["git", "status", "--porcelain"], cwd=wt, capture_output=True, text=True).stdout, "")

    def test_a_recorded_slot_of_another_repository_is_dropped_never_used(self):
        # a clone or copy that carries the project's results/slots.json rebuilt the original's branches in its stack worktree,
        # and clean wiped the tool folders in its slots
        other = Path(tempfile.mkdtemp()) / "other"
        subprocess.run(["git", "clone", "-q", str(self.repo), str(other)], check=True)
        theirs = other.parent / "stackroot"
        subprocess.run(["git", "worktree", "add", "-q", "--detach", str(theirs)], cwd=other, check=True, capture_output=True)
        (theirs / ".trail").mkdir()
        subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "their trunk moved"], cwd=other, check=True)
        head = lambda p: subprocess.run(["git", "rev-parse", "HEAD"], cwd=p, capture_output=True, text=True).stdout
        before = head(theirs)
        mine = Path(tempfile.mkdtemp()) / "mine"
        self.git("worktree", "add", "-q", "--detach", str(mine))
        recorded = {"stackroot": str(theirs), "tests-001": str(theirs), "tests-002": str(mine), "tests-003": str(other / "gone")}
        (self.proj / "results" / "slots.json").write_text(json.dumps(recorded))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            wt = fc.fc_worktree.stack_worktree(self.repo, self.proj, "main")
        common = lambda p: subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=p, capture_output=True, text=True).stdout
        self.assertEqual(common(wt), common(self.repo))
        self.assertEqual(head(theirs), before)
        self.assertEqual(fc.fc_worktree.slots(self.proj), {"tests-002": str(mine), "tests-003": str(other / "gone")})
        self.assertEqual(json.loads((self.proj / "results" / "slots.json").read_text()), {"tests-002": str(mine), "tests-003": str(other / "gone")})
        for role in ("stackroot", "tests-001"):
            self.assertIn(f"{role} {theirs}", out.getvalue())
        fc.fc_init.clean_project(self.repo, "p", self.repo, self.proj)
        self.assertTrue((theirs / ".trail").is_dir())

    def test_verify_installs_in_the_worktree_at_the_stack_top(self):
        (self.repo / ".gitignore").write_text("node_modules/\n.compose/\n")
        (self.repo / "bun.lock").write_text("trunk\n")
        self.git("add", "-A"); self.git("commit", "-qm", "lock")
        self.git("checkout", "-q", "-b", "top"); (self.repo / "bun.lock").write_text("top\n")
        self.git("commit", "-qam", "dep"); self.git("checkout", "-q", "main")
        cfg = {"install": "mkdir -p node_modules && cat bun.lock >> node_modules/seen"}
        with mock.patch.object(fc.fc_worktree, "stack_order", return_value=["top"]), mock.patch.object(fc.fc_layers, "linearize", return_value=["top"]):
            wt, _, _ = fc.fc_verify.verify_root(self.repo, self.proj, cfg)
        self.assertEqual((wt / "node_modules" / "seen").read_text(), "top\n")  # installed once, against the top layer's lockfile


class BranchNames(unittest.TestCase):
    setUp, git = StackWorktree.setUp, StackWorktree.git

    def prefix(self, verify=None, *refs):
        (self.proj / "verify.json").unlink(missing_ok=True)
        if verify is not None:
            (self.proj / "verify.json").write_text(json.dumps(verify))
        for r in refs:
            self.git("update-ref", r, "HEAD")
        return fc.fc_worktree.task_prefix(self.repo, self.proj)

    def test_the_prefix_comes_from_the_record_legacy_branches_or_the_project_branch(self):
        self.assertEqual(self.prefix(), "compose/p-")
        self.assertEqual((self.prefix({"branch": "compose/p"}), fc.fc_worktree.task_branch(self.repo, self.proj, "001")), ("compose/p-", "compose/p-001"))
        self.assertEqual((self.prefix({"branch": "p"}), fc.fc_worktree.task_branch(self.repo, self.proj, "001")), ("p-", "p-001"))
        self.assertEqual(self.prefix({"branch": "p"}, "refs/heads/fast/p-2/001", "refs/heads/fast/pp/001"), "p-")  # another project's legacy branches
        self.assertEqual(self.prefix({"task_prefix": "x/"}, "refs/remotes/origin/fast/p/001"), "x/")  # the record wins
        self.assertEqual(self.prefix({"branch": "p"}), "fast/p/")  # only a remote-tracking legacy ref
        self.assertEqual(self.prefix(None, "refs/heads/fast/p/001"), "fast/p/")
        self.assertFalse((self.proj / "verify.json").exists())  # recorded only into an existing file
        self.prefix({"branch": "p"})
        self.git("update-ref", "-d", "refs/heads/fast/p/001"); self.git("update-ref", "-d", "refs/remotes/origin/fast/p/001")
        self.assertEqual(fc.fc_worktree.task_prefix(self.repo, self.proj), "fast/p/")
        self.assertEqual(json.loads((self.proj / "verify.json").read_text()), {"branch": "p", "task_prefix": "fast/p/"})

    def test_own_branches_are_task_bench_and_test_writer_branches_only(self):
        for b in ("compose/p", "compose/p-001", "compose/p-002-bench-x", "compose/p-tests-001", "compose/p-layer-01", "compose/p-2-001", "compose/p-0001"):
            self.git("branch", b)
        self.git("update-ref", "refs/remotes/origin/compose/p-003", "HEAD")
        self.assertEqual(set(fc.fc_worktree.own_branches(self.repo, self.proj)), {"compose/p-001", "compose/p-002-bench-x", "compose/p-tests-001"})

    def test_task_branches_and_the_stack_order_use_the_new_names(self):
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": [{"id": "001", "after": "002"}, {"id": "002"}]}))
        (self.proj / "results" / "001.json").write_text(json.dumps({"base": "compose/p-002"}))
        for b in ("compose/p-002", "compose/p-001", "compose/p-tests-001", "compose/p-layer-01", "compose/p-2-001"):
            self.git("checkout", "-q", "-b", b); self.git("commit", "-q", "--allow-empty", "-m", b)
        self.git("checkout", "-q", "main")
        self.assertEqual(fc.fc_worktree.task_branches(self.repo, self.proj), {"compose/p-001": "compose/p-002", "compose/p-002": None})
        self.assertEqual(fc.fc_worktree.stack_order(self.repo, self.proj), ["compose/p-002", "compose/p-001"])

    def test_a_replaced_tip_maps_back_to_its_new_name(self):
        for verify, b in (({}, "compose/p-001"), ({"branch": "p"}, "p-001")):
            (self.proj / "verify.json").write_text(json.dumps(verify)); self.git("branch", b); tip = self.git("rev-parse", b)
            fc.fc_worktree.replace_branch(self.repo, self.proj, b)
            self.assertEqual(fc.fc_worktree.replaced_tips(self.repo, self.proj), [(b, tip)])
            self.assertEqual(self.git("for-each-ref", "--format=%(refname)", "refs/compose/replaced/"), f"refs/compose/replaced/p/001/{tip}")
            self.git("update-ref", "-d", f"refs/compose/replaced/p/001/{tip}")

    def legacy(self):
        """A project on fast/p/ names, recorded wherever the CLI records a branch, one branch checked out in a worktree."""
        (self.proj / "verify.json").write_text(json.dumps({"review_base": "main", "task_prefix": "fast/p/", "layer_prefix": "fast/p/"}))
        for b in ("fast/p/001", "fast/p/002", "fast/p/002-bench-x", "fast/p/tests-003", "fast/p/layer-01", "fast/p/layer-02", "fast/pp/001"):
            self.git("branch", b)
        self.git("update-ref", f"refs/compose/replaced/p/001/{self.git('rev-parse', 'HEAD')}", "HEAD")
        self.wt = Path(tempfile.mkdtemp()) / "wt"
        self.git("worktree", "add", "-q", str(self.wt), "fast/p/002")
        (self.proj / "results" / "changes").mkdir(exist_ok=True)
        files = {"results/002.json": {"branch": "fast/p/002", "base": "fast/p/001", "worktree": "/w/002"},
                 "results/changes/C1.json": {"results": {"002": {"branch": "fast/p/002", "base": "fast/p/001"}}},
                 "layers.json": {"fast/p/layer-01": ["groundwork"], "fast/p/layer-02": ["001", "002"]},
                 "pr_text.json": {"fast/p/layer-01": {"title": "t", "body": "fast/p/layer-01 holds groundwork"}}}
        for rel, data in files.items():
            (self.proj / rel).write_text(json.dumps(data))
        stacks = {"schemaVersion": 1, "stacks": [{"trunk": {"branch": "main"}, "branches": [{"branch": "fast/p/layer-01"}, {"branch": "fast/p/layer-02"}]},
                                                 {"trunk": {"branch": "main"}, "branches": [{"branch": "fast/pp/001"}]}]}
        (self.repo / ".git" / "gh-stack").write_text(json.dumps(stacks))
        return {rel: (self.proj / rel).read_text() for rel in ["verify.json", *files]} | {"gh-stack": json.dumps(stacks)}

    def recorded(self):
        return {rel: (self.proj / rel).read_text() for rel in ("verify.json", "results/002.json", "results/changes/C1.json", "layers.json", "pr_text.json")} \
            | {"gh-stack": (self.repo / ".git" / "gh-stack").read_text()}

    def test_never_pushed_fast_branches_take_a_new_projects_names_once_with_every_record(self):
        self.legacy()
        self.assertTrue(fc.fc_worktree.rename_legacy_branches(self.repo, self.proj))
        self.assertEqual(self.git("branch", "--list", "--format=%(refname:short)").split(),
                         ["compose/p-001", "compose/p-002", "compose/p-002-bench-x", "compose/p-layer-01", "compose/p-layer-02", "compose/p-tests-003", "fast/pp/001", "main"])
        self.assertEqual(subprocess.run(["git", "branch", "--show-current"], cwd=self.wt, capture_output=True, text=True).stdout.strip(), "compose/p-002")
        cfg = json.loads((self.proj / "verify.json").read_text())
        self.assertEqual((cfg["review_base"], cfg["task_prefix"], cfg["layer_prefix"]), ("main", "compose/p-", "compose/p-"))
        (self.proj / "verify.json").write_text("{}")
        fresh = fc.fc_layers.layer_prefix(self.repo, self.proj)
        (self.proj / "verify.json").write_text(json.dumps(cfg))
        self.assertEqual(fc.fc_layers.layer_prefix(self.repo, self.proj), fresh)  # the layers are named as a new project's
        self.assertEqual(json.loads((self.proj / "results" / "002.json").read_text()), {"branch": "compose/p-002", "base": "compose/p-001", "worktree": "/w/002"})
        self.assertEqual(json.loads((self.proj / "results" / "changes" / "C1.json").read_text())["results"]["002"], {"branch": "compose/p-002", "base": "compose/p-001"})
        self.assertEqual(json.loads((self.proj / "layers.json").read_text()), {"compose/p-layer-01": ["groundwork"], "compose/p-layer-02": ["001", "002"]})
        self.assertEqual(json.loads((self.proj / "pr_text.json").read_text()), {"compose/p-layer-01": {"title": "t", "body": "fast/p/layer-01 holds groundwork"}})
        stacks = json.loads((self.repo / ".git" / "gh-stack").read_text())["stacks"]
        self.assertEqual([[b["branch"] for b in s["branches"]] for s in stacks], [["compose/p-layer-01", "compose/p-layer-02"], ["fast/pp/001"]])
        self.assertEqual(fc.fc_worktree.replaced_tips(self.repo, self.proj), [("compose/p-001", self.git("rev-parse", "HEAD"))])
        before = self.recorded()
        self.git("update-ref", "refs/remotes/origin/fast/p/009", "HEAD")  # someone else's push, fetched later
        self.assertFalse(fc.fc_worktree.rename_legacy_branches(self.repo, self.proj))  # once
        self.assertEqual((fc.fc_worktree.task_prefix(self.repo, self.proj), self.recorded()), ("compose/p-", before))

    def test_a_pushed_live_or_blocked_project_keeps_every_name(self):
        branches = lambda: self.git("branch", "--list", "--format=%(refname:short)").split()
        for case in ("pushed", "live", "taken"):
            with self.subTest(case):
                if case != "pushed":
                    self.git("worktree", "remove", "--force", str(self.wt))
                for b in self.git("for-each-ref", "--format=%(refname)", "refs/heads/fast/", "refs/heads/compose/", "refs/remotes/").split():
                    self.git("update-ref", "-d", b)
                before = self.legacy()
                if case == "pushed":
                    self.git("update-ref", "refs/remotes/origin/fast/p/layer-01", "HEAD")
                if case == "live":
                    other = subprocess.Popen(["sleep", "30"]); self.addCleanup(other.kill)
                    (self.proj / "results" / "run.json").write_text(json.dumps({"pid": other.pid}))
                if case == "taken":
                    (self.proj / "results" / "run.json").unlink()
                    self.git("branch", "compose/p-001")
                names = branches()
                self.assertFalse(fc.fc_worktree.rename_legacy_branches(self.repo, self.proj))
                self.assertEqual((branches(), self.recorded()), (names, before))


class ReviewGate(unittest.TestCase):
    def test_confirmed_review_findings_fail_verify(self):
        proj = Path(tempfile.mkdtemp()) / "p"; (proj / "results").mkdir(parents=True)
        (proj / "linear.json").write_text(json.dumps({"feature": "ENG-1"}))
        high = {"file": "s.go", "severity": "high", "note": "a query per answer", "confirmed": True}
        rv = {"pass": False, "issues": [high], "confirmed": [high]}
        a = SimpleNamespace(skip_e2e=True, skip_review=False)
        with mock.patch.dict(os.environ, {"HERDR_ENV": ""}), mock.patch.object(fc.fc_verify, "llm_review", return_value=rv), \
                mock.patch.object(fc.fc_verify, "review_inputs", return_value=("diff", "plan", "", [])):
            ok, _, findings = fc.fc_verify.run_stages(proj, proj, {"review": True, "jev_acceptance": False}, a)
        self.assertFalse(ok); self.assertIn("a query per answer", findings)


if __name__ == "__main__":
    unittest.main()
