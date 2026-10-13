import importlib.machinery, importlib.util, io, json, os, re, subprocess, sys, tempfile, threading, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
os.environ["FAST_CODING_NO_TREEHOUSE"] = "1"  # these cover the plain-worktree path; test_treehouse covers the pool

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)

ENV = {"HERDR_ENV": "", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def repo_with(files):
    r = Path(tempfile.mkdtemp())
    run = lambda *a: subprocess.run(["git", *a], cwd=r, check=True, capture_output=True, text=True)
    run("init", "-q", "-b", "main")
    for name, text in files.items():
        (r / name).parent.mkdir(parents=True, exist_ok=True)
        (r / name).write_text(text)
    run("add", "-A"); run("commit", "-qm", "init")
    return r, run


class Groundwork(unittest.TestCase):
    """The groundwork brief is a template; test writers get the task plus the shared contract, never a guess."""
    def setUp(self):
        self.env = mock.patch.dict(os.environ, ENV); self.env.start(); self.addCleanup(self.env.stop)
        self.repo, _ = repo_with({"server/go.mod": "module x\n", "client/package.json": "{}", "client/yarn.lock": ""})
        self.proj = self.repo / ".fast-coding" / "p"
        (self.proj / "results").mkdir(parents=True)
        tasks = [{"id": "001", "title": "Store", "files": ["server/store.go"], "protected": ["server/store_test.go"],
                  "test": "cd server && go test ./... -run TestStore", "body": "## Goal\nOpen the store."},
                 {"id": "002", "title": "Form", "files": ["client/src/Form.js"], "protected": ["client/src/Form.test.js"],
                  "test": "cd client && yarn test Form", "body": "## Goal\nShow the form."}]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))

    def patched(self):
        return (mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch.object(fc, "project_worktree", return_value=self.repo))

    def test_brief_covers_the_detected_toolchains_and_appends_the_notes(self):
        out = io.StringIO()
        with self.patched()[0], self.patched()[1], mock.patch("sys.stdout", out):
            fc.cmd_groundwork(SimpleNamespace(repo=str(self.repo), project="p", extra="Stub Open(dsn string) (*sql.DB, error)."))
        brief = out.getvalue()
        self.assertIn("Go module in server", brief)
        self.assertIn("Node package in client with yarn", brief)
        self.assertIn(str(self.proj / "results" / "contract.md"), brief)
        self.assertIn("$E2E_CLIENT_PORT", brief)
        self.assertTrue(brief.rstrip().endswith("Stub Open(dsn string) (*sql.DB, error)."))

    def test_wayfinder_brief_asks_by_text_and_opens_lavish_only_for_visual_cards(self):
        (self.proj / "linear.json").write_text(json.dumps({"feature": "NEB-9"}))
        out = io.StringIO()
        with self.patched()[0], self.patched()[1], mock.patch("sys.stdout", out):
            fc.cmd_wayfinder(SimpleNamespace(repo=str(self.repo), project="p", extra="Spec: README.md"))
        brief = out.getvalue()
        page = str(self.proj / "lavish" / "wayfinder.html")
        self.assertIn("NEB-9", brief)
        self.assertIn("Text (the default)", brief)
        self.assertIn("Lavish only for a card whose content IS visual", brief)
        self.assertIn("needs-user", brief)
        self.assertIn("before any poll", brief)
        self.assertIn('data-lavish-annotate="off"', brief)
        self.assertIn("data-lavish-question", brief)
        self.assertIn("Answers arrive in the poll's `text`", brief)
        self.assertIn('answer: [{question, answer}, ...]', brief)
        self.assertIn("run it again at once", brief)
        self.assertIn(f"npx -y lavish-axi poll {page}", brief)
        self.assertIn("Decisions so far", brief)
        self.assertTrue(brief.rstrip().endswith("Spec: README.md"))

    def planner(self, issue=None, extra="Spec: README.md", stdin=""):
        (self.proj / "linear.json").write_text(json.dumps({"feature": "NEB-9"}))
        out = io.StringIO()
        with self.patched()[0], self.patched()[1], mock.patch("sys.stdout", out), mock.patch("sys.stdin", io.StringIO(stdin)):
            fc.cmd_planner(SimpleNamespace(repo=str(self.repo), project="p", issue=issue, extra=extra))
        return out.getvalue()

    def test_planner_brief_names_the_feature_and_routes_every_gap(self):
        brief = self.planner()
        for s in ("NEB-9", str(self.repo), "p-planner", "### Codebase brief", "## Plan", "needs-user", "blocked",
                  "fast-coding sync", "spec-check --project p", "fast-coding tasks", "change start --why", "change done",
                  "crew start --role", "explore", "groundwork", "wayfinder", "Design", "designer"):
            self.assertIn(s, brief)
        runs = [m.start() for m in re.finditer(r"fast-coding run\b", brief)]
        self.assertTrue(runs, "the brief must say the planner never runs `fast-coding run`")
        for i in runs:  # every mention forbids it; none tells the planner to dispatch
            self.assertRegex(brief[max(0, i - 60):i], r"[Nn]ever|[Nn]ot\b|\b[Nn]o\b")
        self.assertTrue(brief.rstrip().endswith("Spec: README.md"))

    def test_planner_issue_overrides_the_feature_and_dash_reads_notes_from_stdin(self):
        brief = self.planner(issue="NEB-12", extra="-", stdin="Story NEB-12 only.\n")
        self.assertIn("NEB-12", brief)
        self.assertTrue(brief.rstrip().endswith("Story NEB-12 only."))
        self.assertNotIn("Project notes", self.planner(extra=None))

    def test_planner_is_a_command_with_issue_and_extra(self):
        cli = str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")
        top = subprocess.run([sys.executable, cli, "--help"], capture_output=True, text=True).stdout
        self.assertRegex(top, r"[{,]planner[,}]")
        sub = subprocess.run([sys.executable, cli, "planner", "--help"], capture_output=True, text=True)
        self.assertEqual(sub.returncode, 0, sub.stderr)
        self.assertIn("--issue", sub.stdout); self.assertIn("--extra", sub.stdout)

    def test_each_test_crew_gets_its_task_and_the_contract(self):
        (self.proj / "results" / "contract.md").write_text("Store is a value type: store.Store{}")
        out = io.StringIO()
        with self.patched()[0], mock.patch("sys.stdout", out):
            fc.cmd_testcrews(SimpleNamespace(repo=str(self.repo), project="p", contract=None, only="002", print_=True))
        text = out.getvalue()
        self.assertIn("===== tests-002", text); self.assertNotIn("tests-001", text)
        self.assertIn("client/src/Form.test.js", text)
        self.assertIn("Store is a value type", text)
        self.assertIn("## Goal\nShow the form.", text)

    def test_test_crews_commit_only_their_file_and_never_rewrite_the_shared_branch(self):
        (self.proj / "results" / "contract.md").write_text("c")
        out = io.StringIO()
        with self.patched()[0], mock.patch("sys.stdout", out):
            fc.cmd_testcrews(SimpleNamespace(repo=str(self.repo), project="p", contract=None, only="002", print_=True))
        text = out.getvalue()
        self.assertIn("git add client/src/Form.test.js && git commit client/src/Form.test.js -m", text)
        self.assertIn("Never run `git commit --amend`, `git reset`, `git rebase`", text)

    def test_no_contract_means_no_test_crews(self):
        with self.patched()[0], self.assertRaises(SystemExit):
            fc.cmd_testcrews(SimpleNamespace(repo=str(self.repo), project="p", contract=None, only=None, print_=True))


class Triage(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {**ENV, "TEXT_MODEL_API_KEY": "k"}); self.env.start(); self.addCleanup(self.env.stop)
        self.repo, run = repo_with({"a.go": "a\n", "b.go": "b\n"})
        self.proj = self.repo / ".fast-coding" / "p"
        (self.proj / "results").mkdir(parents=True)
        tasks = []
        for tid, f in (("001", "a.go"), ("002", "b.go")):
            run("checkout", "-q", "-b", f"fast/p/{tid}", "main")
            (self.repo / f).write_text(f"{tid} change\n"); run("commit", "-qam", tid); run("checkout", "-q", "main")
            (self.proj / "results" / f"{tid}.json").write_text(json.dumps({"id": tid, "status": "passed"}))
            tasks.append({"id": tid, "files": [f], "body": "brief"})
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))

    def test_tasks_are_triaged_at_once_and_the_verdict_is_kept(self):
        live, peak, lock = [0], [0], threading.Lock()
        def fake(env, system, user, **kw):
            with lock:
                live[0] += 1; peak[0] = max(peak[0], live[0])
            time.sleep(0.2)
            with lock:
                live[0] -= 1
            return {"verdict": "flag", "reason": "adds a retry flag: `retries := 3`"} if "001 change" in user else {"verdict": "clean"}
        with mock.patch.object(fc, "fast_json", fake), mock.patch.object(fc, "say"):
            out = fc.triage(self.repo, self.proj, ["001", "002"])
        self.assertEqual(peak[0], 2)
        self.assertEqual(out["001"][0], "flag"); self.assertEqual(out["002"][0], "clean")
        self.assertEqual(json.loads((self.proj / "results" / "001.json").read_text())["triage"]["verdict"], "flag")

    def test_a_failed_call_is_unknown_never_a_crash(self):
        with mock.patch.object(fc, "fast_json", side_effect=RuntimeError("down")), mock.patch.object(fc, "say"):
            out = fc.triage(self.repo, self.proj, ["001"])
        self.assertEqual(out["001"][0], "unknown")


class CondenseFailure(unittest.TestCase):
    def test_short_output_keyless_or_failing_calls_add_nothing(self):
        with mock.patch.object(fc, "fast_json", side_effect=AssertionError("no call for short output")):
            self.assertEqual(fc.condense_failure("FAIL x"), "")
        long = "noise\n" * 400
        with mock.patch.object(fc, "fast_env", return_value={}):
            self.assertEqual(fc.condense_failure(long), "")
        with mock.patch.object(fc, "fast_env", return_value={"TEXT_MODEL_API_KEY": "k"}), \
                mock.patch.object(fc, "fast_json", side_effect=TimeoutError()):
            self.assertEqual(fc.condense_failure(long), "")
        with mock.patch.object(fc, "fast_env", return_value={"TEXT_MODEL_API_KEY": "k"}), \
                mock.patch.object(fc, "fast_json", return_value={"summary": "TestScore: want 2, got 1"}):
            self.assertEqual(fc.condense_failure(long), "TestScore: want 2, got 1")


class CrewWorkdir(unittest.TestCase):
    """A teammate pointed at another repo works in its own worktree; the repo's checkout never switches branches."""
    def setUp(self):
        self.env = mock.patch.dict(os.environ, ENV); self.env.start(); self.addCleanup(self.env.stop)
        self.project, _ = repo_with({"README.md": "project\n"})
        self.tool, self.tool_git = repo_with({"bin/tool": "v1\n"})
        self.home = Path(tempfile.mkdtemp())
        trusted = {"projects": {str(self.tool.resolve()): {"hasTrustDialogAccepted": True}}}
        (self.home / ".claude.json").write_text(json.dumps(trusted))

    def test_another_repo_gets_a_worktree_on_a_new_branch(self):
        with mock.patch.object(Path, "home", return_value=self.home):
            path, branch = fc.crew_workdir(str(self.tool), self.project, "shop-toolsmith")
        self.assertTrue(branch.startswith("shop-toolsmith-"))
        self.assertEqual(path.parent, self.tool.resolve() / ".claude" / "worktrees")
        self.assertTrue((path / "bin" / "tool").exists())
        self.assertEqual(self.tool_git("branch", "--show-current").stdout.strip(), "main")  # the checkout stayed put
        self.assertEqual(self.tool_git("status", "--porcelain").stdout.strip(), "")  # the worktree is excluded, not untracked noise

    def test_the_project_repo_and_plain_folders_run_where_pointed(self):
        self.assertEqual(fc.crew_workdir(str(self.project), self.project, "x"), (self.project, None))
        plain = tempfile.mkdtemp()
        self.assertEqual(fc.crew_workdir(plain, self.project, "x"), (Path(plain), None))
        self.assertEqual(fc.crew_workdir(None, self.project, "x"), (self.project, None))

    def test_an_untrusted_repo_is_named_up_front(self):
        (self.home / ".claude.json").write_text(json.dumps({"projects": {}}))
        with mock.patch.object(Path, "home", return_value=self.home), self.assertRaises(SystemExit) as e:
            fc.crew_workdir(str(self.tool), self.project, "shop-toolsmith")
        self.assertIn("trust", str(e.exception))
        self.assertEqual(self.tool_git("worktree", "list").stdout.count("\n"), 1)  # nothing created


if __name__ == "__main__":
    unittest.main()
