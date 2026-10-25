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
import fc_answer as fa, fc_core, fc_proc


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


class UsageWaits(unittest.TestCase):
    def setUp(self):
        self.panes, self.prompted = {}, []
        self.read = lambda name: self.panes.get(name, "")
        self.prompt = lambda name, text: self.prompted.append((name, text)) or True
        self.repo = Path(tempfile.mkdtemp()).resolve()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

    def test_reset_times_parse_to_the_next_occurrence_plus_a_minute(self):
        at = time.mktime((2026, 10, 27, 1, 10, 0, 0, 0, -1))
        self.assertEqual(time.localtime(ns.reset_at("5-hour limit reached \u2219 resets 3am", at))[3:5], (3, 1))
        self.assertEqual(time.localtime(ns.reset_at("usage limit reached, try again at 1:30 PM", at))[3:5], (13, 31))
        self.assertEqual(ns.reset_at("rate limited, resets in 2h 15m", at), at + 2 * 3600 + 15 * 60 + 60)
        self.assertIsNone(ns.reset_at("usage limit reached", at))
        self.assertEqual([ns.fallback_wait(n) for n in (1, 2, 3, 6, 9)], [60, 120, 240, 1800, 1800])

    def test_a_limited_lead_starts_a_wait_and_the_reset_prompts_it_to_continue(self):
        night = ns.new_night(0.0, 10**10, 20.0, None)
        self.panes["sign-in-orchestrator"] = "...\nYou've hit your usage limit \u00b7 resets in 30m\n"
        lines = ns.usage_step(night, {"sign-in": "sign-in-orchestrator"}, 1000.0, self.read, self.prompt)
        self.assertEqual(night["wait"]["until"], 1000.0 + 1800 + 60)
        self.assertTrue(lines[0].startswith("event factory=usage-wait until="))
        self.assertEqual(ns.usage_step(night, {"sign-in": "sign-in-orchestrator"}, 2000.0, self.read, self.prompt), [])
        self.panes["sign-in-orchestrator"] = "done thinking\n"
        lines = ns.usage_step(night, {"sign-in": "sign-in-orchestrator"}, 2861.0, self.read, self.prompt)
        self.assertEqual(self.prompted, [("sign-in-orchestrator", ns.CONTINUE)]); self.assertIsNone(night["wait"])
        self.assertEqual((night["waits"], night["waited"]), (1, 1861.0))
        self.assertTrue(lines[0].startswith("event factory=usage-resumed agents=sign-in-orchestrator"))

    def test_no_reset_time_escalates_and_a_billing_line_ends_the_night(self):
        night = ns.new_night(0.0, 10**10, 20.0, None)
        self.panes["a-orchestrator"] = "usage limit reached\n"
        ns.usage_step(night, {"a": "a-orchestrator"}, 0.0, self.read, self.prompt); self.assertEqual(night["wait"]["until"], 60.0)
        self.panes["a-orchestrator"] = "usage limit reached again\n"
        ns.usage_step(night, {"a": "a-orchestrator"}, 61.0, self.read, self.prompt); self.assertEqual(night["wait"]["until"], 181.0)
        self.panes["a-orchestrator"] = "Error: 402 Payment Required - credit balance too low\n"; night["wait"] = None
        ns.usage_step(night, {"a": "a-orchestrator"}, 300.0, self.read, self.prompt); self.assertIsNone(night["ended"])
        lines = ns.usage_step(night, {"a": "a-orchestrator"}, 360.0, self.read, self.prompt)
        self.assertEqual(night["ended"]["state"], "no-credit"); self.assertIn("factory=night-ended state=no-credit", lines[0])

    def test_a_new_limit_at_a_due_wait_keeps_the_leads_already_waiting(self):
        night, leads = ns.new_night(0.0, 10**10, 20.0, None), {"a": "a-orchestrator", "b": "b-orchestrator"}
        self.panes["a-orchestrator"] = "usage limit reached\n"
        ns.usage_step(night, leads, 0.0, self.read, self.prompt)
        self.panes["b-orchestrator"] = "usage limit reached · resets in 10m\n"
        ns.usage_step(night, leads, 61.0, self.read, self.prompt)
        self.assertEqual(night["wait"]["agents"], ["a-orchestrator", "b-orchestrator"]); self.assertEqual(self.prompted, [])
        ns.usage_step(night, leads, 61.0 + 660, self.read, self.prompt)
        self.assertEqual(sorted(n for n, _ in self.prompted), ["a-orchestrator", "b-orchestrator"]); self.assertIsNone(night["wait"])

    def test_a_later_resume_keeps_an_earlier_lead_s_stale_banner_ignored(self):
        night, leads = ns.new_night(0.0, 10**10, 20.0, None), {"a": "a-orchestrator", "b": "b-orchestrator"}
        self.panes["a-orchestrator"] = "usage limit reached\n"
        ns.usage_step(night, leads, 0.0, self.read, self.prompt); ns.usage_step(night, leads, 61.0, self.read, self.prompt)
        self.panes["b-orchestrator"] = "usage limit reached for b\n"
        ns.usage_step(night, leads, 100.0, self.read, self.prompt); ns.usage_step(night, leads, 161.0, self.read, self.prompt)
        self.assertEqual(ns.usage_step(night, leads, 200.0, self.read, self.prompt), []); self.assertIsNone(night["wait"])

    def test_a_payment_halt_since_the_night_began_is_no_credit(self):
        proj = self.repo / ".compose" / "sign-in"
        (proj / "results").mkdir(parents=True); (proj / "verify.json").write_text("{}")
        path = proj / "results" / "resume.json"
        path.write_text(json.dumps({"provider": "openrouter"})); os.utime(path, (100.0, 100.0))
        self.assertEqual(ns.no_credit(self.repo, 0.0), "sign-in: payment halt (openrouter)")
        self.assertIsNone(ns.no_credit(self.repo, 200.0))

    PAY = "Error: 402 Payment Required - credit balance is too low"

    def look(self, night, now, name="a-orchestrator"):
        return ns.usage_step(night, {"a": name}, now, self.read, self.prompt)

    def test_ordinary_pane_text_never_ends_the_night(self):
        for text in ("src/billing/checkout.ts | 12 +++", "\u2713 returns 402 when the card is declined", "+  // top up the wallet",
                     "expect(res.status).toBe(402)", "+  // error: 402 credit balance is too low", "- Error: 402 insufficient credits"):
            night = ns.new_night(0.0, 10**10, 20.0, None)
            self.panes["a-orchestrator"] = "usage limit reached\n" + text + "\n"
            self.look(night, 0.0); self.look(night, 500.0); self.look(night, 1000.0)
            self.assertIsNone(night["ended"], text)

    def test_a_real_billing_banner_must_be_seen_twice_a_minute_apart(self):
        night = ns.new_night(0.0, 10**10, 20.0, None)
        self.panes["a-orchestrator"] = self.PAY + "\n"
        self.look(night, 0.0); self.assertIsNone(night["ended"]); self.assertIsNotNone(night["wait"])
        self.look(night, 60.0); self.assertEqual(night["ended"]["state"], "no-credit")
        night = ns.new_night(0.0, 10**10, 20.0, None)
        self.look(night, 0.0); self.panes["a-orchestrator"] = "usage limit reached, resets in 5m\n"; self.look(night, 60.0)
        self.assertEqual(night["pay_seen"], {}); self.panes["a-orchestrator"] = self.PAY + "\n"; self.look(night, 400.0)
        self.assertIsNone(night["ended"])

    def test_a_stale_banner_at_the_due_time_is_prompted_not_waited_again(self):
        night = ns.new_night(0.0, 10**10, 20.0, None)
        self.panes["a-orchestrator"] = "usage limit reached, resets in 30m\n"
        self.look(night, 0.0)
        lines = self.look(night, 1861.0)
        self.assertEqual(self.prompted, [("a-orchestrator", ns.CONTINUE)]); self.assertIsNone(night["wait"])
        self.assertTrue(lines[0].startswith("event factory=usage-resumed"))
        self.assertEqual(self.look(night, 1900.0), []); self.assertIsNone(night["wait"])
        self.panes["a-orchestrator"] = "usage limit reached, resets in 2h\n"
        self.look(night, 2000.0); self.assertEqual(night["wait"]["until"], 2000.0 + 7200 + 60)

    def test_bare_clocks_in_timestamps_and_far_resets_do_not_count(self):
        at = time.mktime((2026, 10, 27, 1, 10, 0, 0, 0, -1))
        self.assertIsNone(ns.reset_at("[01:09:58] Retrying in 4s ... 429", at)); self.assertIsNone(ns.reset_at("limit, in 3 hello", at))
        self.assertIsNotNone(ns.reset_at("limit reached, resets 3am", at))
        night = ns.new_night(at, 10**11, 20.0, None)
        self.panes["a-orchestrator"] = "usage limit reached, resets 11am\n"
        self.look(night, at); self.assertEqual(night["wait"]["until"], at + 60)

    def test_an_empty_read_or_a_failed_prompt_extends_the_wait_and_counts_nothing(self):
        night = ns.new_night(0.0, 10**10, 20.0, None)
        self.panes["a-orchestrator"] = "usage limit reached\n"; self.look(night, 0.0)
        self.panes["a-orchestrator"] = ""; self.look(night, 61.0)
        self.assertEqual((night["wait"]["until"], self.prompted, night["waits"]), (181.0, [], 0))
        self.panes["a-orchestrator"] = "idle\n"; self.prompt = lambda name, text: False
        self.look(night, 182.0); self.assertEqual((night["wait"]["until"], night["waits"]), (182.0 + 240, 0))
        self.look(night, 500.0); self.assertEqual(night["waits"], 0)
        self.prompt = lambda name, text: self.prompted.append((name, text)) or True
        self.look(night, 1000.0); self.assertEqual((night["waits"], night["wait"]), (1, None))
        night["wait"] = {"until": 0.0, "n": 0, "since": 0.0, "agents": ["gone"], "lines": {}}; self.prompted.clear()
        self.look(night, 5.0); self.assertEqual((self.prompted, night["wait"]), ([], None))

    def test_a_resume_json_that_is_not_an_object_is_reported_as_unknown(self):
        proj = self.repo / ".compose" / "x"
        (proj / "results").mkdir(parents=True); (proj / "verify.json").write_text("{}")
        (proj / "results" / "resume.json").write_text("[1]")
        self.assertEqual(ns.no_credit(self.repo, 0.0), "x: payment halt (unknown)")


class Answerer(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp()).resolve()
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        self.proj = self.repo / ".compose" / "sign-in"
        (self.proj / "results" / "crew").mkdir(parents=True)
        (self.proj / "verify.json").write_text("{}")
        (self.proj / "linear.json").write_text(json.dumps({"feature": "NEB-9"}))
        (self.proj / "results" / "yolo.json").write_text(json.dumps({"mode": "night"}))
        self.state = {"night": ns.new_night(fc_core.report_time("2026-10-26 22:00:00"), 0.0, 10.0, None)}
        self.gone, self.events, self.pids = set(), [], iter(range(5000, 5100))
        def cli(args, stdin=None, pane=None):
            return json.dumps({"identifier": args[2], "title": "t", "description": "d"}) if args[:2] == ["linear", "get"] else ""
        patches = [unittest.mock.patch.object(fa.fc_nightstate, "spawn_once", side_effect=lambda *a: next(self.pids)),
                   unittest.mock.patch.object(fa.fc_claude, "claude_once"),
                   unittest.mock.patch.object(fa.fc_factoryturn, "compose_cli", side_effect=cli),
                   unittest.mock.patch.object(fa.fc_factoryturn, "prompt_lead", return_value=True),
                   unittest.mock.patch.object(fa.fc_factorystate, "add_event", side_effect=lambda repo, line: self.events.append(line)),
                   unittest.mock.patch.object(fa.fc_delivery, "product_plan", return_value={"doc": {"content": "PLAN"}}),
                   unittest.mock.patch.object(fa.os, "kill", side_effect=self.kill)]
        self.spawn, self.claude, self.cli, self.prompt = (p.start() for p in patches[:4])
        for p in patches[4:]:
            p.start()
        self.addCleanup(unittest.mock.patch.stopall)

    def kill(self, pid, sig):
        if pid in self.gone:
            raise ProcessLookupError

    def dead(self, pid):
        self.gone.add(pid)

    def report(self, state, message, at):
        with open(self.proj / "results" / "crew" / "sign-in-orchestrator.status", "a") as f:
            f.write(json.dumps({"at": at, "state": state, "message": message, "why": ""}) + "\n")

    def test_planning_questions_wait_for_the_morning_and_the_rest_get_one_answerer_each(self):
        self.report("needs-user", "shape NEB-12: no design yet", "2026-10-27 01:00:00")
        self.report("needs-user", "NEB-10: 2 cards Q1,Q2; recommendation Q1 A, Q2 B", "2026-10-27 01:05:00")
        lines = fa.answer_step(self.repo, self.state, 100.0)
        self.assertEqual(lines, ['event factory=for-morning project=sign-in question="shape NEB-12: no design yet"  '
                                 "(planning waits for the product owner: it is listed under Ready to plan)"])
        self.spawn.assert_called_once_with(self.repo, ["factory", "answer", "--repo", str(self.repo), "--project", "sign-in",
                                                       "--at", "2026-10-27 01:05:00", "--nth", "0"], "night-answer.log")
        self.assertEqual(fa.answer_step(self.repo, self.state, 160.0), [])  # neither is asked twice

    def test_at_most_two_answerers_run_and_a_dead_one_without_a_record_is_said_once(self):
        for i in range(3):
            self.report("needs-user", f"NEB-1{i}: question {i}", f"2026-10-27 01:0{i}:00")
        fa.answer_step(self.repo, self.state, 100.0)
        self.assertEqual(self.spawn.call_count, 2)
        self.dead(self.state["night"]["asked"]["sign-in@2026-10-27 01:00:00"]["pid"])
        lines = fa.answer_step(self.repo, self.state, 200.0)
        self.assertIn('event factory=answer-failed project=sign-in question="NEB-10: question 0"  (the answerer ended without an answer: it waits for the product owner)', lines)
        self.assertEqual(self.spawn.call_count, 3)
        self.assertNotIn("answer-failed", "".join(fa.answer_step(self.repo, self.state, 260.0)))

    def test_the_worker_records_cards_through_decide_and_the_rest_through_the_team_lead(self):
        self.report("needs-user", "NEB-10: 1 card Q1; recommendation A", "2026-10-27 01:05:00")
        self.claude.return_value = (None, '{"never_set": false, "answer": "Q1 A", "reasoning": "D2 says one store", "cards": {"Q1": "A"}}', 3, {})
        fa.run_answer(self.repo, "sign-in", "2026-10-27 01:05:00")
        self.assertEqual(self.cli.call_args_list[-1].args[0], ["decide", "--repo", str(self.repo), "--project", "sign-in", "Q1: A"])
        comment = next(c for c in self.cli.call_args_list if c.args[0][:2] == ["linear", "comment"])
        self.assertEqual(comment.args[0][2], "NEB-10"); self.assertIn("Answered while you were away", comment.kwargs["stdin"])
        self.prompt.assert_not_called()
        self.assertEqual(json.loads(fa.answers_path(self.repo).read_text().splitlines()[-1])["answer"], "Q1 A")
        self.assertEqual(self.claude.call_args.kwargs["tools"], "Read,Grep,Glob"); self.assertEqual(self.claude.call_args.kwargs["effort"], "high")
        self.claude.return_value = (None, '{"never_set": false, "answer": "keep 30 day sessions", "reasoning": "r", "cards": {}}', 3, {})
        fa.run_answer(self.repo, "sign-in", "2026-10-27 01:05:00")
        self.prompt.assert_called_once_with("sign-in-orchestrator", "night: keep 30 day sessions")

    def test_a_never_set_question_is_never_answered(self):
        self.report("needs-user", "NEB-10: force-push the rebased branch?", "2026-10-27 01:05:00")
        self.claude.return_value = (None, '{"never_set": true, "why_wait": "force-push", "answer": "", "reasoning": "", "cards": {}}', 1, {})
        rec = fa.run_answer(self.repo, "sign-in", "2026-10-27 01:05:00")
        self.assertTrue(rec["never_set"]); self.prompt.assert_not_called()
        self.assertFalse(any(c.args[0][0] == "decide" for c in self.cli.call_args_list))
        self.assertTrue(self.events[-1].startswith('event factory=waiting project=sign-in question="NEB-10: force-push the rebased branch?"'))

    def test_an_unparsable_reply_records_the_error_and_says_answer_failed(self):
        self.report("needs-user", "NEB-10: q", "2026-10-27 01:05:00")
        self.claude.return_value = (None, "no json here", 1, {})
        rec = fa.run_answer(self.repo, "sign-in", "2026-10-27 01:05:00")
        self.assertTrue(rec["error"]); self.assertTrue(self.events[-1].startswith("event factory=answer-failed project=sign-in"))
        self.prompt.assert_not_called()

    def reply(self, **kw):
        self.claude.return_value = (None, json.dumps({"never_set": False, "answer": "a", "reasoning": "r", "cards": {}, **kw}), 1, {})

    def test_any_never_set_object_in_the_reply_wins_over_an_example(self):
        self.report("needs-user", "NEB-10: q", "2026-10-27 01:05:00")
        self.claude.return_value = (None, 'Example: {"answer": "yes", "never_set": false} but really {"never_set": true, "answer": "", "why_wait": "x"}', 1, {})
        self.assertTrue(fa.run_answer(self.repo, "sign-in", "2026-10-27 01:05:00")["never_set"])
        self.prompt.assert_not_called()
        self.claude.return_value = (None, '{"answer": "yes"}', 1, {})
        self.assertTrue(fa.run_answer(self.repo, "sign-in", "2026-10-27 01:05:00")["error"])

    def test_a_failed_decide_after_the_comment_is_recorded_as_partial(self):
        self.report("needs-user", "NEB-10: Q1 here", "2026-10-27 01:05:00")
        self.reply(cards={"Q1": "A"})
        self.cli.side_effect = lambda args, stdin=None, pane=None: (_ for _ in ()).throw(RuntimeError("boom")) if args[0] == "decide" else ""
        rec = fa.run_answer(self.repo, "sign-in", "2026-10-27 01:05:00")
        self.assertEqual((rec["commented"], rec["acted"]), (True, False))
        self.assertIn("answer-failed", self.events[-1]); self.assertIn("boom", self.events[-1])
        self.assertEqual(len(fa.answers_path(self.repo).read_text().splitlines()), 1)

    def test_a_lead_that_did_not_take_the_prompt_is_not_answered(self):
        self.report("needs-user", "NEB-10: q", "2026-10-27 01:05:00")
        self.reply(); self.prompt.return_value = False
        self.assertTrue(fa.run_answer(self.repo, "sign-in", "2026-10-27 01:05:00")["error"])
        self.assertIn("answer-failed", self.events[-1])

    def test_only_the_teams_issue_ids_count(self):
        self.report("needs-user", "should we use SHA-256 for NEB-10 tokens?", "2026-10-27 01:00:00")
        self.report("needs-user", "use UTF-8?", "2026-10-27 01:01:00")
        self.assertEqual([q["issue"] for q in fa.new_questions(self.repo, self.state["night"])], ["NEB-10", "NEB-9"])

    def test_two_reports_in_one_second_are_two_questions_and_a_repeat_is_not_asked_again(self):
        self.report("needs-user", "NEB-10: one", "2026-10-27 01:00:00")
        self.report("needs-user", "NEB-10: two", "2026-10-27 01:00:00")
        self.report("needs-user", "NEB-10: one", "2026-10-27 01:02:00")
        fa.answer_step(self.repo, self.state, 100.0)
        self.assertEqual(sorted(self.state["night"]["asked"]), ["sign-in@2026-10-27 01:00:00", "sign-in@2026-10-27 01:00:00#1"])
        self.assertEqual(self.spawn.call_args.args[1][-2:], ["--nth", "1"])
        self.reply(); self.assertEqual(fa.run_answer(self.repo, "sign-in", "2026-10-27 01:00:00", 1)["question"], "NEB-10: two")

    def test_never_words_in_the_question_or_the_answer_force_never_set(self):
        self.report("needs-user", "NEB-10: ok to force-push?", "2026-10-27 01:05:00")
        self.reply(answer="yes")
        rec = fa.run_answer(self.repo, "sign-in", "2026-10-27 01:05:00")
        self.assertTrue(rec["never_set"]); self.assertIn("force-push", rec["why_wait"]); self.prompt.assert_not_called()
        self.assertFalse(any(c.args[0][:2] == ["linear", "comment"] for c in self.cli.call_args_list))

    def test_card_ids_must_be_cards_of_the_question(self):
        self.report("needs-user", "NEB-10: 1 card Q1", "2026-10-27 01:05:00")
        self.reply(answer="", cards={"D2": "x", "Q9": "B"})
        self.assertTrue(fa.run_answer(self.repo, "sign-in", "2026-10-27 01:05:00")["error"])
        self.reply(cards={"D2": "x", "Q1": "A"})
        self.assertEqual(fa.run_answer(self.repo, "sign-in", "2026-10-27 01:05:00")["cards"], {"Q1": "A"})

    def test_a_torn_status_file_does_not_stop_the_step(self):
        (self.proj / "results" / "crew" / "sign-in-orchestrator.status").write_text("{torn\n")
        self.assertEqual(fa.new_questions(self.repo, self.state["night"]), [])

    def test_d_ids_are_never_cards(self):
        self.report("needs-user", "NEB-10: should D2 change? cards Q1", "2026-10-27 01:05:00")
        self.reply(cards={"D2": "x", "Q1": "A"})
        fa.run_answer(self.repo, "sign-in", "2026-10-27 01:05:00")
        decides = [c.args[0] for c in self.cli.call_args_list if c.args[0][0] == "decide"]
        self.assertEqual(decides, [["decide", "--repo", str(self.repo), "--project", "sign-in", "Q1: A"]])

    def test_in_flight_repeats_are_silent_and_answered_repeats_go_to_the_morning_once(self):
        self.report("needs-user", "NEB-10: same", "2026-10-27 01:00:00")
        fa.answer_step(self.repo, self.state, 100.0)
        self.report("needs-user", "NEB-10: same", "2026-10-27 01:02:00")
        self.assertEqual(fa.answer_step(self.repo, self.state, 120.0), []); self.assertEqual(self.spawn.call_count, 1)
        self.reply(); fa.run_answer(self.repo, "sign-in", "2026-10-27 01:00:00")
        self.dead(self.state["night"]["asked"]["sign-in@2026-10-27 01:00:00"]["pid"])
        want = ['event factory=for-morning project=sign-in question="NEB-10: same"  (asked again after the night answer: it waits for the product owner)']
        self.assertEqual(fa.answer_step(self.repo, self.state, 200.0), want)
        self.assertEqual(fa.answer_step(self.repo, self.state, 260.0), []); self.assertEqual(self.spawn.call_count, 1)

    def test_the_guard_is_about_actions_not_topics(self):
        for text in ("should the auth provider return a client secret field?", "which OAuth provider first?"):
            self.assertEqual(fa.never_hits(text), [], text)
        for text in ("should I force-push the rebased branch?", "add a new API key for Stripe?", "switch the model to opus?"):
            self.assertTrue(fa.never_hits(text), text)

    def test_the_guard_reads_card_values_and_reasoning(self):
        self.report("needs-user", "NEB-10: 1 card Q1", "2026-10-27 01:05:00")
        self.reply(answer="", cards={"Q1": "B. purchase the Pro plan"})
        self.assertTrue(fa.run_answer(self.repo, "sign-in", "2026-10-27 01:05:00")["never_set"])
        self.assertFalse(any(c.args[0][0] == "decide" for c in self.cli.call_args_list))
        self.reply(reasoning="we must wipe the database first")
        self.assertTrue(fa.run_answer(self.repo, "sign-in", "2026-10-27 01:05:00")["never_set"])

    def test_a_timeout_is_a_recorded_failure(self):
        self.report("needs-user", "NEB-10: q", "2026-10-27 01:05:00")
        self.claude.side_effect = subprocess.TimeoutExpired("claude", 1800)
        self.assertTrue(fa.run_answer(self.repo, "sign-in", "2026-10-27 01:05:00")["error"])
        self.assertEqual(len(fa.answers_path(self.repo).read_text().splitlines()), 1)
        self.assertIn("answer-failed", self.events[-1])

    def test_a_recorded_key_is_not_asked_again_after_lost_state(self):
        self.report("needs-user", "NEB-10: q", "2026-10-27 01:05:00")
        self.reply(); fa.run_answer(self.repo, "sign-in", "2026-10-27 01:05:00")
        self.assertEqual(fa.answer_step(self.repo, self.state, 100.0), []); self.spawn.assert_not_called()

    def test_reports_before_the_night_are_not_questions(self):
        self.report("needs-user", "NEB-10: old", "2026-10-26 20:00:00")
        self.assertEqual(fa.new_questions(self.repo, self.state["night"]), [])

    def test_claude_once_passes_effort_and_keeps_the_tail_it_is_asked_for(self):
        unittest.mock.patch.stopall()
        run = unittest.mock.Mock(return_value=unittest.mock.Mock(stdout=json.dumps({"result": "x" * 5000}), returncode=0))
        with unittest.mock.patch.object(fc_proc, "run", run):
            reply = fc_claude.claude_once(self.repo, "p", effort="high", keep=4000)[1]
            self.assertEqual(len(reply), 4000)
            self.assertEqual(run.call_args.args[0][run.call_args.args[0].index("--effort") + 1], "high")
            self.assertEqual(len(fc_claude.claude_once(self.repo, "p")[1]), 1500)
            self.assertNotIn("--effort", run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
