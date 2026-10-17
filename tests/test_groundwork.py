import importlib.machinery, importlib.util, io, json, os, re, subprocess, sys, tempfile, threading, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"  # these cover the plain-worktree path; test_treehouse covers the pool

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)


_mcp = mock.patch.object(fc.fc_mcp, "installed_servers", side_effect=lambda cwd: [])  # no test runs the real `claude mcp list`


def setUpModule():
    _mcp.start()


def tearDownModule():
    _mcp.stop()

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
        self.proj = self.repo / ".compose" / "p"
        (self.proj / "results").mkdir(parents=True)
        tasks = [{"id": "001", "title": "Store", "files": ["server/store.go"], "protected": ["server/store_test.go"],
                  "test": "cd server && go test ./... -run TestStore", "body": "## Goal\nOpen the store."},
                 {"id": "002", "title": "Form", "files": ["client/src/Form.js"], "protected": ["client/src/Form.test.js"],
                  "test": "cd client && yarn test Form", "body": "## Goal\nShow the form."}]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))

    def patched(self):
        return (mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch.object(fc.fc_herdr, "project_worktree", return_value=self.repo))

    def test_brief_covers_the_detected_toolchains_and_appends_the_notes(self):
        out = io.StringIO()
        with self.patched()[0], self.patched()[1], mock.patch("sys.stdout", out):
            fc.fc_briefs.cmd_groundwork(SimpleNamespace(repo=str(self.repo), project="p", extra="Stub Open(dsn string) (*sql.DB, error)."))
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
            fc.fc_briefs.cmd_wayfinder(SimpleNamespace(repo=str(self.repo), project="p", extra="Spec: README.md"))
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

    def test_a_test_crew_commits_its_files_as_separate_paths(self):
        brief = fc.fc_briefs.test_brief({"id": "005", "protected": ["tests/test_a.py", "tests/test_b.py"], "test": "true"}, "")
        self.assertIn("Test file: tests/test_a.py, tests/test_b.py.", brief)  # prose keeps the comma list
        self.assertIn("`git add tests/test_a.py tests/test_b.py && git commit tests/test_a.py tests/test_b.py -m", brief)

    def planner(self, issue=None, extra="Spec: README.md", stdin=""):
        (self.proj / "linear.json").write_text(json.dumps({"feature": "NEB-9"}))
        out = io.StringIO()
        with self.patched()[0], self.patched()[1], mock.patch("sys.stdout", out), mock.patch("sys.stdin", io.StringIO(stdin)):
            fc.fc_briefs.cmd_planner(SimpleNamespace(repo=str(self.repo), project="p", issue=issue, extra=extra))
        return out.getvalue()

    def test_planner_brief_names_the_feature_and_routes_every_gap(self):
        brief = self.planner()
        for s in ("NEB-9", str(self.repo), "p-planner", "### Codebase brief", "## Plan", "needs-user", "blocked",
                  "compose sync", "spec-check --project p", "compose tasks", "change start --why", "change done",
                  "crew start --role", "explore", "groundwork", "wayfinder", "Design", "designer"):
            self.assertIn(s, brief)
        runs = [m.start() for m in re.finditer(r"compose run\b", brief)]
        self.assertTrue(runs, "the brief must say the planner never runs `compose run`")
        for i in runs:  # every mention forbids it; none tells the planner to dispatch
            self.assertRegex(brief[max(0, i - 60):i], r"[Nn]ever|[Nn]ot\b|\b[Nn]o\b")
        self.assertTrue(brief.rstrip().endswith("Spec: README.md"))

    def test_planner_issue_overrides_the_feature_and_dash_reads_notes_from_stdin(self):
        brief = self.planner(issue="NEB-12", extra="-", stdin="Story NEB-12 only.\n")
        self.assertIn("NEB-12", brief)
        self.assertTrue(brief.rstrip().endswith("Story NEB-12 only."))
        self.assertNotIn("Project notes", self.planner(extra=None))

    def test_planner_is_a_command_with_issue_and_extra(self):
        cli = str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")
        top = subprocess.run([sys.executable, cli, "--help"], capture_output=True, text=True).stdout
        self.assertRegex(top, r"[{,]planner[,}]")
        sub = subprocess.run([sys.executable, cli, "planner", "--help"], capture_output=True, text=True)
        self.assertEqual(sub.returncode, 0, sub.stderr)
        self.assertIn("--issue", sub.stdout); self.assertIn("--extra", sub.stdout)

    def test_each_test_crew_gets_its_task_and_the_contract(self):
        (self.proj / "results" / "contract.md").write_text("Store is a value type: store.Store{}")
        out = io.StringIO()
        with self.patched()[0], mock.patch("sys.stdout", out):
            fc.fc_briefs.cmd_testcrews(SimpleNamespace(repo=str(self.repo), project="p", contract=None, only="002", print_=True))
        text = out.getvalue()
        self.assertIn("===== tests-002", text); self.assertNotIn("tests-001", text)
        self.assertIn("client/src/Form.test.js", text)
        self.assertIn("Store is a value type", text)
        self.assertIn("## Goal\nShow the form.", text)

    def test_test_crews_commit_only_their_file_and_never_rewrite_the_shared_branch(self):
        (self.proj / "results" / "contract.md").write_text("c")
        out = io.StringIO()
        with self.patched()[0], mock.patch("sys.stdout", out):
            fc.fc_briefs.cmd_testcrews(SimpleNamespace(repo=str(self.repo), project="p", contract=None, only="002", print_=True))
        text = out.getvalue()
        self.assertIn("git add client/src/Form.test.js && git commit client/src/Form.test.js -m", text)
        self.assertIn("Never run `git commit --amend`, `git reset`, `git rebase`", text)

    def test_one_test_crew_failing_to_start_does_not_stop_the_rest(self):
        (self.proj / "results" / "contract.md").write_text("c")
        started, out = [], io.StringIO()
        def crew(ns):
            if ns.role.endswith("001"):
                raise RuntimeError("agent_prompt_stalled")
            started.append(ns.role)
        with self.patched()[0], mock.patch.object(fc.fc_crew, "cmd_crew", crew), mock.patch.object(fc.fc_herdr, "herdr_space"), \
             mock.patch.object(fc.fc_briefs, "test_worktree", lambda proj, tid: self.repo), mock.patch("sys.stdout", out):
            fc.fc_briefs.cmd_testcrews(SimpleNamespace(repo=str(self.repo), project="p", contract=None, only=None, print_=False))
        self.assertEqual(started, ["tests-002"])
        self.assertIn("tests-001 not started: agent_prompt_stalled", out.getvalue())

    def test_a_named_task_that_needs_no_test_writer_says_why(self):
        (self.proj / "results" / "contract.md").write_text("c")
        (self.proj / "results" / "001.json").write_text(json.dumps({"id": "001", "status": "hand_done"}))
        out = io.StringIO()
        with self.patched()[0], mock.patch("sys.stdout", out):
            fc.fc_briefs.cmd_testcrews(SimpleNamespace(repo=str(self.repo), project="p", contract=None, only="001,009", print_=True))
        self.assertIn("001 skipped: its result is hand_done", out.getvalue())
        self.assertIn("009 skipped: no such task", out.getvalue())
        self.assertNotIn("===== tests-001", out.getvalue())

    def test_no_contract_means_no_test_crews(self):
        with self.patched()[0], self.assertRaises(SystemExit):
            fc.fc_briefs.cmd_testcrews(SimpleNamespace(repo=str(self.repo), project="p", contract=None, only=None, print_=True))


class Explore(unittest.TestCase):
    def test_brief_is_graft_only_time_boxed_and_names_the_feature(self):
        proj = Path(tempfile.mkdtemp()) / ".compose" / "p"
        proj.mkdir(parents=True)
        (proj / "linear.json").write_text(json.dumps({"feature": "ENG-7"}))
        out = []
        with mock.patch.object(fc.fc_core, "project_dir", return_value=proj), mock.patch.object(fc.fc_herdr, "project_worktree", return_value=proj.parent.parent), \
                mock.patch("builtins.print", side_effect=lambda s: out.append(s)):
            fc.fc_briefs.cmd_explore(SimpleNamespace(extra="the client lives in web/"))
        brief = out[0]
        for want in ("ENG-7", "graft ask", "graft callers", "under 3 minutes", "at most 40 lines", "patch append", "the client lives in web/"):
            self.assertIn(want, brief)


class Triage(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {**ENV, "TEXT_MODEL_API_KEY": "k"}); self.env.start(); self.addCleanup(self.env.stop)
        self.repo, run = repo_with({"a.go": "a\n", "b.go": "b\n"})
        self.proj = self.repo / ".compose" / "p"
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
        with mock.patch.object(fc.fc_models, "fast_json", fake), mock.patch.object(fc.fc_core, "say"):
            out = fc.fc_run.triage(self.repo, self.proj, ["001", "002"])
        self.assertEqual(peak[0], 2)
        self.assertEqual(out["001"][0], "flag"); self.assertEqual(out["002"][0], "clean")
        self.assertEqual(json.loads((self.proj / "results" / "001.json").read_text())["triage"]["verdict"], "flag")

    def test_a_failed_call_is_unknown_never_a_crash(self):
        with mock.patch.object(fc.fc_models, "fast_json", side_effect=RuntimeError("down")), mock.patch.object(fc.fc_core, "say"):
            out = fc.fc_run.triage(self.repo, self.proj, ["001"])
        self.assertEqual(out["001"][0], "unknown")

    def test_a_reply_that_is_not_a_verdict_object_is_asked_again_then_unknown_with_why(self):
        def replies(*contents):
            calls = []
            def http(req, provider, timeout=90):
                calls.append(json.loads(req.data)["messages"][0]["content"])
                return {"choices": [{"message": {"content": contents[len(calls) - 1]}}]}
            return http, calls
        cut = '{"verdict": "clean", "reason": "the diff only chang'
        for contents, want in ((('["clean"]', '{"verdict": "flag", "reason": "`x := 1`"}'), ("flag", "`x := 1`")),
                               (('[{"verdict": "clean"}]',), ("clean", "")),
                               (('["clean"]', '{"issues": []}'), ("unknown", "triage failed: reply was not a")),
                               ((cut, cut), ("unknown", "triage failed: reply was not valid JSON"))):
            http, calls = replies(*contents)
            with mock.patch.object(fc.fc_models, "http_json", http), mock.patch.object(fc.fc_core, "say"):
                verdict, reason = fc.fc_run.triage(self.repo, self.proj, ["001"])["001"]
            self.assertEqual((verdict, reason[:len(want[1])]), want, contents)
            self.assertEqual(len(calls), len(contents))
            self.assertTrue(len(calls) == 1 or "exactly one JSON object" in calls[1])


class CondenseFailure(unittest.TestCase):
    def test_short_output_keyless_or_failing_calls_add_nothing(self):
        with mock.patch.object(fc.fc_models, "fast_json", side_effect=AssertionError("no call for short output")):
            self.assertEqual(fc.fc_implement.condense_failure("FAIL x"), "")
        long = "noise\n" * 400
        with mock.patch.object(fc.fc_models, "fast_env", return_value={}):
            self.assertEqual(fc.fc_implement.condense_failure(long), "")
        with mock.patch.object(fc.fc_models, "fast_env", return_value={"TEXT_MODEL_API_KEY": "k"}), \
                mock.patch.object(fc.fc_models, "fast_json", side_effect=TimeoutError()):
            self.assertEqual(fc.fc_implement.condense_failure(long), "")
        with mock.patch.object(fc.fc_models, "fast_env", return_value={"TEXT_MODEL_API_KEY": "k"}), \
                mock.patch.object(fc.fc_models, "fast_json", return_value={"summary": "TestScore: want 2, got 1"}):
            self.assertEqual(fc.fc_implement.condense_failure(long), "TestScore: want 2, got 1")


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
            path, branch = fc.fc_crew.crew_workdir(str(self.tool), self.project, "shop-toolsmith")
        self.assertTrue(branch.startswith("shop-toolsmith-"))
        self.assertEqual(path.parent, self.tool.resolve() / ".claude" / "worktrees")
        self.assertTrue((path / "bin" / "tool").exists())
        self.assertEqual(self.tool_git("branch", "--show-current").stdout.strip(), "main")  # the checkout stayed put
        self.assertEqual(self.tool_git("status", "--porcelain").stdout.strip(), "")  # the worktree is excluded, not untracked noise

    def test_the_project_repo_and_plain_folders_run_where_pointed(self):
        self.assertEqual(fc.fc_crew.crew_workdir(str(self.project), self.project, "x"), (self.project, None))
        plain = tempfile.mkdtemp()
        self.assertEqual(fc.fc_crew.crew_workdir(plain, self.project, "x"), (Path(plain), None))
        self.assertEqual(fc.fc_crew.crew_workdir(None, self.project, "x"), (self.project, None))

    def test_an_untrusted_repo_is_named_up_front(self):
        (self.home / ".claude.json").write_text(json.dumps({"projects": {}}))
        with mock.patch.object(Path, "home", return_value=self.home), self.assertRaises(SystemExit) as e:
            fc.fc_crew.crew_workdir(str(self.tool), self.project, "shop-toolsmith")
        self.assertIn("trust", str(e.exception))
        self.assertEqual(self.tool_git("worktree", "list").stdout.count("\n"), 1)  # nothing created


class ClaudeTrust(unittest.TestCase):
    """Claude Code's own rule: a folder in a repo is trusted through the repo's main checkout or a folder between it and the
    repo's top, never through a folder above the repo; outside git any parent counts."""
    def setUp(self):
        self.env = mock.patch.dict(os.environ, ENV); self.env.start(); self.addCleanup(self.env.stop)
        self.home = Path(tempfile.mkdtemp())

    def trusted(self, path, *accepted):
        (self.home / ".claude.json").write_text(json.dumps({"projects": {str(p): {"hasTrustDialogAccepted": True} for p in accepted}}))
        with mock.patch.object(Path, "home", return_value=self.home):
            return fc.fc_claude.claude_trusted(path)

    def test_a_repo_nested_in_a_trusted_folder_still_asks(self):
        outer = Path(tempfile.mkdtemp()).resolve()
        (outer / "repo" / "src").mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(outer / "repo")], check=True)
        (outer / "plain" / "sub").mkdir(parents=True)
        self.assertIs(self.trusted(outer / "repo", outer), False)
        self.assertIs(self.trusted(outer / "repo" / "src", outer), False)
        self.assertIs(self.trusted(outer / "repo" / "src", outer / "repo"), True)
        self.assertIs(self.trusted(outer / "plain" / "sub", outer), True)

    def test_a_worktree_shares_its_main_checkouts_trust(self):
        main, git = repo_with({"src/a.py": ""})
        main, wt = main.resolve(), Path(tempfile.mkdtemp()).resolve() / "wt"
        git("worktree", "add", "-q", str(wt))
        self.assertIs(self.trusted(wt / "src", main), True)
        self.assertIs(self.trusted(wt, main / "src"), False)
        self.assertIs(self.trusted(wt / "src", wt / "src"), True)


class PlannerRules(unittest.TestCase):
    """The planner brief carries the seven-item spec check, its routing, the cutting rules, and the task issue format."""
    def setUp(self):
        env = mock.patch.dict(os.environ, ENV); env.start(); self.addCleanup(env.stop)
        repo, _ = repo_with({"README.md": "x"})
        proj = repo / ".compose" / "p"; proj.mkdir(parents=True)
        (proj / "linear.json").write_text(json.dumps({"feature": "NEB-9"}))
        out = io.StringIO()
        with mock.patch.object(fc.fc_core, "project_dir", return_value=proj), mock.patch.object(fc.fc_herdr, "project_worktree", return_value=repo), mock.patch("sys.stdout", out):
            fc.fc_briefs.cmd_planner(SimpleNamespace(repo=str(repo), project="p", issue=None, extra=""))
        self.brief = out.getvalue()

    def test_the_seven_spec_checks_come_in_numbered_order(self):
        at = -1
        for n, kw in enumerate(("Not yet specified", "### Codebase brief", "traceable", "graft ask", "protected:", "open how", "contract"), 1):
            i = self.brief.find(kw, at + 1)
            self.assertGreater(i, at, f"spec check {n} ({kw}) missing or out of order")
            at = i
        self.assertIn("graft callers", self.brief)
        self.assertIn("as new", self.brief)
        self.assertIn("verify.json", self.brief)

    def test_gaps_are_routed_to_the_chain_or_to_teammates(self):
        for s in ("decision gap", "fact gap", "1, 3, 6", "2, 4, 5"):
            self.assertIn(s, self.brief)

    def test_every_cutting_rule_is_stated(self):
        for s in ("one or two files", "2500", "five", "350", "no documents", "files:", "after:", "blocked-by", "review order", "split"):
            self.assertIn(s, self.brief)

    def test_task_issue_format_lists_sections_and_block_keys(self):
        at = -1
        for sec in ("## Goal", "## Acceptance criteria", "## Test plan", "## Constraints", "```compose"):
            i = self.brief.find(sec, at + 1)
            self.assertGreater(i, at, f"{sec} missing or out of order")
            at = i
        self.assertIn("id, files, protected, test", self.brief)
        self.assertRegex(self.brief, r"(?s)`after`.{0,80}`title`.{0,80}not .{0,20}key|`title`.{0,80}`after`.{0,80}not .{0,20}key")


class DesignerBrief(unittest.TestCase):
    """The designer's brief names the project, its Figma file, and the tools and gates the designer must use."""
    def setUp(self):
        self.wt = Path(tempfile.mkdtemp()).resolve()
        self.proj = self.wt / ".compose" / "p"
        (self.proj / "results").mkdir(parents=True)
        self.write({"feature": "ENG-1"})

    def write(self, data):
        (self.proj / "linear.json").write_text(json.dumps(data))

    def brief(self, extra=None, figma=None, stdin=""):
        out = io.StringIO()
        with mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch.object(fc.fc_herdr, "project_worktree", return_value=self.wt), \
                mock.patch.object(sys, "stdin", io.StringIO(stdin)), mock.patch.object(fc.fc_core, "say"), mock.patch("sys.stdout", out):
            fc.fc_figma.cmd_designer(SimpleNamespace(repo=str(self.wt), project="p", extra=extra, figma=figma))
        return out.getvalue()

    def test_brief_names_the_project_and_the_tools_and_gates(self):
        self.write({"feature": "ENG-1", "figma": "AbCdEf123456"})
        brief = self.brief()
        for text in ("ENG-1", str(self.wt), "AbCdEf123456", "figma:figma-use", "0d", "needs-user", "design-review", "kind: design",
                     "compose frame0 up --project p", "compose figma judge --project p --only NNN", "compose designcrews --project p"):
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
        with mock.patch.object(fc.fc_core, "figma_key", return_value=None), mock.patch.object(fc.fc_figma, "store_figma") as store, \
                self.assertRaises(SystemExit) as e:
            self.brief(figma="https://example.com/nope")
        self.assertNotIn(e.exception.code, (0, None))
        store.assert_not_called()
        self.assertEqual(json.loads((self.proj / "linear.json").read_text()), {"feature": "ENG-1"})

    def test_extra_from_stdin_ends_the_brief_under_the_notes_header(self):
        brief = self.brief(extra="-", stdin="Checkout only.\n")
        self.assertIn("Project notes from the team lead:\nCheckout only.", brief)
        self.assertTrue(brief.rstrip().endswith("Checkout only."))

    def test_brief_splits_figma_writes_from_framelink_reads(self):
        brief = " ".join(self.brief().split())
        for text in ("WRITES ONLY", "never a read-only script", "returns the facts it set", "mcp__framelink-figma__get_figma_data", "download_figma_images",
                     "never `get_screenshot`, `get_metadata`, or `get_design_context`", "Never use `plugin:*figma*`", "compose figma tree --project p --only NNN"):
            self.assertIn(text, brief)

    def test_design_task_nodes_are_page_and_name_pairs_one_page_per_task(self):
        brief = " ".join(self.brief().split())
        step4 = brief[brief.index(" 4. "):brief.index(" 5. ")]
        self.assertIn("A design task carries `kind: design`, `nodes:` (the page and the top-level frames or component sets it may create or touch, "
                      "as <page>/<name>, one page per task), and `test: compose figma judge --project p --only NNN`.", step4)
        self.assertNotIn("node id", brief)
        self.assertEqual(brief.count("<page>/<name>"), 1)


class DesignCrews(unittest.TestCase):
    """designcrews briefs and starts one design-NNN builder per open design task, with the stored Figma key."""
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()).resolve() / ".compose" / "p"
        (self.proj / "results").mkdir(parents=True)
        (self.proj / "linear.json").write_text(json.dumps({"feature": "ENG-1", "figma": "AbCdEf123456"}))
        def issue(n, status="Todo", **kv):
            block = "\n".join(f"{k}: {v}" for k, v in {"id": n, "kind": "design", "test": f"judge {n}", **kv}.items())
            return {"id": f"ENG-{n}", "title": f"Task {n}", "description": f"## Goal\nDraw {n}.\n\n```compose\n{block}\n```\n", "status": status, "blockedBy": []}
        fc.fc_tasks.sync_tasks(self.proj, {"feature": {"id": "ENG-1", "title": "F", "description": ""}, "issues": [
            issue("001", nodes="Checkout/Cart, Checkout/Pay"), issue("002", kind="code", files="a.go"), issue("003", "Done", nodes="Home/Hero"),
            issue("004", "In Review", nodes="Home/Nav"), issue("005", nodes="Account/Profile")]})

    def run_crews(self, only=None, print_=False, busy=(), max=None):
        started, out = [], io.StringIO()
        def crew(ns):
            started.append(ns)
            if ns.role in busy: raise SystemExit("busy")
        with mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch.object(fc.fc_herdr, "herdr_space") as space, \
                mock.patch.object(fc.fc_crew, "cmd_crew", side_effect=crew), mock.patch("sys.stdout", out):
            fc.fc_figma.cmd_designcrews(SimpleNamespace(repo=".", project="p", only=only, print_=print_, max=max))
        return started, out.getvalue(), space

    def test_print_shows_one_brief_per_open_design_task(self):
        started, out, space = self.run_crews(print_=True)
        for text in ("===== design-001", "===== design-005", "Figma file AbCdEf123456", "Checkout/Cart", "Checkout/Pay", str(self.proj / "results" / "001.tree.txt"), "judge 001", "figma:figma-use", "TASK BRIEF:", "## Goal\nDraw 001."):
            self.assertIn(text, out)
        self.assertEqual((out.count("====="), started, space.call_count), (2, [], 0))
        flat = " ".join(out.split())
        for text in ("WRITES ONLY", "mcp__framelink-figma__get_figma_data", "compose figma tree --project p --only 001", "never a read-only `use_figma` script", "Never use `plugin:*figma*`"):
            self.assertIn(text, flat)

    def test_default_pace_is_three_builders_at_once(self):
        def issue(n):
            return {"id": f"ENG-{n}", "title": n, "description": f"```compose\nid: {n}\nkind: design\ntest: t\nnodes: P{n}/A\n```\n", "status": "Todo", "blockedBy": []}
        fc.fc_tasks.sync_tasks(self.proj, {"feature": {"id": "ENG-1", "title": "F", "description": ""}, "issues": [issue(f"10{i}") for i in range(5)]})
        started, out, _ = self.run_crews()
        self.assertEqual((len(started), "queued past the cap of 3" in out), (3, True))

    def test_starts_one_crew_per_open_design_task_and_reports_one_that_fails(self):
        started, out, space = self.run_crews(busy={"design-001"})
        self.assertEqual(sorted(ns.role for ns in started), ["design-001", "design-005"])
        self.assertEqual(space.call_count, 1); self.assertIn("design-001 not started: busy", out)
        ns, meta = next(ns for ns in started if ns.role == "design-005"), fc.fc_tasks.load_tasks(self.proj)[-1]
        self.assertEqual((ns.project, ns.action, ns.title, ns.force, ns.cwd, ns.model), ("p", "start", "design 005", False, None, None))
        self.assertEqual(ns.brief, fc.fc_figma.design_brief(meta, "AbCdEf123456", self.proj / "results"))
        self.assertEqual([ns.role for ns in self.run_crews(only="005")[0]], ["design-005"])

    def test_starts_at_most_the_cap_and_prints_the_rest_with_the_command_to_start_them(self):
        started, out, _ = self.run_crews(max=1)
        self.assertEqual([ns.role for ns in started], ["design-001"])
        self.assertIn("queued past the cap of 1: 005", out)
        self.assertIn("compose designcrews --project p --only 005", out)
        (self.proj / "verify.json").write_text(json.dumps({"design_concurrency": 1}))
        self.assertEqual(len(self.run_crews()[0]), 1)
        self.assertEqual(len(self.run_crews(max=2)[0]), 2)
        (self.proj / "verify.json").unlink()
        started, out, _ = self.run_crews()  # no config: the default of 3 holds both open tasks
        self.assertEqual((len(started), "queued" in out), (2, False))

    def test_a_named_id_that_is_skipped_prints_one_line_with_the_reason(self):
        started, out, _ = self.run_crews(only="003,004,002,099,005", print_=True)
        for line in ("003 skipped: its state is Done", "004 skipped: its state is In Review", "002 skipped: not a design task (kind code)", "099 skipped: no such task"):
            self.assertIn(line, out)
        self.assertEqual((out.count("skipped"), out.count("=====")), (4, 1))
        self.assertNotIn("skipped", self.run_crews(only="005", print_=True)[1])

    def test_a_task_figma_line_names_its_own_file_else_the_stored_key(self):
        def issue(n, **kv):
            block = "\n".join(f"{k}: {v}" for k, v in {"id": n, "kind": "design", "test": "t", "nodes": "P/A", **kv}.items())
            return {"id": f"ENG-{n}", "title": n, "description": f"```compose\n{block}\n```\n", "status": "Todo", "blockedBy": []}
        fc.fc_tasks.sync_tasks(self.proj, {"feature": {"id": "ENG-1", "title": "F", "description": ""}, "issues": [
            issue("123", figma="https://www.figma.com/design/LibKey123456789/Lib?node-id=1-2"), issue("124")]})
        out = self.run_crews(print_=True)[1]
        self.assertEqual((out.count("Figma file LibKey123456789"), out.count("Figma file AbCdEf123456")), (1, 1))
        (self.proj / "linear.json").write_text(json.dumps({"feature": "ENG-1"}))
        self.assertIn("design-123", self.run_crews(only="123", print_=True)[1])  # every task names its file: no stored key needed
        with self.assertRaises(SystemExit):
            self.run_crews(only="124")
        with self.assertRaises(SystemExit) as e:
            fc.fc_tasks.sync_tasks(self.proj, {"feature": {"id": "ENG-1", "title": "F", "description": ""}, "issues": [issue("125", figma="junk")]})
        self.assertIn("figma is not a Figma file url or key: junk", str(e.exception))

    def test_no_stored_figma_key_refuses(self):
        (self.proj / "linear.json").write_text(json.dumps({"feature": "ENG-1"}))
        with self.assertRaises(SystemExit) as e:
            self.run_crews()
        self.assertEqual(str(e.exception), "no Figma file: compose figma check --figma <url or key>")


class ToolsmithBrief(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp()).resolve()
        self.log = self.home / ".compose" / "tool-bugs.jsonl"
        for p in (mock.patch.object(fc.fc_crew, "TOOL_BUGS", self.log),
                  mock.patch.object(fc.fc_config, "CONFIG_PATH", self.home / ".compose" / "config.json"),
                  mock.patch.object(fc.fc_core, "project_dir", return_value=self.home / "shop")):
            p.start(); self.addCleanup(p.stop)

    def entry(self, project, message, **kw):
        self.log.parent.mkdir(parents=True, exist_ok=True)
        with open(self.log, "a") as f:
            f.write(json.dumps({"at": "2026-10-17 15:30:00", "project": project, "reporter": f"{project}-tests", "message": message,
                                "cli_commit": "abc1234", "cli_repo": "/Users/alice9/code/compose", **kw}) + "\n")

    def brief(self, state):
        with mock.patch.object(fc.fc_toolbug, "gh_status", return_value=(state, None if state == "no-gh" else "alice9")) as gh, \
                mock.patch("sys.stdout", io.StringIO()) as out:
            fc.fc_briefs.cmd_toolsmith(SimpleNamespace(repo=".", project="shop"))
        self.assertEqual(gh.call_count, 1)
        return out.getvalue()

    def test_every_variant_carries_the_newest_entry_of_its_project_and_the_filing_steps(self):
        self.entry("shop", "crew start hung at the trust prompt", at="2026-10-17 09:00:00", cli_commit="1111111")
        self.entry("shop", "report crashed with KeyError owner", at="2026-10-17 15:30:00", reporter="shop-impl-002")
        self.entry("other", "other project's newer bug", at="2026-10-18 08:00:00", cli_commit="9999999")
        for state in ("maintainer", "reporter", "no-gh"):
            out = self.brief(state)
            for s in ("report crashed with KeyError owner", "shop-impl-002", "2026-10-17 15:30:00", "abc1234",
                      "SKILL.md", "# <command>: <symptom>", "--comment <n>", "--new"):
                self.assertIn(s, out, state)
            self.assertRegex(out, r"compose tool-bug file --project (shop|<slug>) --body")
            for s in ("sections/", "trust prompt", "1111111", "other project's", "9999999"):
                self.assertNotIn(s, out, state)

    def test_the_maintainers_toolsmith_fixes_on_a_branch_and_never_merges(self):
        self.entry("shop", "report crashed")
        out = self.brief("maintainer")
        for s in ("gh issue comment", "never merge or push", "Fixes #"):
            self.assertIn(s, out)
        self.assertNotIn("never edit or commit", out)

    def test_anyone_elses_toolsmith_only_diagnoses_and_asks_before_filing(self):
        self.entry("shop", "report crashed")
        for state in ("reporter", "no-gh"):
            out = self.brief(state)
            for s in ("never edit or commit", "needs-user", "--approved"):
                self.assertIn(s, out, state)
            self.assertNotIn("never merge or push", out, state)

    def test_no_entry_for_the_project_exits_naming_it(self):
        for setup in (lambda: None, lambda: self.entry("other", "not ours")):
            setup()
            with self.assertRaises(SystemExit) as cm, mock.patch.object(fc.fc_toolbug, "gh_status", return_value=("maintainer", "alice9")):
                fc.fc_briefs.cmd_toolsmith(SimpleNamespace(repo=".", project="shop"))
            self.assertNotIn(cm.exception.code, (0, None))
            self.assertIn("shop", str(cm.exception.code))


if __name__ == "__main__":
    unittest.main()
