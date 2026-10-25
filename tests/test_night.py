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
import fc_nightstate as ns


BIN = Path(__file__).resolve().parents[1] / "bin"


class PlansLanded(unittest.TestCase):
    params = staticmethod(lambda fn: list(inspect.signature(fn).parameters))

    def test_the_seams_of_the_build_loop_exist_as_promised(self):
        self.assertEqual((set(st.PACE), set(ft.IDLE)), ({"day", "night"}, {"day"}))  # night joins PACE when fc_nightstate loads
        self.assertEqual(st.EMPTY["mode"], "day")
        self.assertEqual([self.params(g) for g in (st.pace, st.day_cap)], [["state"]] * 2)
        self.assertEqual(self.params(st.add_event), ["repo", "line"]); self.assertEqual(self.params(st.events_since), ["repo", "n"])
        self.assertEqual(self.params(st.say_once), ["state", "key", "line", "out"])
        self.assertEqual(self.params(ft.turn)[:3], ["repo", "state", "now"]); self.assertEqual(self.params(ft.in_flight), ["plan", "state"])
        self.assertEqual(self.params(ft.offer_day), ["repo", "state", "offer", "now", "out"])
        self.assertEqual(self.params(ft.compose_cli)[:2], ["args", "stdin"]); self.assertEqual(self.params(ft.prompt_lead), ["name", "text"])
        self.assertEqual(self.params(f.run_loop), ["repo", "turns"]); self.assertTrue(callable(f.verb_stop) and callable(f.alive))
        self.assertEqual(set(fc_config.FACTORY_DEFAULTS), {"day_tickets", "turn_seconds", "offer_snooze_minutes", "night_tickets", "night_until", "night_budget", "prep_ahead"})

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


class Limits(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp()).resolve()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

    def make_proj(self, slug):
        (self.repo / ".compose" / slug / "results").mkdir(parents=True)
        (self.repo / ".compose" / slug / "verify.json").write_text("{}")

    def result(self, slug, tid, cost, mtime):
        path = self.repo / ".compose" / slug / "results" / f"{tid}.json"
        path.write_text(json.dumps({"cost": cost})); os.utime(path, (mtime, mtime))

    def test_until_is_the_next_occurrence_and_limits_survive_a_reload(self):
        at = time.mktime((2026, 10, 26, 23, 0, 0, 0, 0, -1))
        self.assertEqual(time.localtime(ns.until_epoch("07:00", at))[:5], (2026, 10, 27, 7, 0))
        self.assertEqual(time.localtime(ns.until_epoch("23:30", at))[:5], (2026, 10, 26, 23, 30))
        s = st.load_state(self.repo); s["mode"] = "night"; s["night"] = ns.new_night(at, ns.until_epoch("07:00", at), 20.0, None)
        st.save_state(self.repo, s)
        self.assertEqual(st.load_state(self.repo)["night"]["budget"], 20.0)
        self.assertEqual(st.load_state(self.repo)["prep"], {})

    def test_spend_counts_task_results_written_since_the_night_began_across_projects(self):
        self.make_proj("sign-in"); self.make_proj("billing")
        self.result("sign-in", "001", 0.40, mtime=50.0); self.result("sign-in", "002", 1.25, mtime=150.0); self.result("billing", "001", 0.75, mtime=200.0)
        self.assertAlmostEqual(ns.night_spend(self.repo, 100.0), 2.0)
        self.result("billing", "002", "nan", mtime=300.0); self.result("billing", "003", "inf", mtime=300.0)
        self.assertAlmostEqual(ns.night_spend(self.repo, 100.0), 2.0)  # a cost that is not a number of dollars counts 0, never disables the budget

    def test_the_night_drains_at_morning_or_at_the_budget_and_the_cap_follows(self):
        n = ns.new_night(0.0, 1000.0, 5.0, None)
        self.assertIsNone(ns.drain_reason(n, 999.0)); self.assertEqual(ns.drain_reason(n, 1000.0), "morning")
        n["spend"] = 5.0; self.assertEqual(ns.drain_reason(n, 10.0), "budget")
        s = {"mode": "night", "night": ns.new_night(0.0, 1000.0, 5.0, None), "day_tickets": None}
        self.assertEqual(st.pace(s), {"mode": "night", "cap": 6})
        for key, value in (("draining", "budget"), ("wait", {"until": 50.0}), ("ended", {"state": "morning"})):
            s["night"] = {**ns.new_night(0.0, 1000.0, 5.0, None), key: value}
            self.assertEqual(ns.night_cap(s), 0)

    def test_notes_are_appended_and_tailed_and_spawn_once_logs_to_compose(self):
        ns.add_note(self.repo, "first"); ns.add_note(self.repo, "second")
        self.assertEqual(ns.notes_tail(self.repo), "first\nsecond\n")
        self.assertEqual(ns.notes_tail(self.repo, 7), "second\n")
        self.assertEqual(ns.notes_path(self.repo).name, "night-notes.md")
        with unittest.mock.patch.object(ns, "subprocess") as sp:  # the module's own name only, so git still runs
            p = sp.Popen; p.return_value.pid = 4242
            self.assertEqual(ns.spawn_once(self.repo, ["status"], "x.log"), 4242)
        self.assertEqual(p.call_args[0][0][1:], [str(BIN / "compose.py"), "status"])
        self.assertTrue(p.call_args[1]["start_new_session"])


class OneLevel(unittest.TestCase):
    @staticmethod
    def feature(ident, state, blockers=()):
        return {"id": ident, "state": state, "stories": [], "blockers": [{"id": i, "state": st, "labels": []} for i, st in blockers]}

    @staticmethod
    def entry(ident, feature):
        return {"id": ident, "title": ident, "state": "Todo", "kind": "story", "feature": feature, "track": "t", "wave": 1, "waits_on": []}

    def chain_plan(self):
        feature = self.feature
        plan = {"features": {"NEB-5": feature("NEB-5", "In Review"), "NEB-9": feature("NEB-9", "Todo", [("NEB-5", "In Review")]),
                             "NEB-12": feature("NEB-12", "In Review", [("NEB-5", "In Review")]),
                             "NEB-20": feature("NEB-20", "Todo", [("NEB-12", "In Review")]), "NEB-30": feature("NEB-30", "Todo", [("NEB-2", "Done")])}}
        plan["features"]["NEB-20"]["stories"] = [{"id": "NEB-22", "state": "Todo"}]
        return plan

    def test_depth_counts_chains_of_verified_unmerged_blockers(self):
        plan = self.chain_plan()
        self.assertEqual([ns.unmerged_depth(plan, f) for f in ("NEB-5", "NEB-9", "NEB-20", "NEB-30")], [0, 1, 2, 0])

    def test_one_level_drops_deeper_entries_unless_in_flight_and_day_keeps_them(self):
        plan, entry = self.chain_plan(), self.entry
        entries = [entry("NEB-10", "NEB-9"), entry("NEB-21", "NEB-20"), entry("NEB-22", "NEB-20")]
        state = {"mode": "night", "dispatched": {"NEB-22": {"feature": "NEB-20"}}}
        self.assertEqual([e["id"] for e in ns.one_level(plan, entries, state)], ["NEB-10", "NEB-22"])
        self.assertEqual(ft.ORDER_FILTER["night"], ns.one_level)
        self.assertNotIn("day", ft.ORDER_FILTER)


if __name__ == "__main__":
    unittest.main()
