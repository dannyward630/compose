import importlib.machinery, importlib.util, io, json, os, tempfile, unittest
from pathlib import Path
from unittest import mock

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
        orchestrator_view = fc.watch_filter(ev, "shop", [])  # everything but its own report, which goes up
        self.assertEqual(orchestrator_view, ["event crew=shop-q-neb-12 state=needs-user message='Which payment provider? I recommend Stripe'"])
        first_mate_view = fc.watch_filter(ev, "shop", ["shop-orchestrator"])
        self.assertEqual(first_mate_view, ["event crew=shop-orchestrator state=needs-user message='Tasks are ready for your go'"])
        self.assertEqual(fc.watch_events(snap(self.proj), snap(self.proj)), [])  # nothing new, no event

    def test_bad_state_refused(self):
        with self.assertRaises(SystemExit):
            self.report("shop-q-1", "finished", "x")

    def test_start_opens_tab_starts_claude_and_briefs_it(self):
        calls = []
        def herdr(*args, **kw):
            calls.append(args)
            if args[:2] == ("agent", "get"):
                return None
            if args[:2] == ("tab", "create"):
                return {"tab": {"tab_id": "w9:t3"}, "root_pane": {"pane_id": "w9:p7"}}
            return {}
        a = type("A", (), {"action": "start", "role": "q-NEB-12", "title": "Payment provider", "brief": "Resolve NEB-12 with the captain."})
        with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch.object(fc, "herdr", herdr), \
                mock.patch.object(fc, "herdr_env", return_value=True), mock.patch.object(fc, "herdr_space", return_value="w9"), \
                mock.patch("builtins.print"):
            fc.cmd_crew(a)
        verbs = [c[:2] for c in calls]
        self.assertEqual(verbs, [("agent", "get"), ("tab", "create"), ("agent", "start"), ("pane", "report-metadata"), ("agent", "prompt")])
        self.assertIn("FAST_CODING_ROLE=crew", calls[1])  # only the orchestrator's tab is marked for the guard
        start = calls[2]
        self.assertEqual(start[2], "shop-q-neb-12")
        self.assertIn("claude", start)
        prompt = calls[4][3]
        self.assertIn("fast-coding report", prompt)
        self.assertIn("shop-orchestrator, your orchestrator", prompt)
        self.assertTrue(prompt.endswith("Resolve NEB-12 with the captain."))
        self.assertEqual(fc.crew_reports(self.proj, "shop-q-neb-12")[0]["state"], "working")

    def test_orchestrator_reports_to_first_mate(self):
        self.assertIn("the first mate", fc.crew_preamble(self.proj, "shop-orchestrator", "orchestrator"))

    def test_every_brief_carries_the_commit_and_simplicity_rules(self):
        pre = fc.crew_preamble(self.proj, "shop-tests", "tests")
        self.assertIn("never mention fast-coding", pre)
        self.assertIn("one test file per unit", pre)
        self.assertIn("not even a throwaway reference", pre)

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
    """The CLI, not a session's memory, gets the captain's attention and spreads decisions between question agents."""
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

    def test_done_decision_reaches_open_question_agents_only(self):
        self.report("shop-q-neb-1", "done", "Provider: Stripe (NEB-1)")
        prompted = [c[2] for c in self.calls if c[:2] == ("agent", "prompt")]
        self.assertEqual(prompted, ["shop-q-neb-2"])  # not itself, not the finished q-neb-3, not the tests crew
        self.assertIn("Provider: Stripe (NEB-1)", next(c[3] for c in self.calls if c[:2] == ("agent", "prompt")))
        self.assertNotIn(("notification", "show"), [c[:2] for c in self.calls])

    def test_non_question_done_is_not_broadcast(self):
        self.report("shop-tests", "done", "tests committed")
        self.assertEqual([c for c in self.calls if c[:2] == ("agent", "prompt")], [])

    def test_focus_jumps_on_request(self):
        a = type("A", (), {"action": "focus", "role": "q-neb-2"})
        with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch("builtins.print"), \
                mock.patch.object(fc, "herdr", lambda *args, **kw: self.calls.append(args)):
            fc.cmd_crew(a)
        self.assertEqual(self.calls, [("workspace", "focus", "w9"), ("tab", "focus", "w9:q-neb-2")])


class Guard(unittest.TestCase):
    """The orchestrator writes Linear and the CLI's JSON; code, tests, and docs are crew work."""
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        fc.sh(["git", "init", "-q"], self.repo)
        (self.repo / ".fast-coding" / "shop").mkdir(parents=True)

    def test_orchestrator_cannot_edit_repo_files(self):
        for f in ("src/app.go", "tests/app_test.go", "README.md", "package.json", ".fast-coding/shop/notes.md"):
            self.assertIsNotNone(fc.guard_decision("Edit", str(self.repo / f), "orchestrator"), f)

    def test_orchestrator_keeps_its_own_files(self):
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
