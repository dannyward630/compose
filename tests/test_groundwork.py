import importlib.machinery, importlib.util, io, json, os, subprocess, tempfile, threading, time, unittest
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


class DesignerBrief(unittest.TestCase):
    """The designer's brief names the project, its Figma file, and the tools and gates the designer must use."""
    def setUp(self):
        self.wt = Path(tempfile.mkdtemp()).resolve()
        self.proj = self.wt / ".fast-coding" / "p"
        (self.proj / "results").mkdir(parents=True)
        self.write({"feature": "ENG-1"})

    def write(self, data):
        (self.proj / "linear.json").write_text(json.dumps(data))

    def brief(self, extra=None, figma=None, stdin=""):
        out = io.StringIO()
        with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch.object(fc, "project_worktree", return_value=self.wt), \
                mock.patch.object(fc.sys, "stdin", io.StringIO(stdin)), mock.patch.object(fc, "say"), mock.patch("sys.stdout", out):
            fc.cmd_designer(SimpleNamespace(repo=str(self.wt), project="p", extra=extra, figma=figma))
        return out.getvalue()

    def test_brief_names_the_project_and_the_tools_and_gates(self):
        self.write({"feature": "ENG-1", "figma": "AbCdEf123456"})
        brief = self.brief()
        for text in ("ENG-1", str(self.wt), "AbCdEf123456", "figma:figma-use", "0d", "needs-user", "design-review", "kind: design",
                     "fast-coding frame0 up --project p", "fast-coding figma judge --project p --only NNN", "fast-coding designcrews --project p"):
            self.assertIn(text, brief)
        self.assertNotIn("not set", brief)
        self.assertNotIn("Project notes from the team lead:", brief)

    def test_without_a_stored_key_the_brief_says_to_ask_for_the_file(self):
        self.assertIn("not set: ask the product owner for the Figma file", self.brief())

    def test_figma_url_stores_the_key_before_printing(self):
        self.write({"feature": "ENG-1", "figma": "OldKey000000"})
        brief = self.brief(figma="https://www.figma.com/design/AbCdEf123456/Shop?node-id=1-2")
        self.assertEqual(json.loads((self.proj / "linear.json").read_text()), {"feature": "ENG-1", "figma": "AbCdEf123456"})
        self.assertIn("AbCdEf123456", brief)
        self.assertNotIn("OldKey000000", brief)

    def test_an_unreadable_figma_link_exits_without_storing_or_printing(self):
        with mock.patch.object(fc, "figma_key", return_value=None), mock.patch.object(fc, "store_figma") as store, \
                self.assertRaises(SystemExit) as e:
            self.brief(figma="https://example.com/nope")
        self.assertNotIn(e.exception.code, (0, None))
        store.assert_not_called()
        self.assertEqual(json.loads((self.proj / "linear.json").read_text()), {"feature": "ENG-1"})

    def test_extra_from_stdin_ends_the_brief_under_the_notes_header(self):
        brief = self.brief(extra="-", stdin="Checkout only.\n")
        self.assertIn("Project notes from the team lead:\nCheckout only.", brief)
        self.assertTrue(brief.rstrip().endswith("Checkout only."))


class DesignCrews(unittest.TestCase):
    """designcrews briefs and starts one design-NNN builder per open design task, with the stored Figma key."""
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()).resolve() / ".fast-coding" / "p"
        (self.proj / "results").mkdir(parents=True)
        (self.proj / "linear.json").write_text(json.dumps({"feature": "ENG-1", "figma": "AbCdEf123456"}))
        def issue(n, status="Todo", **kv):
            block = "\n".join(f"{k}: {v}" for k, v in {"id": n, "kind": "design", "test": f"judge {n}", **kv}.items())
            return {"id": f"ENG-{n}", "title": f"Task {n}", "description": f"## Goal\nDraw {n}.\n\n```fast-coding\n{block}\n```\n", "status": status, "blockedBy": []}
        fc.sync_tasks(self.proj, {"feature": {"id": "ENG-1", "title": "F", "description": ""}, "issues": [
            issue("001", nodes="Checkout/Cart, Checkout/Pay"), issue("002", kind="code", files="a.go"), issue("003", "Done", nodes="Home/Hero"),
            issue("004", "In Review", nodes="Home/Nav"), issue("005", nodes="Account/Profile")]})

    def run_crews(self, only=None, print_=False, busy=()):
        started, out = [], io.StringIO()
        def crew(ns):
            started.append(ns)
            if ns.role in busy: raise SystemExit("busy")
        with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch.object(fc, "herdr_space") as space, \
                mock.patch.object(fc, "cmd_crew", side_effect=crew), mock.patch("sys.stdout", out):
            fc.cmd_designcrews(SimpleNamespace(repo=".", project="p", only=only, print_=print_))
        return started, out.getvalue(), space

    def test_print_shows_one_brief_per_open_design_task(self):
        started, out, space = self.run_crews(print_=True)
        for text in ("===== design-001", "===== design-005", "Figma file AbCdEf123456", "Checkout/Cart", "Checkout/Pay", str(self.proj / "results" / "001.tree.txt"), "judge 001", "figma:figma-use", "TASK BRIEF:\nDraw 001."):
            self.assertIn(text, out)
        self.assertEqual((out.count("====="), started, space.call_count), (2, [], 0))

    def test_starts_one_crew_per_open_design_task_and_reports_one_that_fails(self):
        started, out, space = self.run_crews(busy={"design-001"})
        self.assertEqual(sorted(ns.role for ns in started), ["design-001", "design-005"])
        self.assertEqual(space.call_count, 1); self.assertIn("design-001 not started: busy", out)
        ns, meta = next(ns for ns in started if ns.role == "design-005"), fc.load_tasks(self.proj)[-1]
        self.assertEqual((ns.project, ns.action, ns.title, ns.force, ns.cwd, ns.model), ("p", "start", "design 005", False, None, None))
        self.assertEqual(ns.brief, fc.design_brief(meta, "AbCdEf123456", self.proj / "results"))
        self.assertEqual([ns.role for ns in self.run_crews(only="005")[0]], ["design-005"])

    def test_no_stored_figma_key_refuses(self):
        (self.proj / "linear.json").write_text(json.dumps({"feature": "ENG-1"}))
        with self.assertRaises(SystemExit) as e:
            self.run_crews()
        self.assertEqual(str(e.exception), "no Figma file: fast-coding figma check --figma <url or key>")


if __name__ == "__main__":
    unittest.main()
