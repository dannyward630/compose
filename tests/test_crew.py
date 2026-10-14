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


def setUpModule():  # crew start waits for the agent to be working; a fake herdr answering {} never is, so do not sleep through the wait
    global _sleep
    _sleep = mock.patch.object(fc.time, "sleep")
    _sleep.start()


def tearDownModule():
    _sleep.stop()


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
            if args[:2] == ("agent", "get"):
                return {"agent": {"agent_status": "working"}}
            return {}
        a = type("A", (), {"action": "start", "role": "q-NEB-12", "title": "Payment provider", "brief": "Resolve NEB-12 with the product owner."})
        with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch.object(fc, "herdr", herdr), \
                mock.patch.object(fc, "herdr_env", return_value=True), mock.patch.object(fc, "herdr_space", return_value="w9"), mock.patch.object(fc, "herdr_find_space", return_value="w9"), \
                mock.patch.object(fc, "frame0_register") as frame0, mock.patch.object(fc, "claude_trusted", return_value=True), \
                mock.patch("builtins.print"):
            fc.cmd_crew(a)
        frame0.assert_called_once_with(fc.project_worktree(self.proj), fc.frame0_port(self.proj))  # before the session reads its MCP servers
        verbs = [c[:2] for c in calls]
        self.assertEqual(verbs, [("agent", "list"), ("tab", "create"), ("agent", "start"), ("pane", "report-metadata"), ("agent", "get")])
        self.assertIn("FAST_CODING_ROLE=crew", calls[1])  # only the team lead's tab is marked for the guard
        self.assertIn("FAST_CODING_PROJECT=shop", calls[1])  # the Stop hook's watch finds its project from the tab
        self.assertIn(f"FAST_CODING_REPO={fc.project_worktree(self.proj)}", calls[1])
        start = calls[2]
        self.assertEqual(start[2], "shop-q-neb-12")
        self.assertIn("claude", start)
        self.assertEqual(json.loads(start[start.index("--settings") + 1]), {"attribution": {"commit": "", "pr": ""}})  # no co-author trailer on a crew commit
        sep = start.index("--")
        self.assertIn("brief.md", start[sep + 1])  # the brief is the session's first prompt, passed at launch: no race with a later `herdr agent prompt`
        self.assertNotIn(("agent", "prompt"), [c[:2] for c in calls])
        prompt = (self.proj / "results" / "crew" / "shop-q-neb-12.brief.md").read_text()
        self.assertIn("fast-coding report", prompt)
        self.assertIn("shop-orchestrator, your team lead", prompt)
        self.assertTrue(prompt.endswith("Resolve NEB-12 with the product owner."))
        self.assertEqual(fc.crew_reports(self.proj, "shop-q-neb-12")[0]["state"], "working")

    def test_started_is_written_before_the_agent_can_report(self):
        def herdr(*args, **kw):
            if args[:2] == ("agent", "start"):  # a fast teammate finishes before start returns
                fc.write_report(self.proj, "shop-eol", "done", "one commit")
            if args[:2] == ("agent", "list"):
                return {"agents": []}
            if args[:2] == ("agent", "get"):
                return {"agent": {"agent_status": "working"}}
            return {"tab": {"tab_id": "w9:t3"}, "root_pane": {"pane_id": "w9:p7"}} if args[:2] == ("tab", "create") else {}
        a = type("A", (), {"action": "start", "role": "eol", "title": "eol", "brief": "Do it."})
        with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch.object(fc, "herdr", herdr), \
                mock.patch.object(fc, "herdr_env", return_value=True), mock.patch.object(fc, "herdr_space", return_value="w9"), mock.patch.object(fc, "herdr_find_space", return_value="w9"), \
                mock.patch.object(fc, "frame0_register"), mock.patch.object(fc, "claude_trusted", return_value=True), mock.patch("builtins.print"):
            fc.cmd_crew(a)
        self.assertEqual([r["state"] for r in fc.crew_reports(self.proj, "shop-eol")], ["working", "done"])

    def test_guarded_roles_mark_their_own_tab_and_every_other_role_is_crew(self):
        for role, env in (("planner", "planner"), ("orchestrator", "orchestrator"), ("wayfinder", "crew"), ("q-planner", "crew")):
            calls = []
            def herdr(*args, **kw):
                calls.append(args)
                if args[:2] == ("agent", "list"):
                    return {"agents": []}
                if args[:2] == ("agent", "get"):
                    return {"agent": {"agent_status": "working"}}
                return {"tab": {"tab_id": "w9:t3"}, "root_pane": {"pane_id": "w9:p7"}} if args[:2] == ("tab", "create") else {}
            a = type("A", (), {"action": "start", "role": role, "title": role, "brief": "Plan the feature."})
            with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch.object(fc, "herdr", herdr), \
                    mock.patch.object(fc, "herdr_env", return_value=True), mock.patch.object(fc, "herdr_space", return_value="w9"), mock.patch.object(fc, "herdr_find_space", return_value="w9"), \
                    mock.patch.object(fc, "frame0_register"), mock.patch.object(fc, "claude_trusted", return_value=True), mock.patch("builtins.print"):
                fc.cmd_crew(a)
            self.assertEqual(calls[1][:2], ("tab", "create"))
            self.assertIn(f"FAST_CODING_ROLE={env}", calls[1], role)
            self.assertEqual(calls[2][2], f"shop-{role}")

    def test_same_named_agent_in_another_space_neither_blocks_start_nor_shows_in_list(self):
        stranger = {"name": "shop-explore", "workspace_id": "wC", "agent_status": "idle"}
        calls = []
        def herdr(*args, **kw):
            calls.append(args)
            if args[:2] == ("agent", "list"):
                return {"agents": [stranger]}
            if args[:2] == ("agent", "get"):
                return {"agent": {"agent_status": "working"}}
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

    def test_needs_user_badges_the_pane_without_notifying_or_focusing(self):
        """A teammate's question only badges its pane: the product owner hears of it once, from the engineering manager."""
        self.report("shop-q-neb-1", "needs-user", "Stripe or Adyen?")
        self.assertEqual([c[:2] for c in self.calls], [("pane", "report-metadata")])
        self.assertIn("blocked=needs you", self.calls[0])

    def test_orchestrator_report_does_not_notify_either(self):
        (fc.crew_dir(self.proj) / "shop-orchestrator.json").write_text(json.dumps(
            {"name": "shop-orchestrator", "role": "orchestrator", "title": "orchestrator", "space": "w9", "tab": "w9:o", "pane": "p-o"}))
        self.report("shop-orchestrator", "needs-user", "Stripe or Adyen? I recommend Stripe")
        self.assertEqual([c[:2] for c in self.calls], [("pane", "report-metadata")])

    def test_only_the_engineering_manager_notifies_and_only_on_a_question(self):
        """The notification fires when the report wakes the engineering manager's watch, the one watcher with no crew role."""
        ev = ["event crew=shop-orchestrator state=needs-user message='Stripe or Adyen? I recommend Stripe'",
              "event crew=shop-q-neb-1 state=done message='Provider: Stripe'",
              "event stall=idle agent=shop-orchestrator the team lead has been idle"]
        with mock.patch.object(fc, "herdr", lambda *args, **kw: self.calls.append(args)):
            with mock.patch.dict(os.environ, {"FAST_CODING_ROLE": "orchestrator"}):
                fc.manager_attention(self.proj, ev)  # the team lead watching its teammates
            self.assertEqual(self.calls, [])
            with mock.patch.dict(os.environ, {"FAST_CODING_ROLE": ""}):
                os.environ.pop("FAST_CODING_ROLE")
                fc.manager_attention(self.proj, ev)
        self.assertEqual([c[:2] for c in self.calls], [("notification", "show")])
        self.assertIn("shop: the engineering manager needs you", self.calls[0])
        self.assertIn("Stripe or Adyen? I recommend Stripe  (from shop-orchestrator)", self.calls[0])
        self.assertIn("request", self.calls[0])

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
        for role in ("orchestrator", "planner"):
            self.assertIsNone(fc.guard_decision("Write", str(self.repo / ".fast-coding/shop/scratch/sync.json"), role), role)
        self.assertIsNotNone(fc.guard_decision("Write", str(self.repo / ".fast-coding/shop/scratch.md"), "planner"))
        self.assertIsNone(fc.guard_decision("Write", str(Path(tempfile.mkdtemp()) / "brief.txt"), "orchestrator"))  # scratch outside a repo

    def test_crew_and_unmarked_sessions_are_untouched(self):
        for role in ("crew", None, ""):
            self.assertIsNone(fc.guard_decision("Edit", str(self.repo / "src/app.go"), role))
        self.assertIsNone(fc.guard_decision("Read", str(self.repo / "src/app.go"), "orchestrator"))

    def test_planner_is_guarded_like_the_team_lead(self):
        self.assertEqual(fc.GUARDED_ROLES, ("orchestrator", "planner"))
        self.assertEqual(fc.PLANNING_ROLES, ("wayfinder",))  # the guard change does not touch who gets `planner`
        for tool in fc.GUARDED_TOOLS:
            for role in fc.GUARDED_ROLES:
                why = fc.guard_decision(tool, str(self.repo / "src/app.go"), role) or ""
                self.assertIn("team lead", why, (tool, role))
                self.assertIn("planner", why.lower(), (tool, role))
        for f in (".fast-coding/shop/linear.json", ".fast-coding/shop/verify.json", ".fast-coding/linear.json"):
            self.assertIsNone(fc.guard_decision("Write", str(self.repo / f), "planner"), f)
        self.assertIsNone(fc.guard_decision("Read", str(self.repo / "src/app.go"), "planner"))
        self.assertIsNone(fc.guard_decision("Write", str(Path(tempfile.mkdtemp()) / "plan.md"), "planner"))  # scratch outside a repo
        for role in ("wayfinder", "q-planner", "planners"):  # only the exact guarded roles
            self.assertIsNone(fc.guard_decision("Edit", str(self.repo / "src/app.go"), role), role)

    def test_hook_output_denies(self):
        ev = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(self.repo / "x.go")}})
        for role, denied in (("orchestrator", True), ("planner", True), ("wayfinder", False)):
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"FAST_CODING_ROLE": role}), mock.patch.object(fc.sys, "stdin", io.StringIO(ev)), \
                    mock.patch.object(fc.sys, "stdout", out):
                fc.cmd_guard(None)
            if denied:
                self.assertTrue(out.getvalue(), role)
                self.assertEqual(json.loads(out.getvalue())["hookSpecificOutput"]["permissionDecision"], "deny", role)
            else:
                self.assertEqual(out.getvalue(), "", role)


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
                return {"agent": {"agent_status": "working"}}
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


class ToolsmithWorktree(unittest.TestCase):
    def test_toolsmith_in_the_project_repo_gets_its_own_worktree_and_leaves_checkouts_alone(self):
        def git(*args, cwd):
            return fc.sh(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd).stdout.strip()
        repo = Path(tempfile.mkdtemp()).resolve()
        git("init", "-q", "-b", "main", cwd=repo)
        git("commit", "-q", "--allow-empty", "-m", "init", cwd=repo)
        slot = repo.parent / (repo.name + "-slot")
        git("worktree", "add", "-q", "-b", "fast-coding/shop", str(slot), cwd=repo)
        with mock.patch.object(fc, "claude_trusted", return_value=True):
            path, branch = fc.crew_workdir(str(repo), slot, "shop-toolsmith", "toolsmith")
            same, none = fc.crew_workdir(str(repo), slot, "shop-tests", "tests")
        self.assertTrue(str(path).startswith(str(repo / ".claude" / "worktrees")) and branch)
        self.assertEqual(git("branch", "--show-current", cwd=path), branch)
        self.assertEqual((git("branch", "--show-current", cwd=repo), git("branch", "--show-current", cwd=slot)), ("main", "fast-coding/shop"))
        self.assertEqual((same, none), (Path(repo), None))  # other roles still run where they were pointed


class AwaitStart(unittest.TestCase):
    """The brief is the session's initial prompt, so a prompt sent right after start cannot come first. crew start returns only
    once the agent is working on it, presses Enter if the box kept the text, and names the agent when it never starts."""
    def run_await(self, statuses):
        calls, seen = [], iter(statuses)
        def herdr(*args, check=False, timeout=120):
            calls.append(args)
            return {"agent": {"agent_status": next(seen)}} if args[:2] == ("agent", "get") else {}
        with mock.patch.object(fc, "herdr", herdr), mock.patch.object(fc.time, "sleep"):
            fc.herdr_await_start("shop-tests-003")
        return [c for c in calls if c[:2] == ("agent", "send-keys")]

    def test_a_slow_to_ready_agent_is_waited_for_without_enter(self):
        self.assertEqual(self.run_await(["idle"] * 5 + ["working"]), [])
        self.assertEqual(self.run_await(["done"]), [])

    def test_a_brief_left_in_the_box_is_submitted_with_enter(self):
        self.assertEqual(self.run_await(["idle"] * 10 + ["working"]), [("agent", "send-keys", "shop-tests-003", "enter")])

    def test_a_brief_that_never_starts_fails_loudly_with_the_agent_name(self):
        with self.assertRaises(RuntimeError) as e:
            self.run_await(["idle"] * 100)
        self.assertIn("shop-tests-003 did not start", str(e.exception))


class StartPaneBusy(unittest.TestCase):
    """Teammates started in parallel race each other: a new pane answers agent_pane_busy until its shell is up, which is retried, not a failed start."""
    def run_start(self, busy):
        calls = []
        def herdr(*args, **kw):
            calls.append(args)
            if args[:2] == ("agent", "start") and len([c for c in calls if c[:2] == args[:2]]) <= busy:
                raise RuntimeError("herdr agent start: agent_pane_busy")
            return {}
        with mock.patch.object(fc, "herdr", herdr):
            fc.herdr_start_crew("shop-design-086", "--kind", "claude")
        return len(calls)

    def test_a_busy_pane_is_retried_until_it_starts(self):
        self.assertEqual(self.run_start(busy=3), 4)

    def test_a_name_not_yet_registered_is_retried_like_a_busy_pane(self):
        calls = []
        def herdr(*args, **kw):
            calls.append(args)
            if args[:2] == ("agent", "start") and len(calls) == 1:
                raise RuntimeError("herdr agent start: agent_name_not_found")
            return {"agents": []} if args[:2] == ("agent", "list") else {}
        with mock.patch.object(fc, "herdr", herdr):
            fc.herdr_start_crew("shop-design-086", "--kind", "claude", "--pane", "wJ:p3")
        self.assertEqual([c[:2] for c in calls].count(("agent", "start")), 2)

    def test_a_name_not_found_start_that_made_a_session_names_it_and_never_starts_a_second(self):
        calls = []
        def herdr(*args, **kw):
            calls.append(args)
            if args[:2] == ("agent", "start"):
                raise RuntimeError("herdr agent start: agent_name_not_found")
            return {"agents": [{"name": "claude", "pane_id": "wH:p19"}]} if args[:2] == ("agent", "list") else {}
        with mock.patch.object(fc, "herdr", herdr):
            fc.herdr_start_crew("shop-design-123", "--kind", "claude", "--pane", "wH:p19")
        self.assertEqual([c[:2] for c in calls].count(("agent", "start")), 1)
        self.assertIn(("agent", "rename", "wH:p19", "shop-design-123"), calls)

    def test_a_pane_busy_for_good_fails_loudly(self):
        with self.assertRaisesRegex(RuntimeError, "agent_pane_busy"):
            self.run_start(busy=99)

    def run_timeout(self, live):
        calls = []
        def herdr(*args, **kw):
            calls.append(args)
            if args[:2] == ("agent", "start"):
                raise RuntimeError("herdr agent start: timeout")
            return {"agents": live} if args[:2] == ("agent", "list") else {}
        with mock.patch.object(fc, "herdr", herdr):
            fc.herdr_start_crew("shop-design-086", "--kind", "claude", "--pane", "wJ:p3")
        return calls

    def test_a_start_that_timed_out_but_came_up_is_named_and_kept(self):
        calls = self.run_timeout([{"name": "claude", "pane_id": "wJ:p3"}])
        self.assertIn(("agent", "rename", "wJ:p3", "shop-design-086"), calls)

    def test_a_start_that_timed_out_and_never_came_up_fails_loudly(self):
        with self.assertRaisesRegex(RuntimeError, "timeout"):
            self.run_timeout([])


class AtomicState(unittest.TestCase):
    """A reader of the sync cache sees the old file or the new one, never an empty or partial one; watch retries a transient bad read."""
    def test_a_reader_never_sees_a_partial_write(self):
        import threading
        path = Path(tempfile.mkdtemp()) / "tasks.json"
        fc.atomic_write(path, json.dumps({"n": 0}))
        stop, bad = threading.Event(), []
        def read():
            while not stop.is_set():
                try:
                    json.loads(path.read_text())
                except ValueError as e:
                    bad.append(e)
        t = threading.Thread(target=read); t.start()
        for i in range(300):
            fc.atomic_write(path, json.dumps({"n": i, "pad": "x" * 100000}))
        stop.set(); t.join()
        self.assertEqual(bad, [])
        self.assertEqual([f.name for f in path.parent.iterdir()], ["tasks.json"])  # no temp file left behind

    def test_watch_retries_one_bad_read_of_the_cache(self):
        proj = Path(tempfile.mkdtemp()) / "p"; (proj / "results").mkdir(parents=True)
        reads = iter([json.JSONDecodeError("Expecting value", "", 0), []])
        def load(p, required=False):
            r = next(reads)
            if isinstance(r, Exception):
                raise r
            return r
        with mock.patch.object(fc, "load_tasks", load), mock.patch.object(fc, "herdr", return_value={}):
            self.assertEqual(fc.watch_snapshot(Path("."), proj)["tasks"], {})
