import hermetic  # first: no test sees the real home
import os, subprocess, tempfile, unittest
from pathlib import Path
import importlib.machinery, importlib.util, sys
# tests/test_modules.py fails a test file without the next line
os.environ["HERDR_ENV"] = ""
_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_factorystate as st


class State(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        self.repo = Path(d.name).resolve()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

    def test_state_round_trips_and_events_are_numbered(self):
        self.assertEqual(st.load_state(self.repo), st.EMPTY)
        s = st.load_state(self.repo); s["dispatched"]["NEB-10"] = {"feature": "NEB-9"}; st.save_state(self.repo, s)
        self.assertEqual(st.load_state(self.repo)["dispatched"], {"NEB-10": {"feature": "NEB-9"}})
        self.assertEqual(st.state_path(self.repo), self.repo / ".compose" / "factory.json")
        self.assertEqual([st.add_event(self.repo, f"event factory=x n={i}") for i in range(3)], [1, 2, 3])
        self.assertEqual([e["line"] for e in st.events_since(self.repo, 1)], ["event factory=x n=1", "event factory=x n=2"])

    def test_unreadable_state_reads_as_empty(self):
        st.state_path(self.repo).parent.mkdir(exist_ok=True); st.state_path(self.repo).write_text("{not json")
        self.assertEqual(st.load_state(self.repo), st.EMPTY)

    def test_saved_values_of_the_wrong_type_are_ignored(self):
        st.state_path(self.repo).parent.mkdir(exist_ok=True)
        st.state_path(self.repo).write_text('{"dispatched": null, "said": [], "mode": ["x"], "day_tickets": 3, "pid": 7}')
        s = st.load_state(self.repo)
        self.assertEqual((s["dispatched"], s["said"], s["mode"], s["day_tickets"], s["pid"]), ({}, {}, "day", 3, 7))
        st.state_path(self.repo).write_text("[1]")
        self.assertEqual(st.load_state(self.repo), st.EMPTY)

    def test_corrupt_event_lines_are_skipped_and_a_torn_line_is_not_glued_onto(self):
        st.events_path(self.repo).parent.mkdir(exist_ok=True)
        good = '{"n": 4, "at": 1.0, "line": "kept"}'
        st.events_path(self.repo).write_text("null\n[]\n{}\n" + '{"x":1}\n' + good + '\n{"n": 9, "at"')
        self.assertEqual([e["n"] for e in st.events_since(self.repo, 0)], [4])
        self.assertEqual(st.add_event(self.repo, "next"), 5)
        self.assertEqual([e["line"] for e in st.events_since(self.repo, 4)], ["next"])

    def test_day_pace_is_the_repos_setting_else_the_config(self):
        s = st.load_state(self.repo); self.assertEqual(st.pace(s), {"mode": "day", "cap": 2})
        s["day_tickets"] = 1; self.assertEqual(st.pace(s), {"mode": "day", "cap": 1})

    def test_say_once_repeats_nothing_until_the_line_changes(self):
        s, out = st.load_state(self.repo), []
        for line in ("a", "a", "b"): st.say_once(s, "k", line, out)
        self.assertEqual(out, ["a", "b"])


import fc_factoryturn as ft


def story(id, state="Todo", *labels):
    return {"id": id, "title": id, "state": state, "labels": list(labels)}

def plan_of(**features):
    return {"features": {k.replace("_", "-"): {"id": k.replace("_", "-"), "stories": v} for k, v in features.items()}}

def entry(id, feature, kind="story", state="Todo", waits_on=()):
    return {"id": id, "title": id, "state": state, "kind": kind, "feature": feature, "track": "t", "wave": 1, "waits_on": list(waits_on)}

def rd(id, ready=True, has_tasks=True, specced=True, missing=(), error=None):
    return {"id": id, "ready": ready, "has_tasks": has_tasks, "specced": specced, "missing": list(missing), "error": error}

def judge(results):
    return lambda repo, s, **kw: results[s]


class Pick(unittest.TestCase):
    def test_build_needs_ready_tasks_and_the_label_and_cut_needs_no_needs_shaping(self):
        self.assertEqual(ft.classify(["Story", "Ready"], rd("A")), "build")
        self.assertIsNone(ft.classify(["Story"], rd("A")))  # tasks but no Ready: another gate holds it
        self.assertEqual(ft.classify(["Story"], rd("A", has_tasks=False)), "cut")
        self.assertIsNone(ft.classify(["Story", "needs-shaping"], rd("A", has_tasks=False)))
        self.assertIsNone(ft.classify(["Story", "Ready"], rd("A", ready=False)))

    def test_in_flight_counts_hand_started_stories_and_frees_in_review(self):
        plan = plan_of(NEB_9=[story("NEB-10", "In Progress"), story("NEB-11"), story("NEB-13", "In Review")])
        self.assertEqual(ft.in_flight(plan, {"dispatched": {"NEB-11": {}, "NEB-13": {}}}), ["NEB-10", "NEB-11"])

    def test_pick_fills_free_slots_in_order_and_starts_nothing_without_one(self):
        plan = plan_of(NEB_9=[story("NEB-10", "Todo", "Ready"), story("NEB-11", "Todo", "Ready"), story("NEB-14", "In Progress")])
        entries = [entry("NEB-14", "NEB-9", state="In Progress"), entry("NEB-10", "NEB-9"), entry("NEB-11", "NEB-9"),
                   entry("NEB-20", "NEB-12", waits_on=("NEB-9",))]
        j = judge({"NEB-10": rd("NEB-10"), "NEB-11": rd("NEB-11")})
        out = ft.pick(entries, plan, {"dispatched": {}}, 1, j)
        self.assertEqual(([(e["id"], k) for e, k in out["picks"]], out["ready_waiting"], out["offer"]), ([("NEB-10", "build")], True, None))
        self.assertEqual(ft.pick(entries, plan, {"dispatched": {}}, 0, j)["picks"], [])

    def test_nothing_dispatchable_offers_the_first_entry_that_needs_planning(self):
        missing = [{"item": "scope", "issue": "NEB-10", "question": "What is out?"}]
        out = ft.pick([entry("NEB-10", "NEB-9"), entry("NEB-12", "NEB-12", kind="feature")], plan_of(NEB_9=[story("NEB-10")]),
                      {"dispatched": {}}, 2, judge({"NEB-10": rd("NEB-10", ready=False, specced=False, missing=missing)}))
        self.assertEqual(out["offer"], {"id": "NEB-10", "layer": "story", "why": "scope: What is out?"})
        out = ft.pick([entry("NEB-12", "NEB-12", kind="feature")], plan_of(), {"dispatched": {}}, 2, judge({}))
        self.assertEqual(out["offer"], {"id": "NEB-12", "layer": "stories", "why": "no stories yet"})

    def test_a_failed_judge_is_reported_never_offered_and_judging_stops_at_the_limit(self):
        out = ft.pick([entry("NEB-10", "NEB-9")], plan_of(NEB_9=[story("NEB-10", "Todo", "Ready")]), {"dispatched": {}}, 2,
                      judge({"NEB-10": rd("NEB-10", ready=False, specced=None, error="no TypeSafe key")}))
        self.assertEqual((out["picks"], out["offer"], out["failed"]), ([], None, [("NEB-10", "no TypeSafe key")]))
        calls, entries = [], [entry(f"NEB-{n}", "NEB-9") for n in range(30, 40)]
        ft.pick(entries, plan_of(NEB_9=[story(e["id"]) for e in entries]), {"dispatched": {}}, 2,
                lambda repo, s, **kw: calls.append(s) or rd(s, ready=False, specced=False))
        self.assertLessEqual(len(calls), ft.JUDGE_LIMIT)


if __name__ == "__main__":
    unittest.main()
