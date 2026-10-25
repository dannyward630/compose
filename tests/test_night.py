import hermetic  # first: no test sees the real home
import inspect, json, os, subprocess, tempfile, time, unittest, unittest.mock
from pathlib import Path
import importlib.machinery, importlib.util, sys
# tests/test_modules.py fails a test file without the next line
os.environ["HERDR_ENV"] = ""
_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_factorystate as st, fc_factoryturn as ft, fc_factory as f
import fc_config, fc_delivery, fc_plan, fc_readiness, fc_claude, fc_change, fc_reconcile


BIN = Path(__file__).resolve().parents[1] / "bin"


class PlansLanded(unittest.TestCase):
    params = staticmethod(lambda fn: list(inspect.signature(fn).parameters))

    def test_the_seams_of_the_build_loop_exist_as_promised(self):
        self.assertEqual((set(st.PACE), set(ft.IDLE)), ({"day"}, {"day"}))
        self.assertEqual(st.EMPTY["mode"], "day")
        self.assertEqual([self.params(g) for g in (st.pace, st.day_cap)], [["state"]] * 2)
        self.assertEqual(self.params(st.add_event), ["repo", "line"]); self.assertEqual(self.params(st.events_since), ["repo", "n"])
        self.assertEqual(self.params(st.say_once), ["state", "key", "line", "out"])
        self.assertEqual(self.params(ft.turn)[:3], ["repo", "state", "now"]); self.assertEqual(self.params(ft.in_flight), ["plan", "state"])
        self.assertEqual(self.params(ft.offer_day), ["repo", "state", "offer", "now", "out"])
        self.assertEqual(self.params(ft.compose_cli)[:2], ["args", "stdin"]); self.assertEqual(self.params(ft.prompt_lead), ["name", "text"])
        self.assertEqual(self.params(f.run_loop), ["repo", "turns"]); self.assertTrue(callable(f.verb_stop) and callable(f.alive))
        self.assertEqual(set(fc_config.FACTORY_DEFAULTS), {"day_tickets", "turn_seconds", "offer_snooze_minutes"})

    def test_the_roadmap_readiness_pause_and_cleanup_interfaces_exist(self):
        self.assertEqual(self.params(fc_delivery.last_reconcile), ["repo"]); self.assertEqual(self.params(fc_delivery.product_plan), ["repo"])
        self.assertEqual(self.params(fc_plan.base_built), ["state", "labels"])
        self.assertEqual(self.params(fc_readiness.story_readiness), ["repo", "story", "refresh", "write"])
        self.assertIn("effort", self.params(fc_claude.claude_json))
        self.assertEqual((self.params(fc_change.rests_on), self.params(fc_change.hold_tasks), self.params(fc_change.paused_tasks)),
                         (["proj", "refs"], ["proj", "ids", "reason"], ["proj"]))
        self.assertEqual(self.params(fc_reconcile.live_leads), ["repo"])
        out = subprocess.run([sys.executable, str(BIN / "compose.py"), "factory", "--help"], capture_output=True, text=True).stdout
        self.assertEqual([v for v in ("start", "stop", "status", "watch", "pace", "plan", "decline", "loop") if v not in out], [])


if __name__ == "__main__":
    unittest.main()
