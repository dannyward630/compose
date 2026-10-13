import importlib.machinery, importlib.util, io, json, os, tempfile, unittest
from pathlib import Path
from unittest import mock
os.environ["FAST_CODING_NO_TREEHOUSE"] = "1"  # these cover the plain-worktree path; test_treehouse covers the pool

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)


def snap(proj):
    return {"tasks": {}, "agents": {}, "run": False, "verify": None,
            "crew": {f.stem: fc.crew_reports(proj, f.stem) for f in sorted((proj / "results" / "crew").glob("*.status"))}}


class Crew(unittest.TestCase):
    def setUp(self):
        wt = Path(tempfile.mkdtemp())
        self.proj = wt / ".fast-coding" / "shop"
        self.proj.mkdir(parents=True)

    def report(self, who, state, msg):
        with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch("builtins.print"):
            fc.cmd_report(type("A", (), {"as_": who, "state": state, "message": msg.split()}))

    def test_reports_wake_the_right_watcher(self):
        fc.write_report(self.proj, "shop-q-neb-12", "working", "started")
        fc.write_report(self.proj, "shop-orchestrator", "working", "started")
        before = snap(self.proj)
        self.report("shop-q-neb-12", "needs-user", "Which payment provider? I recommend Stripe")
        self.report("shop-orchestrator", "needs-user", "Tasks are ready for your go")
        ev = fc.watch_events(before, snap(self.proj))
        self.assertEqual(len(ev), 2)
        team_lead_view = fc.watch_filter(ev, "shop", [])  # everything but its own report, which goes up
        self.assertEqual(team_lead_view, ["event crew=shop-q-neb-12 state=needs-user message='Which payment provider? I recommend Stripe'"])
        engineering_manager_view = fc.watch_filter(ev, "shop", ["shop-orchestrator"])
        self.assertEqual(engineering_manager_view, ["event crew=shop-orchestrator state=needs-user message='Tasks are ready for your go'"])
        self.assertEqual(fc.watch_events(snap(self.proj), snap(self.proj)), [])  # nothing new, no event

    def test_bad_state_refused(self):
        with self.assertRaises(SystemExit):
            self.report("shop-q-1", "finished", "x")

    def test_start_opens_tab_starts_claude_and_briefs_it(self):
        calls = []
        def herdr(*args, **kw):
            calls.append(args)
            if args[:2] == ("agent", "list"):
                return {"agents": []}
            if args[:2] == ("tab", "create"):
                return {"tab": {"tab_id": "w9:t3"}, "root_pane": {"pane_id": "w9:p7"}}
            return {}
        a = type("A", (), {"action": "start", "role": "q-NEB-12", "title": "Payment provider", "brief": "Resolve NEB-12 with the product owner."})
        with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch.object(fc, "herdr", herdr), \
                mock.patch.object(fc, "herdr_env", return_value=True), mock.patch.object(fc, "herdr_space", return_value="w9"), mock.patch.object(fc, "herdr_find_space", return_value="w9"), \
                mock.patch.object(fc, "frame0_register") as frame0, mock.patch.object(fc, "claude_trusted", return_value=True), \
                mock.patch("builtins.print"):
            fc.cmd_crew(a)
        frame0.assert_called_once_with(fc.project_worktree(self.proj), fc.frame0_port(self.proj))  # before the session reads its MCP servers
        verbs = [c[:2] for c in calls]
        self.assertEqual(verbs, [("agent", "list"), ("tab", "create"), ("agent", "start"), ("pane", "report-metadata"), ("agent", "prompt")])
        self.assertIn("FAST_CODING_ROLE=crew", calls[1])  # only the team lead's tab is marked for the guard
        self.assertIn("FAST_CODING_PROJECT=shop", calls[1])  # the Stop hook's watch finds its project from the tab
        self.assertIn(f"FAST_CODING_REPO={fc.project_worktree(self.proj)}", calls[1])
        start = calls[2]
        self.assertEqual(start[2], "shop-q-neb-12")
        self.assertIn("claude", start)
        prompt = calls[4][3]
        self.assertIn("fast-coding report", prompt)
        self.assertIn("shop-orchestrator, your team lead", prompt)
        self.assertTrue(prompt.endswith("Resolve NEB-12 with the product owner."))
        self.assertEqual(fc.crew_reports(self.proj, "shop-q-neb-12")[0]["state"], "working")

    def test_same_named_agent_in_another_space_neither_blocks_start_nor_shows_in_list(self):
        stranger = {"name": "shop-explore", "workspace_id": "wC", "agent_status": "idle"}
        calls = []
        def herdr(*args, **kw):
            calls.append(args)
            if args[:2] == ("agent", "list"):
                return {"agents": [stranger]}
            if args[:2] == ("tab", "create"):
                return {"tab": {"tab_id": "w9:t3"}, "root_pane": {"pane_id": "w9:p7"}}
            return {}
        start = type("A", (), {"action": "start", "role": "explore", "title": "Explore", "brief": "Look around."})
        out = io.StringIO()
        with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch.object(fc, "herdr", herdr), \
                mock.patch.object(fc, "herdr_env", return_value=True), mock.patch.object(fc, "herdr_space", return_value="w9"), \
                mock.patch.object(fc, "herdr_find_space", return_value="w9"), mock.patch.object(fc, "frame0_register"), \
                mock.patch.object(fc, "claude_trusted", return_value=True), mock.patch("sys.stdout", out):
            fc.cmd_crew(start)
        self.assertIn("starting this one as shop-explore-2", out.getvalue())
        self.assertEqual(next(c for c in calls if c[:2] == ("agent", "start"))[2], "shop-explore-2")
        self.assertEqual(fc.crew_record(self.proj, "shop-explore")["agent"], "shop-explore-2")
        # the stranger is not the crew: it is not shown as live, the project's own numbered agent is
        mine = {"name": "shop-explore-2", "workspace_id": "w9", "agent_status": "working"}
        for agents, shown in (([stranger], "closed"), ([stranger, mine], "working")):
            out = io.StringIO()
            with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch.object(fc, "herdr", lambda *a, **k: {"agents": agents}), \
                    mock.patch("sys.stdout", out):
                fc.cmd_crew(type("A", (), {"action": "list"}))
            self.assertIn(shown, out.getvalue())
            self.assertNotIn("idle", out.getvalue())

    def test_team_lead_reports_to_engineering_manager(self):
        self.assertIn("the engineering manager", fc.crew_preamble(self.proj, "shop-orchestrator", "orchestrator"))

    def test_every_brief_carries_the_commit_and_simplicity_rules(self):
        pre = fc.crew_preamble(self.proj, "shop-tests", "tests")
        self.assertIn("never mention fast-coding", pre)
        self.assertIn("one test file per unit", pre)
        self.assertIn("not even a throwaway reference", pre)
        self.assertIn("Fact-check before you say it", pre)
        self.assertIn("not verified", pre)

    def test_start_in_an_untrusted_worktree_says_so_before_opening_a_tab(self):
        calls = []
        a = type("A", (), {"action": "start", "role": "orchestrator", "title": None, "brief": "x"})
        with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch.object(fc, "herdr", lambda *x, **k: calls.append(x)), \
                mock.patch.object(fc, "herdr_env", return_value=True), mock.patch.object(fc, "claude_trusted", return_value=False), \
                self.assertRaises(SystemExit) as e:
            fc.cmd_crew(a)
        self.assertIn("never trusted", str(e.exception.code))
        self.assertNotIn(("tab", "create"), [c[:2] for c in calls])  # no half-started tab left behind

    def test_start_outside_herdr_says_so(self):
        a = type("A", (), {"action": "start", "role": "orchestrator", "title": None, "brief": "x"})
        with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch.dict(os.environ, {"HERDR_ENV": ""}), \
                self.assertRaises(SystemExit):
            fc.cmd_crew(a)

    def test_stop_waits_for_done_unless_forced(self):
        (fc.crew_dir(self.proj) / "shop-q-1.json").write_text('{"tab": "w9:t3"}')
        fc.write_report(self.proj, "shop-q-1", "needs-user", "Which one?")
        closed = []
        def stop(force):
            a = type("A", (), {"action": "stop", "role": "q-1", "force": force})
            with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch("builtins.print"), \
                    mock.patch.object(fc, "herdr", lambda *args, **kw: closed.append(args)):
                fc.cmd_crew(a)
        with self.assertRaises(SystemExit) as e:
            stop(False)
        self.assertIn("needs-user", str(e.exception))
        self.assertEqual(closed, [])
        stop(True)
        self.assertEqual(closed, [("tab", "close", "w9:t3")])
        closed.clear()
        fc.write_report(self.proj, "shop-q-1", "done", "Resolved NEB-12")
        stop(False)
        self.assertEqual(closed, [("tab", "close", "w9:t3")])


class Attention(unittest.TestCase):
    """The CLI, not a session's memory, gets the product owner's attention."""
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()) / ".fast-coding" / "shop"
        self.proj.mkdir(parents=True)
        for role, title in (("q-neb-1", "Payment provider"), ("q-neb-2", "Refund window"), ("q-neb-3", "Currency"), ("tests", "tests")):
            name = f"shop-{role}"
            (fc.crew_dir(self.proj) / f"{name}.json").write_text(json.dumps(
                {"name": name, "role": role, "title": title, "space": "w9", "tab": f"w9:{role}", "pane": f"p-{role}"}))
            fc.write_report(self.proj, name, "working", "started")
        fc.write_report(self.proj, "shop-q-neb-3", "done", "Currency: USD only")
        self.calls = []

    def report(self, who, state, msg):
        with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch("builtins.print"), \
                mock.patch.object(fc, "herdr", lambda *args, **kw: self.calls.append(args)):
            fc.cmd_report(type("A", (), {"as_": who, "state": state, "message": msg.split()}))

    def test_needs_user_notifies_and_badges_without_focus(self):
        self.report("shop-q-neb-1", "needs-user", "Stripe or Adyen?")
        verbs = [c[:2] for c in self.calls]
        self.assertEqual(verbs, [("notification", "show"), ("pane", "report-metadata")])
        self.assertIn("Payment provider needs you", self.calls[0])
        self.assertIn("request", self.calls[0])
        self.assertIn("blocked=needs you", self.calls[1])
        self.assertNotIn(("tab", "focus"), verbs)

    def test_done_prompts_no_other_crew(self):
        """Decisions live on the map in Linear, recorded by the one wayfinder teammate; nothing is broadcast between teammates."""
        self.report("shop-q-neb-1", "done", "Provider: Stripe (NEB-1)")
        self.assertEqual([c for c in self.calls if c[:2] == ("agent", "prompt")], [])

    def test_focus_jumps_on_request(self):
        a = type("A", (), {"action": "focus", "role": "q-neb-2"})
        with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch("builtins.print"), \
                mock.patch.object(fc, "herdr", lambda *args, **kw: self.calls.append(args)):
            fc.cmd_crew(a)
        self.assertEqual(self.calls, [("workspace", "focus", "w9"), ("tab", "focus", "w9:q-neb-2")])


class Guard(unittest.TestCase):
    """The team lead writes Linear and the CLI's JSON; code, tests, and docs are teammate work."""
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        fc.sh(["git", "init", "-q"], self.repo)
        (self.repo / ".fast-coding" / "shop").mkdir(parents=True)

    def test_team_lead_cannot_edit_repo_files(self):
        for f in ("src/app.go", "tests/app_test.go", "README.md", "package.json", ".fast-coding/shop/notes.md"):
            self.assertIsNotNone(fc.guard_decision("Edit", str(self.repo / f), "orchestrator"), f)

    def test_team_lead_keeps_its_own_files(self):
        for f in (".fast-coding/shop/linear.json", ".fast-coding/shop/verify.json", ".fast-coding/linear.json"):
            self.assertIsNone(fc.guard_decision("Write", str(self.repo / f), "orchestrator"), f)
        self.assertIsNone(fc.guard_decision("Write", str(Path(tempfile.mkdtemp()) / "brief.txt"), "orchestrator"))  # scratch outside a repo

    def test_crew_and_unmarked_sessions_are_untouched(self):
        for role in ("crew", None, ""):
            self.assertIsNone(fc.guard_decision("Edit", str(self.repo / "src/app.go"), role))
        self.assertIsNone(fc.guard_decision("Read", str(self.repo / "src/app.go"), "orchestrator"))

    def test_hook_output_denies(self):
        ev = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(self.repo / "x.go")}})
        out = io.StringIO()
        with mock.patch.dict(os.environ, {"FAST_CODING_ROLE": "orchestrator"}), mock.patch.object(fc.sys, "stdin", io.StringIO(ev)), \
                mock.patch.object(fc.sys, "stdout", out):
            fc.cmd_guard(None)
        self.assertEqual(json.loads(out.getvalue())["hookSpecificOutput"]["permissionDecision"], "deny")


class ToolBug(unittest.TestCase):
    """A failure of fast-coding itself goes to the engineering manager, who owns fixing the tool, and to a log across projects."""
    setUp, report = Crew.setUp, Crew.report

    def test_tool_bug_is_recorded_logged_and_wakes_the_engineering_manager(self):
        log = Path(tempfile.mkdtemp()) / "tool-bugs.jsonl"
        fc.write_report(self.proj, "shop-tests", "working", "started")
        before = snap(self.proj)
        with mock.patch.object(fc, "TOOL_BUGS", log):
            self.report("shop-tests", "tool-bug", "run crashed on index.lock; worked around with --parallel 1")
        self.assertEqual(fc.crew_reports(self.proj, "shop-tests")[-1]["state"], "tool-bug")
        entry = json.loads(log.read_text().splitlines()[-1])
        self.assertEqual((entry["project"], entry["reporter"]), ("shop", "shop-tests"))
        self.assertTrue(entry["cli_commit"] and Path(entry["cli_repo"], "bin", "fast-coding").exists())
        ev = fc.watch_events(before, snap(self.proj))
        self.assertEqual(len(fc.watch_filter(ev, "shop", ["shop-orchestrator"])), 1)  # the engineering manager wakes on a teammate's tool-bug too
        self.assertEqual(len(fc.watch_filter(ev, "shop", [])), 1)  # and the team lead sees it

    def test_every_brief_says_how_to_report_a_tool_bug(self):
        self.assertIn("tool-bug", fc.crew_preamble(self.proj, "shop-tests", "tests"))

    def test_crew_can_start_in_another_directory(self):
        calls = []
        def herdr(*args, **kw):
            calls.append(args)
            if args[:2] == ("agent", "get"):
                return None
            if args[:2] == ("tab", "create"):
                return {"tab": {"tab_id": "w9:t3"}, "root_pane": {"pane_id": "w9:p7"}}
            return {}
        a = type("A", (), {"action": "start", "role": "toolsmith", "title": "toolsmith", "brief": "Fix it.", "cwd": "/tmp/fast-coding"})
        with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch.object(fc, "herdr", herdr), \
                mock.patch.object(fc, "herdr_env", return_value=True), mock.patch.object(fc, "herdr_space", return_value="w9"), \
                mock.patch.object(fc, "frame0_register"), mock.patch.object(fc, "claude_trusted", return_value=True), mock.patch("builtins.print"):
            fc.cmd_crew(a)
        tab = next(c for c in calls if c[:2] == ("tab", "create"))
        self.assertEqual(tab[tab.index("--cwd") + 1], "/tmp/fast-coding")
