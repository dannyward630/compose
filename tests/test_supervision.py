import hermetic  # first: no test sees the real home
import contextlib, importlib.machinery, importlib.util, io, json, os, shlex, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)

NOW = 1_800_000_000.0
at = lambda ago: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(NOW - ago))
ORCH = "hw-orchestrator"


class Stalls(unittest.TestCase):
    """Silence with work pending wakes the supervisor once; expected silence (done, waiting on the product owner) never does."""
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()) / "hw"
        (self.proj / "results").mkdir(parents=True)

    def snap(self, tasks=("pending",), crew=None, status="working", last_ago=60, run=False, run_end=0, verify=None):
        return {"tasks": {f"00{i}": {"state": s} for i, s in enumerate(tasks, 1)}, "agents": {ORCH: status},
                "crew": {n: [{"at": at(ago), "state": st, "message": "m"}] for n, (st, ago) in (crew or {}).items()},
                "run": run, "verify": verify, "run_end": run_end, "last": (NOW - last_ago, "teammate x reported working")}

    def stalls(self, snap, now=NOW):
        return fc.fc_watch.watch_stalls(self.proj, snap, 240, now_s=now)

    def test_quiet_project_fires_once(self):
        s = self.snap(crew={ORCH: ("working", 600)}, last_ago=600)
        ev = self.stalls(s)
        self.assertEqual(len(ev), 1)
        self.assertIn("stall=quiet agent=hw-orchestrator", ev[0])
        self.assertIn("herdr agent read hw-orchestrator --lines 60", ev[0])
        self.assertEqual(self.stalls(s), [])  # the same silence does not wake the supervisor again

    def test_a_project_without_a_team_lead_names_none(self):
        s = self.snap(crew={"hw-designer": ("working", 600)}, last_ago=600)
        s["agents"] = {}
        ev = self.stalls(s)
        self.assertEqual(len(ev), 1)
        self.assertIn("stall=quiet nothing moved", ev[0])
        self.assertNotIn("orchestrator", ev[0])
        self.assertIn("no team lead", ev[0])

    def test_the_team_lead_name_is_the_one_crew_start_gives_it(self):
        self.assertEqual(fc.fc_herdr.agent_name("autofill-hifi-design", "orchestrator"), "autofill-hifi-desig-orchestrator")
        self.assertLessEqual(len(fc.fc_herdr.agent_name("autofill-hifi-design", "orchestrator")), 32)

    def test_recent_activity_is_not_a_stall(self):
        self.assertEqual(self.stalls(self.snap(crew={ORCH: ("working", 60)}, last_ago=60)), [])

    def test_done_or_waiting_on_the_product_owner_is_not_a_stall(self):
        self.assertEqual(self.stalls(self.snap(crew={ORCH: ("done", 900)}, last_ago=900)), [])
        self.assertEqual(self.stalls(self.snap(crew={ORCH: ("needs-user", 900)}, last_ago=900)), [])

    def test_test_crews_done_and_nothing_dispatched(self):
        crew = {ORCH: ("working", 100), "hw-tests-001": ("done", 500), "hw-tests-002": ("done", 400)}
        ev = self.stalls(self.snap(crew=crew, last_ago=100))
        self.assertTrue(any("stall=undispatched" in e for e in ev), ev)

    def test_a_teammate_whose_tab_closed_is_not_working(self):
        """tests-002 was collected before its `done` report landed: its last report says working, its tab is closed."""
        s = self.snap(tasks=("passed",), crew={ORCH: ("working", 600), "hw-tests-002": ("working", 600)}, last_ago=600)
        s["closed"] = ["hw-tests-002"]
        self.assertEqual(self.stalls(s), [])
        crew = {ORCH: ("working", 100), "hw-tests-001": ("done", 500), "hw-tests-002": ("working", 400)}
        s = self.snap(crew=crew, last_ago=100); s["closed"] = ["hw-tests-002"]
        ev = self.stalls(s)
        self.assertTrue(any("stall=undispatched" in e and "teammates working none" in e for e in ev), ev)

    def test_run_ended_with_no_next_step(self):
        ev = self.stalls(self.snap(tasks=("passed",), crew={ORCH: ("working", 900)}, last_ago=100, run_end=NOW - 300))
        self.assertTrue(any("stall=no-next-step" in e for e in ev), ev)

    def test_team_lead_idle_with_pending_tasks(self):
        s = self.snap(status="idle", crew={ORCH: ("working", 100)}, last_ago=100)
        self.assertEqual(self.stalls(s, now=NOW), [])  # it just went idle
        ev = self.stalls(s, now=NOW + 300)
        self.assertTrue(any("stall=idle agent=hw-orchestrator" in e for e in ev), ev)

    def test_held_tasks_are_still_work(self):
        s = self.snap(tasks=("held",), status="idle", crew={ORCH: ("working", 600)}, last_ago=600)
        self.assertTrue(any("stall=quiet" in e for e in self.stalls(s)))
        ev = self.stalls(s, now=NOW + 300)
        self.assertTrue(any("stall=idle" in e and "1 task(s) pending" in e for e in ev), ev)

    def test_the_engineering_manager_receives_stalls_and_the_team_lead_too(self):
        ev = ["event stall=quiet agent=hw-orchestrator x", "event crew=hw-tests-001 state=done message='m'",
              "event stall=idle agent=hw-orchestrator the team lead has been idle"]
        self.assertEqual(fc.fc_watch.watch_filter(ev, "hw", [ORCH]), [ev[0], ev[2]])
        self.assertEqual(fc.fc_watch.watch_filter(ev, "hw", []), ev[:2])  # the team lead is idle because it waits on this watch


class WatchTimeout(unittest.TestCase):
    def test_timeout_ends_with_a_state_summary(self):
        snap = {"tasks": {"001": {"state": "pending"}}, "agents": {},
                "crew": {"hw-tests-001": [{"at": time.strftime("%Y-%m-%d %H:%M:%S"), "state": "working", "message": "m"}]},
                "run": False, "verify": None, "run_end": 0, "last": (0, "")}
        a = SimpleNamespace(repo=".", now=False, from_=None, timeout=0.01, interval=0.01, stall=10_000)
        out = []
        with mock.patch.object(fc.fc_core, "project_dir", return_value=Path(tempfile.mkdtemp()) / "hw"), mock.patch.dict(os.environ, {"COMPOSE_ROLE": "orchestrator"}), \
                mock.patch.object(fc.fc_watch, "watch_snapshot", return_value=snap), mock.patch("builtins.print", out.append):
            with self.assertRaises(SystemExit) as e:
                fc.fc_watch.cmd_watch(a)
        self.assertEqual(e.exception.code, 2)
        self.assertIn("event timeout", out[-1])
        self.assertIn("pending tasks 1, teammates working hw-tests-001, run not live, verify not run", out[-1])
        snap["closed"] = ["hw-tests-001"]
        with mock.patch.object(fc.fc_core, "project_dir", return_value=Path(tempfile.mkdtemp()) / "hw"), mock.patch.dict(os.environ, {"COMPOSE_ROLE": "orchestrator"}), \
                mock.patch.object(fc.fc_watch, "watch_snapshot", return_value=snap), mock.patch("builtins.print", out.append):
            with self.assertRaises(SystemExit):
                fc.fc_watch.cmd_watch(a)
        self.assertIn("pending tasks 1, teammates working none,", out[-1])

    def test_the_snapshot_names_teammates_whose_tab_is_closed(self):
        proj = Path(tempfile.mkdtemp()) / "hw"; (proj / "results" / "crew").mkdir(parents=True)
        for n in ("hw-tests-001", "hw-tests-002"):
            (proj / "results" / "crew" / f"{n}.json").write_text(json.dumps({"name": n, "space": "w9"}))
        live = {"agents": [{"name": "hw-tests-001", "workspace_id": "w9", "agent_status": "working"},
                           {"name": "hw-tests-002", "workspace_id": "w1", "agent_status": "working"}]}  # same name, another space
        for answer, closed in ((live, ["hw-tests-002"]), (None, [])):  # herdr cannot say: nobody counts as closed
            with mock.patch.object(fc.fc_herdr, "herdr", return_value=answer), mock.patch.object(fc.fc_tasks, "load_tasks", return_value=[]):
                self.assertEqual(fc.fc_watch.watch_snapshot(Path("."), proj)["closed"], closed)


def wsnap(state="pending", run=False, crashed=False, halt=None):
    return {"tasks": {"001": {"state": state, "attempts": 1, "cost": 0.0, "note": "", "linear": "", "title": "t"}}, "agents": {},
            "crew": {}, "run": run, "crashed": crashed, "verify": None, "halt": halt, "run_end": 0, "last": [0, ""]}


class WatchMemory(unittest.TestCase):
    """Each watcher remembers what it last reported, so what happens while no watch runs is reported by the next one."""
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()) / "hw"

    def watch(self, snap, role=None, **kw):
        a = SimpleNamespace(repo=".", now=False, from_=None, timeout=0.05, interval=0.01, stall=10_000, rewake=False)
        a.__dict__.update(kw)
        out = []
        env = {k: v for k, v in os.environ.items() if k != "COMPOSE_ROLE"} | ({"COMPOSE_ROLE": role} if role is not None else {})
        with mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch.object(fc.fc_watch, "watch_snapshot", return_value=snap), \
                mock.patch("builtins.print", out.append), mock.patch.dict(os.environ, env, clear=True):
            try:
                fc.fc_watch.cmd_watch(a)
            except SystemExit:
                pass
        return out

    def test_a_change_between_two_watches_is_reported_by_the_next(self):
        self.watch(wsnap("running"), now=True)
        out = self.watch(wsnap("passed"))  # the task passed while nobody watched
        self.assertTrue(any("event task=001 state=passed" in line for line in out), out)
        self.assertIn("event timeout", self.watch(wsnap("passed"))[-1])  # reported once, not again

    def test_now_marks_the_current_state_seen(self):
        self.assertTrue(any("task=001 state=passed" in line for line in self.watch(wsnap("passed"), now=True)))
        self.assertIn("event timeout", self.watch(wsnap("passed"))[-1])

    def test_a_wake_passes_its_events_to_the_product_owners_attention(self):
        snap = wsnap(); later = wsnap()
        later["crew"] = {ORCH: [{"at": at(0), "state": "needs-user", "message": "which db?"}]}
        seen = []
        env = {k: v for k, v in os.environ.items() if k != "COMPOSE_ROLE"}  # the engineering manager's watch: no role
        with mock.patch.object(fc.fc_crew, "manager_attention", lambda proj, ev: seen.append(ev)), mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(fc.fc_watch, "watch_snapshot", side_effect=[snap, later, later, later]):
            a = SimpleNamespace(repo=".", now=False, from_="orchestrator", timeout=0.05, interval=0.01, stall=10_000, rewake=False)
            with mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch("builtins.print"):
                with contextlib.suppress(SystemExit):
                    fc.fc_watch.cmd_watch(a)
        self.assertEqual(seen, [[f"event crew={ORCH} state=needs-user message='which db?'"]])

    def test_the_engineering_managers_watch_passes_teammates_it_started_whatever_from_says(self):
        """The one watch (key `manager`, `--from orchestrator` while a team lead is live) also wakes on a planner or designer the
        engineering manager started itself: `crew start` recorded that they report to it. A teammate the team lead started does not."""
        (self.proj / "results" / "crew").mkdir(parents=True)
        for who, up in (("hw-planner", "manager"), ("hw-tests", "orchestrator")):
            (self.proj / "results" / "crew" / f"{who}.json").write_text(json.dumps({"name": who, "role": who[3:], "title": who[3:], "reports_to": up}))
        snap = wsnap(); later = wsnap()
        later["crew"] = {"hw-planner": [{"at": at(0), "state": "needs-user", "message": "3 stories; accept-all"}],
                         "hw-tests": [{"at": at(0), "state": "needs-user", "message": "which fixture?"}]}
        seen = []
        env = {k: v for k, v in os.environ.items() if k != "COMPOSE_ROLE"}
        with mock.patch.object(fc.fc_crew, "manager_attention", lambda proj, ev: seen.append(ev)), \
                mock.patch.object(fc.fc_watch, "watch_snapshot", side_effect=[snap, later, later, later]), mock.patch.dict(os.environ, env, clear=True):
            a = SimpleNamespace(repo=".", now=False, from_="orchestrator", timeout=0.05, interval=0.01, stall=10_000, rewake=False)
            with mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch("builtins.print"):
                with contextlib.suppress(SystemExit):
                    fc.fc_watch.cmd_watch(a)
        self.assertEqual(seen, [["event crew=hw-planner state=needs-user message='3 stories; accept-all'"]])

    def later(self):
        snap = wsnap("passed")
        snap["crew"] = {"hw-x": [{"at": at(0), "state": "tool-bug", "message": "crash"}],
                        "hw-y": [{"at": at(0), "state": "working", "message": "half way"}]}
        return snap

    def test_watches_in_one_role_share_memory_whatever_their_from(self):
        self.watch(wsnap("running"), now=True, role="engineering-manager")
        self.watch(wsnap("running"), now=True, role="engineering-manager", from_="orchestrator")
        self.assertTrue(any("crew=hw-x state=tool-bug" in line for line in self.watch(self.later(), role="engineering-manager")))
        out = self.watch(self.later(), role="engineering-manager", from_="orchestrator")  # already reported in this role
        self.assertFalse(any("crew=hw-x" in line for line in out), out)
        self.assertIn("event timeout", out[-1])

    def test_now_with_from_marks_the_state_seen_for_the_whole_role(self):
        self.watch(wsnap("running"), now=True)
        now = self.watch(self.later(), now=True, from_="orchestrator")
        self.assertFalse(any("crew=hw-y" in line for line in now), now)  # --from still filters what is printed
        self.assertTrue(any("crew=hw-x state=tool-bug" in line for line in now), now)
        self.assertIn("event timeout", self.watch(self.later())[-1])

    def test_each_role_keeps_its_own_memory(self):
        for role in ("orchestrator", "engineering-manager"):
            self.watch(wsnap("running"), now=True, role=role)
        for role in ("orchestrator", "engineering-manager"):
            self.assertTrue(any("crew=hw-x state=tool-bug" in line for line in self.watch(self.later(), role=role)), role)
            self.assertIn("event timeout", self.watch(self.later(), role=role)[-1])

    def test_the_memory_file_is_named_for_the_role(self):
        self.watch(wsnap(), now=True, role="engineering-manager", from_="orchestrator")
        self.watch(wsnap(), now=True)
        self.watch(wsnap(), now=True, role="", from_="x,orchestrator")
        files = sorted(f.name for f in (self.proj / "results").glob("watch-*.json"))
        self.assertEqual(files, ["watch-engineering-manager.json", "watch-manager.json"])

    def test_a_payment_halt_is_an_event(self):
        ev = fc.fc_watch.watch_events(wsnap(run=True), wsnap(halt=["2026-10-11 10:00:00", "openrouter", 2]))
        self.assertTrue(any(e.startswith("event halt=payment provider=openrouter remaining=2") for e in ev), ev)

    def test_a_task_whose_chain_stopped_is_an_event(self):
        ev = fc.fc_watch.watch_events(wsnap(run=True), wsnap("unchained", run=True))
        self.assertTrue(any(e.startswith("event task=001 state=unchained") for e in ev), ev)

    def test_checking_out_the_stack_top_and_back_reports_nothing(self):
        """A task's state is measured against the project branch, not whatever the worktree has checked out: peeking at
        the stack top (where every layer is an ancestor) and coming back must not replay passed and hand_done tasks."""
        repo = Path(tempfile.mkdtemp())
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=repo, check=True, capture_output=True)
        git("init", "-q", "-b", "compose/hw"); git("commit", "-q", "--allow-empty", "-m", "init")
        for tid in ("001", "002"):
            git("checkout", "-q", "-b", f"fast/hw/{tid}"); git("commit", "-q", "--allow-empty", "-m", tid)
        git("checkout", "-q", "compose/hw")
        proj = repo / ".compose" / "hw"; (proj / "results").mkdir(parents=True)
        (proj / "verify.json").write_text("{}")
        (proj / "results" / "tasks.json").write_text(json.dumps({"tasks": [{"id": "001", "title": "a"}, {"id": "002", "title": "b"}]}))
        (proj / "results" / "001.json").write_text(json.dumps({"status": "passed"}))
        (proj / "results" / "002.json").write_text(json.dumps({"status": "hand_done"}))
        snaps = []
        with mock.patch.object(fc.fc_herdr, "herdr", return_value={}):
            for ref in ("compose/hw", "fast/hw/002", "compose/hw"):
                git("checkout", "-q", ref)
                snaps.append(fc.fc_watch.watch_snapshot(repo, proj))
        self.assertEqual({t: v["state"] for t, v in snaps[0]["tasks"].items()}, {"001": "passed", "002": "hand_done"})
        self.assertEqual(fc.fc_watch.watch_events(snaps[0], snaps[1]) + fc.fc_watch.watch_events(snaps[1], snaps[2]), [])

    def test_now_reports_a_crashed_run(self):
        out = self.watch(wsnap("running", crashed=True), now=True)
        self.assertTrue(any("run=ended" in line and "CRASHED" in line for line in out), out)


class Rewake(unittest.TestCase):
    """The team lead's Stop hook: park one watch per turn end, wake the idle session with the event on stderr, exit 2."""
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()) / "hw"
        (self.proj / "results").mkdir(parents=True)
        self.env = {"COMPOSE_ROLE": "orchestrator", "COMPOSE_PROJECT": "hw", "COMPOSE_REPO": "/r", "CLAUDE_CODE_ENTRYPOINT": "cli"}

    def rewake(self, snaps, env=None, session="s1"):
        """The hook reads its JSON from stdin: feed it here, since the real stdin may be a pipe nobody writes to (then the hook waits forever)."""
        err = io.StringIO()
        with mock.patch.dict(os.environ, env or self.env), mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj) as pd, \
                mock.patch.object(fc.fc_watch, "watch_snapshot", side_effect=snaps), mock.patch.object(fc.fc_watch, "WATCH_INTERVAL", 0.01), \
                mock.patch.object(sys, "stdin", io.StringIO(json.dumps({"session_id": session}))), contextlib.redirect_stderr(err):
            try:
                fc.fc_watch.cmd_rewake(SimpleNamespace())
                code = 0
            except SystemExit as e:
                code = e.code
        return code, err.getvalue(), pd

    def test_an_event_wakes_the_session(self):
        code, err, _ = self.rewake([wsnap("running"), wsnap("running"), wsnap("passed")])
        self.assertEqual(code, 2)
        self.assertIn("event task=001 state=passed", err)

    def test_sessions_that_are_not_the_team_lead_return_at_once(self):
        code, err, pd = self.rewake([], env={"COMPOSE_ROLE": "crew", "COMPOSE_PROJECT": "hw"})
        self.assertEqual((code, err), (0, ""))
        pd.assert_not_called()

    def test_a_headless_session_returns_at_once(self):
        code, err, pd = self.rewake([], env={**self.env, "CLAUDE_CODE_ENTRYPOINT": "sdk-cli"})  # what Claude Code sets for `claude -p`
        self.assertEqual((code, err), (0, ""))
        pd.assert_not_called()

    def test_a_wake_carries_the_skill_change_notice(self):
        skill = Path(tempfile.mkdtemp()).resolve()
        (skill / "SKILL.md").write_text("v1\n")
        with mock.patch.object(fc.fc_crew, "SKILL_DIR", skill), mock.patch.object(fc.fc_crew, "SKILL_SEEN", skill / "seen"):
            fc.fc_crew.skill_notice("lead")  # the version the team lead read
            (skill / "SKILL.md").write_text("v2\n")
            code, err, _ = self.rewake([wsnap("running"), wsnap("passed")], session="lead")
        self.assertEqual(code, 2)
        self.assertIn(f"compose's skill changed since you read it: {skill / 'SKILL.md'}", err)

    def test_a_second_hook_leaves_the_parked_one_alone(self):
        held = fc.fc_watch.watch_lock(self.proj, "orchestrator", wait=False)
        self.assertIsNotNone(held)
        code, err, _ = self.rewake([wsnap("passed")])
        self.assertEqual((code, err), (0, ""))
        held.close()


class Reenter(unittest.TestCase):
    """SessionStart hook after a compaction: point a compose teammate back at its brief, the board, and Linear."""
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()) / "hw"
        (self.proj / "results").mkdir(parents=True)
        self.env = {"COMPOSE_ROLE": "tests-021", "COMPOSE_PROJECT": "hw", "COMPOSE_REPO": "/r", "CLAUDE_CODE_ENTRYPOINT": "cli"}

    def reenter(self, env):
        out = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj) as pd, \
                contextlib.redirect_stdout(out):
            fc.fc_watch.cmd_reenter(SimpleNamespace())
        return out.getvalue(), pd

    def test_a_teammate_is_pointed_at_its_brief_the_board_and_linear(self):
        out, _ = self.reenter(self.env)
        self.assertIn(str(self.proj / "results" / "crew" / f"{fc.fc_herdr.agent_name('hw', 'tests-021')}.brief.md"), out)
        self.assertIn("hw-tests-021.brief.md", out)
        self.assertIn("0r", out)
        self.assertIn("compose status --repo /r --project hw", out)
        self.assertIn("compose watch --repo /r --project hw --now", out)
        self.assertIn("Decisions so far", out)
        self.assertIn("Plan", out)

    def test_the_team_lead_gets_the_same_reentry(self):
        out, _ = self.reenter({**self.env, "COMPOSE_ROLE": "orchestrator"})
        self.assertIn("hw-orchestrator.brief.md", out)

    def test_no_role_or_a_headless_session_prints_nothing(self):
        for env in ({k: v for k, v in self.env.items() if k != "COMPOSE_ROLE"}, {**self.env, "CLAUDE_CODE_ENTRYPOINT": "sdk-cli"}):
            out, pd = self.reenter(env)
            self.assertEqual(out, "")
            pd.assert_not_called()

    def test_the_plugin_runs_it_on_a_compaction_and_help_lists_it(self):
        root = Path(fc.__file__).resolve().parents[1]
        hooks = json.loads((root / "hooks" / "hooks.json").read_text())["hooks"]
        cmds = lambda ev, m=None: [h["command"] for e in hooks.get(ev, []) if e.get("matcher") == m for h in e["hooks"]]
        self.assertTrue(any(c.endswith(" reenter") for c in cmds("SessionStart", "compact")), hooks.get("SessionStart"))
        self.assertTrue(cmds("PreToolUse", "Write|Edit|MultiEdit|NotebookEdit")[0].endswith(" guard"))
        self.assertTrue(cmds("PostToolUse", "Skill")[0].endswith(" skillcheck"))
        self.assertTrue(cmds("UserPromptSubmit")[0].endswith(" skillcheck"))
        self.assertTrue(cmds("Stop")[0].endswith(" rewake"))
        help_ = subprocess.run([str(root / "bin" / "compose"), "--help"], capture_output=True, text=True).stdout
        self.assertRegex(help_, r"\breenter\b")


class Detach(unittest.TestCase):
    """run, verify, and resume work in their own session: a closed herdr tab or a dead Claude session ends only the
    follower that streams their log, never the work."""
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.log = self.dir / "run.log"

    def test_the_log_streams_here_and_the_exit_code_comes_back(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = fc.follow([sys.executable, "-c", "print('layer 001 passed'); raise SystemExit(3)"], self.log)
        self.assertEqual(code, 3)
        self.assertIn("layer 001 passed", out.getvalue())
        self.assertIn("layer 001 passed", self.log.read_text())

    def test_a_group_left_with_only_its_zombie_leader_ends_the_follow(self):
        """macOS answers EPERM, not ESRCH, when the work's group has only its zombie leader left: the follow ends with
        the work's exit code instead of crashing on the probe."""
        done, real = Path(f"{self.log}.exit"), os.killpg
        def killpg(group, sig):
            if sig == 0 and done.exists() and done.read_text().strip():
                raise PermissionError(1, "Operation not permitted")
            return real(group, sig)
        out = io.StringIO()
        with mock.patch.object(os, "killpg", killpg), contextlib.redirect_stdout(out):
            code = fc.follow([sys.executable, "-c", "print('layer 001 passed'); raise SystemExit(3)"], self.log)
        self.assertEqual(code, 3)
        self.assertIn("layer 001 passed", out.getvalue())

    def test_the_work_runs_in_its_own_session(self):
        with contextlib.redirect_stdout(io.StringIO()):
            fc.follow([sys.executable, "-c", "import os; print(os.getsid(0))"], self.log)
        self.assertNotEqual(int(self.log.read_text().split()[0]), os.getsid(0))

    def test_a_compose_verify_started_by_a_detached_verify_detaches_too(self):
        """The detach marker is the CLI's own: an e2e driver that runs compose gets a run in its own session, never one in
        the outer verify's process group, where stopping it would stop the outer verify."""
        cli = Path(__file__).resolve().parents[1] / "bin" / "compose.py"
        verify = lambda repo: [sys.executable, str(cli), "verify", "--repo", str(repo), "--project", "p", "--skip-review", "--fix", "0"]
        def repo(driver):
            r = Path(tempfile.mkdtemp())
            for args in (["init", "-q", "-b", "main"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init"]):
                subprocess.run(["git", *args], cwd=r, check=True)
            (r / ".compose" / "p").mkdir(parents=True)
            (r / ".compose" / "p" / "verify.json").write_text(json.dumps({"review": False, "jev_acceptance": False, "e2e_env": {"BU_CDP_URL": "http://127.0.0.1:1", "BU_NAME": "d"},  # no browser
                                                                             "e2e": [{"name": "d", "driver": driver}]}))
            return r
        outer = repo(f"{shlex.join(verify(repo('true')))} > {self.dir}/nested.out 2>&1")
        env = {k: v for k, v in os.environ.items() if k != "COMPOSE_DETACHED"}
        p = subprocess.run(verify(outer), env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("runs in its own session", (self.dir / "nested.out").read_text())

    def test_killing_the_follower_leaves_the_work_running(self):
        done = self.dir / "done"
        started = self.dir / "started"
        work = f"import time; open({str(started)!r}, 'w').write('1'); time.sleep(1.5); open({str(done)!r}, 'w').write('ok')"
        cli = Path(__file__).resolve().parents[1] / "bin" / "compose.py"
        follower = subprocess.Popen([sys.executable, "-c",
            "import importlib.machinery as m, importlib.util as u, sys; "
            f"s = u.spec_from_loader('fc', m.SourceFileLoader('fc', {str(cli)!r})); fc = u.module_from_spec(s); s.loader.exec_module(fc); "
            f"fc.follow([sys.executable, '-c', {work!r}], fc.Path({str(self.log)!r}))"], stdout=subprocess.DEVNULL)
        def wait_for(path):  # generous deadline, polled: a loaded machine can take seconds to start python
            for _ in range(300):
                if path.exists():
                    return
                time.sleep(0.1)
        wait_for(started)  # kill only once the work is running, or the follower may die before it ever spawned it
        def tree(pid):  # what Claude Code does to a background task when its tab closes: the whole process tree
            kids = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True).stdout.split()
            return [pid] + [p for k in kids for p in tree(int(k))]
        for pid in tree(follower.pid):
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass
        follower.wait()
        wait_for(done)
        self.assertEqual(done.read_text(), "ok")

    def test_now_says_a_run_is_live(self):
        proj = Path(tempfile.mkdtemp()) / "hw"
        out = []
        a = SimpleNamespace(repo=".", now=True, from_=None)
        with mock.patch.object(fc.fc_core, "project_dir", return_value=proj), mock.patch.object(fc.fc_watch, "watch_snapshot", return_value=wsnap("running", run=True)), \
                mock.patch("builtins.print", out.append), mock.patch.dict(os.environ, {"COMPOSE_ROLE": "orchestrator"}):
            fc.fc_watch.cmd_watch(a)
        self.assertTrue(any(line.startswith("event run=live") for line in out), out)


class TestHang(unittest.TestCase):
    def test_a_hanging_test_fails_fast_with_a_reason(self):
        import tempfile, time
        t0 = time.time()
        r = fc.fc_implement.run_test({"test": "sleep 30", "test_timeout": "1"}, tempfile.mkdtemp())
        self.assertLess(time.time() - t0, 10)
        self.assertEqual(r.returncode, 124)
        self.assertIn("hangs", r.stderr)


class Timed(unittest.TestCase):
    def test_timed_kills_the_whole_group_and_says_it_hangs(self):
        """The check looks only for this run's sleeps: a suite running at the same time has its own alive, and they are not ours to find."""
        import subprocess as sp, time
        n = 4018 + 2 * os.getpid()  # unique to this run while it lives (another suite's process has another pid), and even
        other = sp.Popen(["sleep", str(n + 1)])  # odd, so never any run's own: stands in for another suite's sleep left alive
        try:
            t0 = time.time()
            r = sp.run([str(Path(__file__).resolve().parents[1] / "bin" / "compose"), "timed", "1", "--", f"sh -c 'sleep {n}' & sleep {n}"],
                       capture_output=True, text=True)
            self.assertEqual(r.returncode, 124)
            self.assertIn("hangs", r.stderr)
            self.assertLess(time.time() - t0, 10)
            time.sleep(0.5)
            self.assertEqual(sp.run(["pgrep", "-f", f"sleep {n}( |$)"], capture_output=True).stdout.strip(), b"")
            self.assertIsNone(other.poll())  # timed killed its own group, nothing outside it
        finally:
            other.kill()
            other.wait()

    def test_timed_runs_several_arguments_as_given_and_one_as_a_shell_line(self):
        import subprocess as sp
        timed = lambda *cmd: sp.run([str(Path(__file__).resolve().parents[1] / "bin" / "compose"), "timed", "30", "--", *cmd],
                                    capture_output=True, text=True)
        r = timed("python3", "-c", "import sys; print(sys.argv[1:])", "a b", "$HOME", "'q'")
        self.assertEqual((r.returncode, r.stdout), (0, "['a b', '$HOME', \"'q'\"]\n"), r.stderr)
        r = timed("echo one && echo two")
        self.assertEqual((r.returncode, r.stdout), (0, "one\ntwo\n"), r.stderr)

    def test_timed_passes_the_callers_stdin_on_but_never_a_terminal(self):
        import pty, subprocess as sp
        cat = lambda **stdin: sp.run([str(Path(__file__).resolve().parents[1] / "bin" / "compose"), "timed", "5", "--", "cat"],
                                     capture_output=True, text=True, **stdin)
        r = cat(input='{"feature": {}}')
        self.assertEqual((r.returncode, r.stdout), (0, '{"feature": {}}'), r.stderr)
        main, term = pty.openpty()
        try:
            r = cat(stdin=term)  # a test reading stdin must not wait on the keyboard until the limit
        finally:
            os.close(main)
            os.close(term)
        self.assertEqual((r.returncode, r.stdout), (0, ""), r.stderr)


class JevLeash(unittest.TestCase):
    def test_a_jev_that_gives_up_is_a_tool_error_not_an_app_failure(self):
        self.assertTrue(fc.fc_jev.tool_error("JEV_GAVE_UP: jev ended blocked after 60 steps\n"))
        self.assertTrue(fc.fc_jev.tool_error("JEV_GAVE_UP: jev did not reach its goal within 150s"))
        self.assertFalse(fc.fc_jev.tool_error("AssertionError: score was 2 of 3"))

    def test_a_jev_case_is_killed_at_its_limit(self):
        with mock.patch.object(fc.fc_config, "JEV_DIR", Path(tempfile.mkdtemp())), \
             mock.patch.object(fc.fc_implement, "timed", return_value=subprocess.CompletedProcess("x", 124, "", "hung")) as t:
            r = fc.fc_jev.jev_e2e({"name": "c", "url": "http://x", "goal": "g", "assert": "true", "timeout": 5}, Path("/tmp"))
        self.assertEqual(t.call_args[0][2], 5)
        self.assertIn("JEV_GAVE_UP", r["stderr"]); self.assertTrue(fc.fc_jev.tool_error(r["stderr"]))


if __name__ == "__main__":
    unittest.main()
