import importlib.machinery, importlib.util, json, os, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock
os.environ["FAST_CODING_NO_TREEHOUSE"] = "1"  # these cover the plain-worktree path; test_treehouse covers the pool

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)

ENV = {"HERDR_ENV": "", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


class RedoMidChain(unittest.TestCase):
    """Rebuilding a layer in the middle of the stack: the layers above still carry its old commit, and the chain rebase drops it."""
    def setUp(self):
        self.env = mock.patch.dict(os.environ, ENV); self.env.start()
        self.repo = Path(tempfile.mkdtemp()).resolve()
        self.git("init", "-q", "-b", "main")
        (self.repo / "a.txt").write_text("base\n")
        self.git("add", "-A"); self.git("commit", "-qm", "init")
        self.proj = self.repo / ".fast-coding" / "p"
        (self.proj / "results").mkdir(parents=True); (self.proj / "worktrees").mkdir()
        (self.repo / ".git" / "info" / "exclude").write_text("/.fast-coding/\n")
        after = {"011": "010", "012": "011", "005": "012"}
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": [{"id": t, "after": after.get(t, "")} for t in ("010", "011", "012", "005")]}))
        for t, base in (("010", "main"), ("011", "fast/p/010"), ("012", "fast/p/011"), ("005", "fast/p/012")):
            self.layer(t, base, "c.txt" if t == "011" else f"{t}.txt", "old\n")

    def tearDown(self):
        self.env.stop()

    def git(self, *a):
        return subprocess.run(["git", *a], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def layer(self, tid, base, name, text):
        self.git("checkout", "-q", "-b", f"fast/p/{tid}", base)
        (self.repo / name).write_text(text)
        self.git("add", "-A"); self.git("commit", "-qm", f"task {tid}")
        self.git("checkout", "-q", "main")

    def test_layers_above_a_rebuilt_layer_replay_onto_it_without_its_old_commit(self):
        fc.replace_branch(self.repo, self.proj, "fast/p/011")
        self.layer("011", "fast/p/010", "c.txt", "new\n")
        chain = fc.linearize(self.repo, self.proj, "main", fc.stack_worktree(self.repo, self.proj, "main"))
        self.assertEqual(chain, [f"fast/p/{t}" for t in ("010", "011", "012", "005")])
        self.assertEqual(self.git("show", "fast/p/005:c.txt"), "new")
        self.assertEqual(self.git("rev-list", "--count", "main..fast/p/005"), "4")  # one commit per layer, the old 011 is gone
        self.assertEqual(self.git("for-each-ref", "refs/fast-coding/replaced/"), "")  # nothing carries the old tip any more


class KeepFinishedLayers(unittest.TestCase):
    """A plain `run` re-enters every task: a layer that passed, or that a teammate finished by hand on top of its pass, keeps its
    branch. Rebuilding a hand-done layer threw away the teammate's commit, so the team lead could not record it."""
    def setUp(self):
        self.env = mock.patch.dict(os.environ, ENV); self.env.start(); self.addCleanup(self.env.stop)
        os.environ.pop("FAST_CODING_REDO", None)
        self.repo = Path(tempfile.mkdtemp()).resolve()
        git = lambda *a: subprocess.run(["git", *a], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()
        git("init", "-q", "-b", "main"); (self.repo / "a.txt").write_text("base\n"); git("add", "-A"); git("commit", "-qm", "init")
        git("checkout", "-q", "-b", "fast/p/001"); (self.repo / "b.txt").write_text("teammate\n"); git("add", "-A"); git("commit", "-qm", "teammate's commit")
        git("checkout", "-q", "main")
        self.tip = git("rev-parse", "fast/p/001")
        self.git = git
        self.proj = self.repo / ".fast-coding" / "p"
        (self.proj / "results").mkdir(parents=True); (self.proj / "worktrees").mkdir()

    def test_a_passed_or_hand_done_layer_keeps_its_branch(self):
        for status in ("passed", "hand_done"):
            (self.proj / "results" / "001.json").write_text(json.dumps({"id": "001", "status": status, "branch": "fast/p/001"}))
            with mock.patch.object(fc, "replace_branch", side_effect=AssertionError(f"a {status} layer was rebuilt")), mock.patch.object(fc, "say"):
                r = fc.run_task(self.repo, self.proj, {"id": "001", "title": "A", "files": [], "body": ""}, 1)
            self.assertEqual(r["status"], status)
            self.assertEqual(self.git("rev-parse", "fast/p/001"), self.tip)

    def test_a_hand_done_task_without_a_branch_is_kept_and_never_moves_linear_unless_redone(self):
        self.git("branch", "-D", "fast/p/001")  # its work was committed on the project branch, as groundwork
        (self.proj / "results" / "001.json").write_text(json.dumps({"id": "001", "status": "hand_done"}))
        task = {"id": "001", "title": "A", "files": [], "body": ""}
        with mock.patch.object(fc, "replace_branch", side_effect=AssertionError("a hand_done task was rebuilt")), \
             mock.patch.object(fc, "linear_event", side_effect=AssertionError("a hand_done task moved Linear")), mock.patch.object(fc, "say"):
            self.assertEqual(fc.run_task(self.repo, self.proj, task, 1)["status"], "hand_done")
        with mock.patch.dict(os.environ, {"FAST_CODING_REDO": "1"}), mock.patch.object(fc, "replace_branch", side_effect=RuntimeError("rebuilt")):
            with self.assertRaisesRegex(RuntimeError, "rebuilt"):
                fc.run_task(self.repo, self.proj, task, 1)

    def test_run_and_resume_schedule_only_the_tasks_that_need_work(self):
        (self.repo / ".git" / "info" / "exclude").write_text("/.fast-coding/\n")
        self.git("branch", "-D", "fast/p/001")
        states = {"001": "hand_done", "003": "passed", "005": "failed"}
        tasks = [{"id": t, "title": t, "files": [], "protected": [], "test": "true", "body": "", "model": "m",
                  **({"linear_state": "Canceled"} if t == "002" else {})} for t in ("001", "002", "003", "004", "005")]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))
        for t, st in states.items():
            (self.proj / "results" / f"{t}.json").write_text(json.dumps({"id": t, "status": st}))
        ran = []
        a = lambda **kw: mock.Mock(repo=str(self.repo), project="p", only=None, redo=False, **kw)
        with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch.object(fc, "project_worktree", return_value=self.repo), \
             mock.patch.object(fc, "run_tasks", lambda repo, proj, ts, a: ran.append([m["id"] for m in ts])), mock.patch.object(fc, "say"):
            fc.cmd_run(a())
            (self.proj / "results" / "run.json").write_text(json.dumps({"pid": 999999, "started_at": "x", "tasks": [t["id"] for t in tasks], "args": {}}))
            fc.cmd_resume(a())
            fc.cmd_run(mock.Mock(repo=str(self.repo), project="p", only=None, redo=True))
        os.environ.pop("FAST_CODING_REDO", None)
        self.assertEqual(ran, [["004", "005"], ["004", "005"], ["001", "003", "004", "005"]])  # Canceled stays out even on --redo
