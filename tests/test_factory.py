import hermetic  # first: no test sees the real home
import json, os, subprocess, tempfile, unittest, unittest.mock
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
    return lambda s, **kw: results[s]


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

    def test_pick_calls_the_judge_with_the_id_alone_so_the_caller_binds_the_repo(self):
        seen = []
        def j(s, **kw):
            seen.append((s, kw)); return rd(s)
        out = ft.pick([entry("NEB-10", "NEB-9")], plan_of(NEB_9=[story("NEB-10", "Todo", "Ready")]), {"dispatched": {}}, 1, j)
        self.assertEqual((seen, len(out["picks"])), ([("NEB-10", {"write": True})], 1))

    def test_a_failed_judge_is_reported_never_offered_and_judging_stops_at_the_limit(self):
        out = ft.pick([entry("NEB-10", "NEB-9")], plan_of(NEB_9=[story("NEB-10", "Todo", "Ready")]), {"dispatched": {}}, 2,
                      judge({"NEB-10": rd("NEB-10", ready=False, specced=None, error="no TypeSafe key")}))
        self.assertEqual((out["picks"], out["offer"], out["failed"]), ([], None, [("NEB-10", "no TypeSafe key")]))
        calls, entries = [], [entry(f"NEB-{n}", "NEB-9") for n in range(30, 40)]
        ft.pick(entries, plan_of(NEB_9=[story(e["id"]) for e in entries]), {"dispatched": {}}, 2,
                lambda s, **kw: calls.append(s) or rd(s, ready=False, specced=False))
        self.assertLessEqual(len(calls), ft.JUDGE_LIMIT)


class Dispatch(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        self.repo = Path(d.name).resolve() / "repo"; self.wt = Path(d.name).resolve() / "compose-sign-in"
        self.repo.mkdir(); self.projects, self.leads, self.state = {}, {}, {"dispatched": {}}
        self.plan = plan_of(NEB_9=[story("NEB-10"), story("NEB-11"), story("NEB-12")])
        self.plan["features"]["NEB-9"].update(title="Sign in", blockers=[])
        self.proj = self.wt / ".compose" / "sign-in"
        for name, new in (("all_projects", lambda repo: dict(self.projects)), ("live_leads", lambda repo: dict(self.leads))):
            mod = ft.fc_core if name == "all_projects" else ft.fc_reconcile
            pa = unittest.mock.patch.object(mod, name, new); pa.start(); self.addCleanup(pa.stop)
        self.cli = unittest.mock.Mock(side_effect=self.fake_cli); self.prompt = unittest.mock.Mock(return_value=True)
        for name, m in (("compose_cli", self.cli), ("prompt_lead", self.prompt)):
            pa = unittest.mock.patch.object(ft, name, m); pa.start(); self.addCleanup(pa.stop)

    def make_project(self, slug, linear):
        self.proj = self.wt / ".compose" / slug; self.proj.mkdir(parents=True, exist_ok=True)
        (self.proj / "linear.json").write_text(json.dumps(linear)); self.projects[slug] = (self.wt, self.proj)

    def fake_cli(self, args, stdin=None):
        if args[0] == "init":
            self.make_project(args[args.index("--project") + 1], {})
            (self.proj / "linear.json").unlink()
        return ""

    def test_a_feature_with_no_project_gets_one_scoped_to_the_story_and_a_new_team_lead(self):
        line = ft.dispatch(self.repo, self.plan, entry("NEB-10", "NEB-9"), "cut", self.state, 100.0)
        init, start = self.cli.call_args_list
        self.assertEqual(init.args[0], ["init", "--repo", str(self.repo), "--project", "sign-in"])
        self.assertEqual(start.args[0][:6], ["crew", "start", "--repo", str(self.wt), "--project", "sign-in"])
        self.assertIn(ft.HOW["cut"], start.kwargs["stdin"]); self.assertIn("sections/0f.md", start.kwargs["stdin"])
        self.assertEqual(json.loads((self.proj / "linear.json").read_text()), {"feature": "NEB-9", "stories": ["NEB-10"]})
        self.assertEqual(self.state["dispatched"]["NEB-10"], {"feature": "NEB-9", "project": "sign-in", "kind": "cut", "at": 100.0})
        self.assertEqual(line, "event factory=dispatched story=NEB-10 project=sign-in kind=cut  (its team lead builds it; relay it: compose watch --project sign-in --from orchestrator)")

    def test_a_live_team_lead_is_prompted_and_only_a_scoped_project_gains_the_story(self):
        self.make_project("sign-in", {"feature": "NEB-9", "stories": ["NEB-10"]}); self.leads["sign-in"] = "sign-in-orchestrator"
        ft.dispatch(self.repo, self.plan, entry("NEB-11", "NEB-9"), "build", self.state, 100.0)
        self.cli.assert_not_called()
        self.prompt.assert_called_once_with("sign-in-orchestrator", ft.lead_prompt("NEB-11", "NEB-9", "Sign in", "build"))
        self.assertEqual(json.loads((self.proj / "linear.json").read_text())["stories"], ["NEB-10", "NEB-11"])
        self.make_project("sign-in", {"feature": "NEB-9"})
        ft.dispatch(self.repo, self.plan, entry("NEB-12", "NEB-9"), "build", self.state, 100.0)
        self.assertEqual(json.loads((self.proj / "linear.json").read_text()), {"feature": "NEB-9"})

    def test_a_lost_team_lead_is_started_again_without_a_second_init(self):
        self.make_project("sign-in", {"feature": "NEB-9", "stories": ["NEB-10"]})
        ft.dispatch(self.repo, self.plan, entry("NEB-11", "NEB-9"), "build", self.state, 100.0)
        self.assertEqual([c.args[0][0] for c in self.cli.call_args_list], ["crew"])
        self.prompt.assert_not_called()

    def test_a_feature_after_a_verified_unmerged_feature_branches_from_its_project(self):
        self.make_project("profile", {"feature": "NEB-5"})
        self.plan["features"]["NEB-9"]["blockers"] = [{"id": "NEB-5", "state": "In Review", "labels": []}]
        ft.dispatch(self.repo, self.plan, entry("NEB-10", "NEB-9"), "build", self.state, 100.0)
        self.assertEqual(self.cli.call_args_list[0].args[0][-2:], ["--after", "profile"])

    def test_a_failed_start_records_nothing(self):
        def boom(args, stdin=None):
            if args[0] == "crew":
                raise RuntimeError("herdr is not running")
            return self.fake_cli(args, stdin)
        self.cli.side_effect = boom
        with self.assertRaises(RuntimeError):
            ft.dispatch(self.repo, self.plan, entry("NEB-10", "NEB-9"), "build", self.state, 100.0)
        self.assertEqual(self.state["dispatched"], {})

    def test_a_failed_prompt_to_a_live_lead_records_nothing_and_adds_no_story(self):
        self.make_project("sign-in", {"feature": "NEB-9", "stories": ["NEB-10"]}); self.leads["sign-in"] = "sign-in-orchestrator"
        self.prompt.return_value = False
        with self.assertRaises(RuntimeError):
            ft.dispatch(self.repo, self.plan, entry("NEB-11", "NEB-9"), "build", self.state, 100.0)
        self.assertEqual((self.state["dispatched"], json.loads((self.proj / "linear.json").read_text())["stories"]), ({}, ["NEB-10"]))

    def test_the_turn_after_a_failed_start_retries_with_only_crew_start(self):
        real = self.cli.side_effect
        def boom(args, stdin=None):
            if args[0] == "crew":
                raise RuntimeError("herdr is not running")
            return real(args, stdin)
        self.cli.side_effect = boom
        with self.assertRaises(RuntimeError):
            ft.dispatch(self.repo, self.plan, entry("NEB-10", "NEB-9"), "build", self.state, 100.0)
        self.cli.reset_mock(); self.cli.side_effect = real
        ft.dispatch(self.repo, self.plan, entry("NEB-10", "NEB-9"), "build", self.state, 101.0)
        self.assertEqual([c.args[0][0] for c in self.cli.call_args_list], ["crew"])
        self.assertEqual(self.state["dispatched"]["NEB-10"]["at"], 101.0)

    def test_a_live_lead_with_a_long_slug_is_prompted_not_started_again(self):
        self.plan["features"]["NEB-9"]["title"] = "Onboarding checklist for teams"
        self.make_project("onboarding-checklist-for", {"feature": "NEB-9"}); self.leads["onboarding-checklist-for"] = "onboarding-checklis-orchestrator"
        ft.dispatch(self.repo, self.plan, entry("NEB-11", "NEB-9"), "build", self.state, 100.0)
        self.cli.assert_not_called()
        self.assertEqual(self.prompt.call_args.args[0], "onboarding-checklis-orchestrator")

    def test_a_project_init_made_but_never_linked_is_taken_up_not_numbered(self):
        self.make_project("sign-in", {}); (self.proj / "linear.json").unlink()
        ft.dispatch(self.repo, self.plan, entry("NEB-10", "NEB-9"), "build", self.state, 100.0)
        self.assertEqual([c.args[0][0] for c in self.cli.call_args_list], ["crew"])
        self.assertEqual(json.loads((self.proj / "linear.json").read_text()), {"feature": "NEB-9", "stories": ["NEB-10"]})

    def test_a_leftover_sibling_folder_or_branch_makes_a_slug_taken(self):
        (self.repo.parent / "compose-sign-in").mkdir()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "branch", "compose/sign-in-2"], check=True)
        ft.dispatch(self.repo, self.plan, entry("NEB-10", "NEB-9"), "build", self.state, 100.0)
        self.assertEqual(self.cli.call_args_list[0].args[0][-1], "sign-in-3")

    def test_slugs_are_short_kebab_and_never_taken(self):
        self.assertEqual(ft.slug_for("Sign in with Google, Apple, and email", set()), "sign-in-with-google")
        self.assertEqual(ft.slug_for("Sign in", {"sign-in"}), "sign-in-2")


if __name__ == "__main__":
    unittest.main()
