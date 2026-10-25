import hermetic  # first: no test sees the real home
import inspect, json, os, subprocess, tempfile, unittest, unittest.mock
from pathlib import Path
import importlib.machinery, importlib.util, sys
# tests/test_modules.py fails a test file without the next line
os.environ["HERDR_ENV"] = ""
_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_factorystate as st


BIN = Path(__file__).resolve().parents[1] / "bin"


class PlansLanded(unittest.TestCase):
    def params(self, fn):
        return list(inspect.signature(fn).parameters)

    def test_the_interfaces_this_builds_on_exist_as_promised(self):
        import fc_change as c, fc_delivery as d, fc_linear, fc_plan as p, fc_readiness as r, fc_reconcile
        self.assertEqual([self.params(f) for f in (d.product_plan, d.delivery_order, d.last_reconcile)], [["repo"]] * 3)
        self.assertEqual(self.params(d.reconcile), ["repo", "dry_run"])
        self.assertTrue(d.NO_PLAN.startswith("no product delivery plan yet"))
        self.assertEqual((self.params(p.order_entries), self.params(p.base_built)), (["tracks", "features"], ["state", "labels"]))
        self.assertEqual(self.params(r.story_readiness), ["repo", "story", "refresh", "write"])
        self.assertTrue(issubclass(r.NotAStory, Exception) and callable(r.readiness_line))
        self.assertEqual((self.params(c.rests_on), self.params(c.hold_tasks)), (["proj", "refs"], ["proj", "ids", "reason"]))
        self.assertEqual(fc_linear.NEEDS_SHAPING, "needs-shaping")
        self.assertEqual(self.params(fc_reconcile.live_leads), ["repo"])

    def test_their_verbs_are_registered(self):
        run = lambda *a: subprocess.run([sys.executable, str(BIN / "compose.py"), *a], capture_output=True, text=True).stdout
        for verb in ("delivery", "readiness", "reconcile", "hold"):
            self.assertRegex(run("--help"), rf"(?m)^    {verb}\b")
        self.assertIn("--rests-on", run("hold", "--help"))


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


FEATURE = "## Decisions so far\n\n- D1: Google only (product owner)\n- D2: 30 day sessions\n"


class PlanChange(unittest.TestCase):
    def setUp(self):
        self.repo, self.proj = Path("/repo"), Path("/repo/.compose/sign-in")
        self.rests_on = unittest.mock.Mock(); self.hold = unittest.mock.Mock()
        for name, m in (("rests_on", self.rests_on), ("hold_tasks", self.hold)):
            pa = unittest.mock.patch.object(ft.fc_change, name, m); pa.start(); self.addCleanup(pa.stop)

    def test_open_questions_edits_are_no_change_and_scope_edits_are(self):
        a = ft.fingerprint(FEATURE, "## Scope\n\nGoogle only\n\n## Open questions\n\n- x (readiness check, 2026-10-26)\n")
        b = ft.fingerprint(FEATURE, "## Scope\n\nGoogle only\n\n## Open questions\n\nNone\n")
        self.assertEqual(ft.changed_refs(a, b, "NEB-10"), [])
        self.assertEqual(ft.changed_refs(a, ft.fingerprint(FEATURE, "## Scope\n\nGoogle and Apple\n"), "NEB-10"), ["NEB-10"])

    def test_a_changed_decision_passes_its_ids_and_one_without_an_id_passes_the_story(self):
        a = ft.fingerprint("## Decisions so far\n\n- D1: Google only (product owner)\n- D2: 30 day sessions\n", "s")
        b = ft.fingerprint("## Decisions so far\n\n- ~~D1: Google only~~ (C1)\n- D2: 30 day sessions\n- D3: Google and Apple\n", "s")
        self.assertEqual(ft.changed_refs(a, b, "NEB-10"), ["D1", "D3"])
        c, d = ft.fingerprint("## Decisions so far\n\n- one store\n", "s"), ft.fingerprint("## Decisions so far\n\n- two stores\n", "s")
        self.assertEqual(ft.changed_refs(c, d, "NEB-10"), ["NEB-10"])

    def test_hold_changed_holds_what_rests_on_the_refs_or_says_nothing_does(self):
        self.rests_on.return_value = {"002": "cites D1", "003": "under NEB-10"}
        line = ft.hold_changed(self.repo, self.proj, "NEB-10", ["D1"], "D1 changed on NEB-9")
        self.hold.assert_called_once_with(self.proj, ["002", "003"], "factory: D1 changed on NEB-9")
        self.assertEqual(line, 'event factory=held story=NEB-10 tasks=002,003 why="D1 changed on NEB-9"  '
                               "(re-plan it with the product owner: keep, part, or discard each held task with compose change, step 8)")
        self.rests_on.return_value = {}; self.hold.reset_mock()
        line = ft.hold_changed(self.repo, self.proj, "NEB-10", ["NEB-10"], "NEB-10 changed")
        self.hold.assert_not_called()
        self.assertEqual(line, 'event factory=changed story=NEB-10 why="NEB-10 changed"  (nothing running rests on it)')


class Turn(unittest.TestCase):
    def setUp(self):
        self.repo, self.wt = Path("/repo"), Path("/repo-wt")
        self.state = json.loads(json.dumps(st.EMPTY))
        self.calls, self.leads, self.results, self.descriptions = [], {}, {}, {}
        self.plan = {"tracks": [{"name": "t", "items": ["NEB-9"]}], "features": {}}
        self.entries = []
        self.add_entry("NEB-10", "NEB-9", labels=("Ready",)); self.add_entry("NEB-11", "NEB-9", labels=("Ready",))
        self.plan["features"]["NEB-9"].update(title="Sign in", state="Todo", labels=["Feature"], blockers=[])
        self.descriptions["NEB-9"] = FEATURE
        for s in ("NEB-10", "NEB-11"):
            self.descriptions[s] = "## Scope\n\nsame\n"; self.results[s] = rd(s)
        self.reconciled = {"added": [], "removed": [], "ready": [], "proposed": [], "doc": "u"}
        n = [0]
        def product_plan(repo):
            n[0] += 1; self.calls.append(f"product_plan:{n[0]}")
            return self.plan_value if hasattr(self, "plan_value") else self.plan
        def reconcile(repo, dry_run=False):
            self.calls.append("reconcile"); return self.reconciled
        def dispatch(repo, plan, e, kind, state, now):
            state["dispatched"][e["id"]] = {"feature": e["feature"], "project": "sign-in", "kind": kind, "at": now}
            return f"event factory=dispatched story={e['id']}"
        self.product_plan = unittest.mock.Mock(side_effect=product_plan)
        self.reconcile = unittest.mock.Mock(side_effect=reconcile)
        self.dispatch = unittest.mock.Mock(side_effect=dispatch)
        self.held = unittest.mock.Mock(return_value=False)
        self.hold_changed = unittest.mock.Mock(return_value="event factory=held story=x")
        issue = lambda ident: {"id": ident, "description": self.descriptions.get(ident, "")}
        for mod, name, m in ((ft.fc_delivery, "product_plan", self.product_plan), (ft.fc_delivery, "reconcile", self.reconcile),
                             (ft.fc_plan, "order_entries", lambda tracks, features: [dict(e) for e in self.entries]),
                             (ft.fc_readiness, "story_readiness", lambda repo, s, **kw: self.results[s]),
                             (ft.fc_load, "held", self.held), (ft.fc_linear, "linear_issue", issue),
                             (ft.fc_reconcile, "live_leads", lambda repo: dict(self.leads)),
                             (ft, "dispatch", self.dispatch), (ft, "hold_changed", self.hold_changed),
                             (ft, "project_for", lambda repo, feature: ("sign-in", self.wt, self.wt / "sign-in"))):
            pa = unittest.mock.patch.object(mod, name, m); pa.start(); self.addCleanup(pa.stop)

    def add_entry(self, ident, feature, waits_on=(), labels=()):
        f = self.plan["features"].setdefault(feature, {"id": feature, "title": feature, "state": "Todo", "labels": ["Feature"], "stories": [], "blockers": []})
        f["stories"].append(story(ident, "Todo", *labels))
        self.entries.append(entry(ident, feature, waits_on=waits_on))

    def set_states(self, **states):
        for f in self.plan["features"].values():
            for s in f["stories"]:
                s["state"] = states.get(s["id"], s["state"])
        for e in self.entries:
            e["state"] = states.get(e["id"], e["state"])

    def set_waits(self, ident, waits_on):
        for e in self.entries:
            if e["id"] == ident:
                e["waits_on"] = list(waits_on)

    def make_nothing_ready(self, missing):
        for s in ("NEB-10", "NEB-11"):
            self.results[s] = rd(s, ready=False, specced=False, missing=[{"item": missing.split(":")[0], "question": missing.split(": ", 1)[1]}])

    def test_no_product_plan_offers_the_bootstrap_once_and_dispatches_nothing(self):
        self.product_plan.side_effect = None; self.product_plan.return_value = None
        lines = ft.turn(self.repo, self.state, 100.0) + ft.turn(self.repo, self.state, 200.0)
        self.assertEqual(lines, ["event factory=bootstrap  (no product delivery plan yet: plan it with the product owner from "
                                 "compose delivery seed (sections/0p.md); nothing is dispatched before it exists)"])
        self.reconcile.assert_not_called(); self.dispatch.assert_not_called()

    def test_a_turn_reconciles_then_fills_the_free_slots_and_the_load_hold_stops_it(self):
        ft.turn(self.repo, self.state, 100.0)
        self.assertLess(self.calls.index("reconcile"), self.calls.index("product_plan:2"))
        self.assertEqual([c.args[2]["id"] for c in self.dispatch.call_args_list], ["NEB-10", "NEB-11"])
        self.dispatch.reset_mock(); self.state["dispatched"] = {}; self.held.return_value = True
        ft.turn(self.repo, self.state, 200.0)
        self.dispatch.assert_not_called()

    def test_a_restart_dispatches_nothing_twice(self):  # NEB-10 dispatched before the crash, NEB-11 started by hand
        self.state["dispatched"] = {"NEB-10": {"feature": "NEB-9", "project": "sign-in", "kind": "build", "at": 1.0}}
        self.set_states(**{"NEB-11": "In Progress"}); self.leads["sign-in"] = "sign-in-orchestrator"
        ft.turn(self.repo, self.state, 100.0)
        self.dispatch.assert_not_called()

    def test_nothing_ready_offers_once_a_decline_snoozes_and_planning_holds_it(self):
        self.make_nothing_ready(missing="scope: What is out?")
        self.assertEqual(ft.turn(self.repo, self.state, 100.0), ['event factory=offer ticket=NEB-10 layer=story why="scope: What is out?"  '
                         "(offer to plan it with the product owner (sections/0f.md); they may pick another ticket or decline)"])
        self.assertEqual((self.state["offer"]["id"], ft.turn(self.repo, self.state, 160.0)), ("NEB-10", []))
        self.state["said"].pop("offer"); self.state["declined_until"] = 3700.0
        self.assertEqual((ft.turn(self.repo, self.state, 200.0), len(ft.turn(self.repo, self.state, 3701.0))), ([], 1))
        self.state["said"].pop("offer"); self.state["planning"] = {"id": "NEB-30", "at": 1.0, "out_of_order": True}
        self.assertEqual(ft.turn(self.repo, self.state, 3800.0), [])

    def test_an_out_of_order_ticket_asks_once_to_move_up_when_specced(self):
        self.state["out_of_order"] = ["NEB-31"]
        self.add_entry("NEB-31", "NEB-30", waits_on=("NEB-9",)); self.results["NEB-31"] = rd("NEB-31", ready=False, has_tasks=False)
        lines = [l for l in ft.turn(self.repo, self.state, 100.0) + ft.turn(self.repo, self.state, 200.0) if "move-up" in l]
        self.assertEqual(lines, ["event factory=move-up ticket=NEB-31 waits_on=NEB-9  (planned out of order and now specced: ask the "
                                 "product owner whether to move it up; on yes, write the tracks again (sections/0p.md))"])
        self.assertEqual(self.state["out_of_order"], [])

    def test_in_review_frees_the_slot_and_a_lost_team_lead_requeues(self):
        self.state["dispatched"] = {s: {"feature": "NEB-9", "project": "sign-in", "kind": "build", "at": 1.0} for s in ("NEB-10", "NEB-11")}
        self.set_states(**{"NEB-10": "In Review"})  # NEB-11 still Todo, no live lead
        lines = ft.turn(self.repo, self.state, 100.0)
        self.assertIn("event factory=verified story=NEB-10 project=sign-in  (verified: waiting for the product owner's look and merge)", lines)
        self.assertIn("event factory=lead-lost story=NEB-11 project=sign-in  (its team lead is gone: the story goes back in the queue)", lines)

    def test_a_changed_or_reordered_in_flight_story_is_held_once(self):
        self.state["dispatched"] = {"NEB-10": {"feature": "NEB-9", "project": "sign-in", "kind": "build", "at": 1.0}}
        self.set_states(**{"NEB-10": "In Progress"}); self.leads["sign-in"] = "sign-in-orchestrator"
        ft.turn(self.repo, self.state, 100.0)  # the first look only records the fingerprint
        self.descriptions["NEB-10"] = "## Scope\n\nchanged\n"
        ft.turn(self.repo, self.state, 200.0); ft.turn(self.repo, self.state, 300.0)
        self.assertEqual([c.args[2:4] for c in self.hold_changed.call_args_list], [("NEB-10", ["NEB-10"])])
        self.set_waits("NEB-10", ("NEB-5",)); ft.turn(self.repo, self.state, 400.0)
        self.assertEqual(self.hold_changed.call_args.args[4], "the product delivery plan now puts NEB-9 after NEB-5")

    def test_proposals_and_failures_are_said_once_and_the_next_turn_tries_again(self):
        self.reconciled = {"added": [], "removed": [], "ready": [], "proposed": ["NEB-30 is not in the plan: add it or cancel it."], "doc": "u"}
        lines = ft.turn(self.repo, self.state, 100.0) + ft.turn(self.repo, self.state, 200.0)
        self.assertEqual(len([l for l in lines if "factory=proposed" in l]), 1)
        self.reconcile.side_effect = [SystemExit("delivery reconcile: timed out; run it again")] * 2 + [self.reconciled]
        self.assertEqual((ft.turn(self.repo, self.state, 300.0), ft.turn(self.repo, self.state, 400.0)),
                         (['event factory=turn-failed why="delivery reconcile: timed out; run it again"  (the next turn tries again)'], []))
        self.dispatch.reset_mock(); ft.turn(self.repo, self.state, 500.0)
        self.dispatch.assert_called()


if __name__ == "__main__":
    unittest.main()
