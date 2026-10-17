import importlib.machinery, importlib.util, json, os, tempfile, unittest
from pathlib import Path
from unittest import mock
import sys, time

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast_coding.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)


class AgentNames(unittest.TestCase):
    def test_agent_name(self):
        self.assertEqual(fc.agent_name("custom-dropdowns", "001"), "custom-dropdowns-001")
        self.assertEqual(fc.agent_name("Workday Login!", "012"), "workday-login-012")
        long = fc.agent_name("a" * 40, "003")
        self.assertEqual(len(long), 32)
        self.assertTrue(long.endswith("-003"))
        self.assertTrue(fc.agent_name("9lives", "001").startswith("fc-9lives"))

    def test_herdr_noop_outside(self):
        with mock.patch.dict(os.environ, {"HERDR_ENV": ""}):
            self.assertIsNone(fc.herdr("agent", "list"))

    def test_implementer_routes_headless_outside_herdr(self):
        with mock.patch.dict(os.environ, {"HERDR_ENV": ""}), mock.patch.object(fc, "pi_turn", return_value=("s", "t", 0, {})) as pt:
            fc.implementer("/tmp", "pi:x/y", "hi", None, task={"space": "w9"})
            pt.assert_called_once()


def line(**msg):
    return json.dumps({"type": "message", "message": msg})


class PiSession(unittest.TestCase):
    def test_parse_turns(self):
        f = Path(tempfile.mkdtemp()) / "s.jsonl"
        f.write_text("\n".join([
            json.dumps({"type": "session", "id": "x"}),
            line(role="user", content=[{"type": "text", "text": "do it"}]),
            line(role="assistant", stopReason="toolUse", content=[{"type": "toolCall", "name": "edit"}],
                 usage={"input": 100, "output": 10, "cacheRead": 5, "cacheWrite": 0, "reasoning": 2, "cost": {"total": 0.01}}),
            line(role="toolResult", content=[{"type": "text", "text": "ok"}]),
            line(role="assistant", stopReason="stop", content=[{"type": "text", "text": "done"}],
                 usage={"input": 50, "output": 5, "cacheRead": 0, "cacheWrite": 0, "reasoning": 0, "cost": {"total": 0.002}}),
        ]) + "\n")
        seen, text, tools, usage, errors = fc.parse_pi_session(f, 0)
        self.assertEqual((seen, text, tools, errors), (5, "done", 1, []))
        self.assertEqual((usage["tokens_in"], usage["tokens_out"]), (155, 17))
        self.assertAlmostEqual(usage["cost"], 0.012)
        seen2, text2, tools2, usage2, _ = fc.parse_pi_session(f, seen)
        self.assertEqual((seen2, text2, tools2, usage2["tokens_in"]), (5, "", 0, 0))

    def test_parse_pi_session_error(self):
        f = Path(tempfile.mkdtemp()) / "s.jsonl"
        f.write_text(line(role="assistant", stopReason="error", errorMessage="402 Payment Required: insufficient credits", content=[]) + "\n")
        with self.assertRaises(fc.PaymentRequired):
            fc.parse_pi_session(f, 0)


if __name__ == "__main__":
    unittest.main()


class Watch(unittest.TestCase):
    def snap(self, **tasks):
        return {"tasks": {k: {"state": v, "attempts": 1, "cost": 0.01, "note": "", "linear": "ENG-7", "title": "T"} for k, v in tasks.items()},
                "agents": {}, "run": True, "verify": None}

    def test_task_final_and_running_are_events_attempts_are_not(self):
        a, b = self.snap(**{"001": "running"}), self.snap(**{"001": "passed"})
        ev = fc.watch_events(a, b)
        self.assertEqual(len(ev), 1)
        self.assertIn("task=001 state=passed", ev[0]); self.assertIn("linear=ENG-7", ev[0])
        b["tasks"]["001"]["attempts"] = 2; b["tasks"]["001"]["state"] = "running"
        self.assertEqual(fc.watch_events(self.snap(**{"001": "running"}), b), [])
        self.assertIn("state=running", fc.watch_events(self.snap(**{"001": "pending"}), self.snap(**{"001": "running"}))[0])

    def test_agent_blocked_run_ended_verify(self):
        a, b = self.snap(**{"001": "passed"}), self.snap(**{"001": "passed"})
        b["agents"] = {"demo-001": "blocked"}; b["run"] = False; b["verify"] = (1, True)
        ev = fc.watch_events(a, b)
        self.assertTrue(any("agent=demo-001 status=blocked" in e for e in ev))
        self.assertTrue(any("run=ended passed=1/1" in e for e in ev))
        self.assertTrue(any("verify=PASS" in e for e in ev))
        self.assertEqual(fc.watch_events(b, b), [])

    def test_pid_alive(self):
        self.assertTrue(fc.pid_alive(os.getpid()))
        self.assertFalse(fc.pid_alive(2**22 + 12345))
        self.assertFalse(fc.pid_alive(None))


class Tabs(unittest.TestCase):
    """Implementers share one tab, one pane each; verify reuses one tab. A space never grows a tab per task or per run."""
    def fake(self, tabs, panes):
        calls = []
        def herdr(*args, check=False, timeout=120):
            calls.append(args)
            if args[:2] == ("tab", "list"):
                return {"tabs": [{"label": l, "tab_id": t} for l, t in tabs.items()]}
            if args[:2] == ("pane", "list"):
                return {"panes": panes}
            if args[:2] == ("tab", "create"):
                return {"tab": {"tab_id": "w9:t9"}, "root_pane": {"pane_id": "w9:p1"}}
            if args[:2] == ("pane", "split"):
                return {"pane": {"pane_id": f"w9:p{len(calls)}"}}
        return calls, herdr

    def test_first_implementer_creates_the_tab_later_ones_split_it(self):
        calls, h = self.fake({}, [])
        with mock.patch.object(fc, "herdr", h):
            self.assertEqual(fc.herdr_implementer_pane("w9", "/tmp", {"K": "v"}), "w9:p1")
        self.assertIn("implementers", calls[-1]); self.assertIn("K=v", calls[-1])
        for n, direction in ((1, "right"), (2, "down")):
            panes = [{"pane_id": f"w9:p{i}", "tab_id": "w9:t9"} for i in range(1, n + 1)] + [{"pane_id": "w9:pX", "tab_id": "w9:t1"}]
            calls, h = self.fake({"implementers": "w9:t9"}, panes)
            with mock.patch.object(fc, "herdr", h):
                fc.herdr_implementer_pane("w9", "/tmp", {})
            split = calls[-1]
            self.assertEqual(split[:3], ("pane", "split", f"w9:p{n}"))
            self.assertIn(direction, split)
            self.assertFalse(any(c[:2] == ("tab", "create") for c in calls))

    def test_verify_replaces_its_previous_tab(self):
        calls, h = self.fake({"verify": "w9:t2", "verify 12:10": "w9:t3", "status": "w9:t4"}, [])
        with mock.patch.object(fc, "herdr", h):
            fc.herdr_verify_panes("w9", "/tmp", ["checks"])
        closed = [c[2] for c in calls if c[:2] == ("tab", "close")]
        self.assertEqual(sorted(closed), ["w9:t2", "w9:t3"])


class AgentStartRace(unittest.TestCase):
    def test_a_busy_pane_is_retried_until_it_is_ready(self):
        answers = iter([(None, "agent_pane_busy"), (None, "agent_pane_busy"), ({"agent": {"name": "a"}}, None)])
        with mock.patch.object(fc, "herdr_error", lambda *a, **k: next(answers)), mock.patch.object(time, "sleep"):
            self.assertEqual(fc.herdr_agent_start("a", "--pane", "p1"), {"agent": {"name": "a"}})

    def test_an_unregistered_name_is_retried(self):
        answers = iter([(None, "agent_name_not_found"), ({"agent": {"name": "a"}}, None)])
        with mock.patch.object(fc, "herdr_error", lambda *a, **k: next(answers)), mock.patch.object(time, "sleep"):
            self.assertEqual(fc.herdr_agent_start("a", "--pane", "p1"), {"agent": {"name": "a"}})

    def test_other_errors_and_a_pane_that_never_frees_still_fail(self):
        with mock.patch.object(fc, "herdr_error", return_value=(None, "pane_not_found")) as e, mock.patch.object(time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "pane_not_found"):
                fc.herdr_agent_start("a")
            self.assertEqual(e.call_count, 1)
        with mock.patch.object(fc, "herdr_error", return_value=(None, "agent_pane_busy")) as e, mock.patch.object(time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "agent_pane_busy"):
                fc.herdr_agent_start("a", tries=3)
            self.assertEqual(e.call_count, 3)


class StackLock(unittest.TestCase):
    def test_parallel_linearize_calls_never_overlap(self):
        """Parallel tasks with `after:` all linearize in the one stack worktree; overlapping git there crashed a run."""
        import threading as th
        active, overlaps = [0], []
        def fake(*a):
            active[0] += 1
            if active[0] > 1:
                overlaps.append(1)
            __import__('time').sleep(0.05)
            active[0] -= 1
            return []
        with mock.patch.object(fc, "_linearize", fake):
            ts = [th.Thread(target=fc.linearize, args=(None, None, "t", None)) for _ in range(4)]
            [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(overlaps, [])


class WatchCrash(unittest.TestCase):
    def test_a_dead_run_with_its_marker_left_is_an_ended_run(self):
        proj = Path(tempfile.mkdtemp()); (proj / "results").mkdir()
        (proj / "results" / "run.json").write_text(json.dumps({"pid": 999999}))
        self.assertFalse(fc.run_alive(proj))
        before = {"tasks": {}, "agents": {}, "run": True, "verify": None}
        after = {"tasks": {}, "agents": {}, "run": fc.run_alive(proj), "crashed": True, "verify": None}
        ev = fc.watch_events(before, after)
        self.assertEqual(len(ev), 1); self.assertIn("run=ended", ev[0]); self.assertIn("CRASHED", ev[0])
