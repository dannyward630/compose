import importlib.machinery, importlib.util, json, os, tempfile, unittest
from pathlib import Path
from unittest import mock

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
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
