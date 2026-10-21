import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, json, os, sys, unittest
from pathlib import Path
from unittest import mock
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"
os.environ["HERDR_ENV"] = ""
_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_routejev  # noqa: E402  (bin is on sys.path now; compose.py does not import it yet)

STATE = {"task": "Greet by name", "criteria": ["works"], "files": [{"path": "bin/x.py", "top": "bin", "exists": True}], "pin": None}
PLAIN = [{"name": "Secrets", "statement": "API keys are checked end to end.", "globs": [], "checks": ["t"]}, {"name": "Docs", "statement": "Docs match the CLI.", "globs": [], "checks": []}]
CALLERS = {"callers": {"bin/x.py": ["bin/y.py"]}}
def ans(choice, conf): return {"choice": choice, "probabilities": {choice: 0.8}, "confidence": conf}
def reply(**answers): return {"model": "jev-test", "answers": answers}
def pick(route, *keys): return tuple(route[k] for k in keys)


class Ask(unittest.TestCase):
    def decide(self, side_effect, state=STATE, cfg=None, plain=()):
        more = mock.Mock(return_value=CALLERS)
        with mock.patch.object(fc.fc_models, "jev_ask", side_effect=side_effect) as ask:
            route = fc_routejev.decide({}, cfg or {}, state, [], list(plain), more)
        return route, ask, more

    def test_questions_follow_pin_and_plain_policies(self):
        q, yn = fc_routejev.route_questions(STATE, PLAIN), {f"policy{i}": ("choice", {"APPLIES", "DOES_NOT_APPLY"}) for i in (0, 1)}
        self.assertEqual({k: (v["type"], set(v["criteria"])) for k, v in q.items()},
                         {"workflow": ("choice", {"TEST_FIRST", "IMPLEMENT_THEN_TEST", "FIX_THEN_REGRESSION_TEST"}), "depth": ("choice", {"FAST", "STANDARD", "DEEP"}), **yn})
        self.assertIn(PLAIN[1]["statement"], json.dumps(q["policy1"]["instructions"]))
        self.assertEqual(set(fc_routejev.route_questions({**STATE, "pin": "implement-then-test"}, [])), {"depth"})

    def test_confident_answers_route_without_retry(self):
        good = reply(depth=ans("STANDARD", 0.65), workflow=ans("FIX_THEN_REGRESSION_TEST", 0.6), policy0=ans("APPLIES", 0.9))
        route, ask, more = self.decide([good], plain=PLAIN[:1])
        self.assertEqual(route, {"workflow": "fix-then-regression-test", "depth": "DEEP", "decided_by": "jev", "confidence": 0.6,
                                 "answers": good["answers"], "retry": None, "fallback": None, "floor": ["Secrets"], "checks": ["t"]})
        self.assertEqual((ask.call_args.args[2:], more.call_count), ((STATE, fc_routejev.route_questions(STATE, PLAIN[:1]), "Jev route"), 0))
        route, ask, _ = self.decide([reply(depth=ans("FAST", 0.9))], state={**STATE, "pin": "fix-then-regression-test"})
        self.assertEqual((ask.call_count, *pick(route, "workflow", "depth", "decided_by", "confidence")), (1, "fix-then-regression-test", "FAST", "pin + jev", 0.9))

    def test_missing_answer_retries_once_with_dependencies(self):
        second = reply(depth=ans("DEEP", 0.9), workflow=ans("IMPLEMENT_THEN_TEST", 0.8))
        route, ask, more = self.decide([reply(depth=ans("FAST", 0.9)), second])
        self.assertEqual(ask.call_args_list[1].args[2:], ({**STATE, "dependencies": CALLERS}, ask.call_args_list[0].args[3], "Jev route retry"))
        self.assertEqual((more.call_count, *pick(route, "workflow", "depth", "decided_by", "retry", "answers")), (1, "implement-then-test", "DEEP", "jev after retry", CALLERS, second["answers"]))

    def test_low_after_retry_falls_back_with_the_threshold(self):
        last = reply(depth=ans("DEEP", 0.75), workflow={"choice": "TEST_FIRST", "probabilities": {}})
        route, ask, _ = self.decide([reply(depth=ans("DEEP", 0.7), workflow=ans("TEST_FIRST", 0.9)), last], cfg={"route_threshold": 0.8})
        self.assertEqual((ask.call_count, *pick(route, "depth", "workflow", "decided_by", "fallback", "confidence", "answers")), (2, "STANDARD", "test-first", "fallback", "confidence below 0.8", 0.75, last["answers"]))
        route, _, _ = self.decide([reply(depth=ans("DEEP", 0.5))] * 2, state={**STATE, "pin": "implement-then-test"})
        self.assertEqual(pick(route, "workflow", "depth", "decided_by", "fallback"), ("implement-then-test", "STANDARD", "pin + fallback", "confidence below 0.6"))

    def test_jev_raising_falls_back_at_once_and_payment_propagates(self):
        route, ask, more = self.decide(RuntimeError("no key"))
        self.assertEqual((route, ask.call_count, more.call_count), ({"workflow": "test-first", "depth": "STANDARD", "decided_by": "fallback", "confidence": None, "answers": {},
                                 "retry": None, "fallback": "Jev unavailable: no key", "floor": [], "checks": []}, 1, 0))
        self.assertRaises(fc.fc_models.PaymentRequired, self.decide, fc.fc_models.PaymentRequired("typesafe", "top up"))


GATE = {"name": "Gate", "statement": "Verify decides what ships.", "globs": ["bin/x.py"], "checks": ["v"]}
TRIO = [{"name": "Secrets", "statement": "Keys.", "globs": [], "checks": ["t", "v"]}, {"name": "Docs", "statement": "Docs.", "globs": [], "checks": ["d"]},
        {"name": "Style", "statement": "Style.", "globs": [], "checks": ["t"]}]
SURE = {"depth": ans("FAST", 0.9), "workflow": ans("TEST_FIRST", 0.9)}


class Floor(unittest.TestCase):
    def decide(self, side_effect, matched=(), plain=()):
        with mock.patch.object(fc.fc_models, "jev_ask", side_effect=side_effect) as ask:
            return fc_routejev.decide({}, {}, STATE, list(matched), list(plain), mock.Mock(return_value=CALLERS)), ask.call_count

    def test_glob_match_and_applying_plain_policies_floor_deep_and_change_nothing_else(self):
        good = reply(**SURE, policy0=ans("DOES_NOT_APPLY", 0.6), policy1=ans("APPLIES", 0.9), policy2=ans("DOES_NOT_APPLY", 0.95))
        bare, _ = self.decide([good])
        self.assertEqual(pick(bare, "depth", "floor", "checks"), ("FAST", [], []))
        route, calls = self.decide([good], [GATE], TRIO)
        self.assertEqual((route, calls), ({**bare, "depth": "DEEP", "floor": ["Gate", "Docs"], "checks": ["v", "d"]}, 1))

    def test_floor_reads_the_last_reply_and_overrides_the_fallback(self):
        first = reply(**SURE, policy0=ans("APPLIES", 0.9), policy1=ans("DOES_NOT_APPLY", 0.4), policy2=ans("APPLIES", 0.9))
        last = reply(**SURE, policy0=ans("DOES_NOT_APPLY", 0.3), policy1=ans("DOES_NOT_APPLY", 0.9))
        route, calls = self.decide([first, last], [GATE], TRIO)
        self.assertEqual((calls, *pick(route, "fallback", "depth", "floor", "checks")),
                         (2, "confidence below 0.6", "DEEP", ["Gate", "Secrets", "Style"], ["v", "t"]))

    def test_jev_unavailable_plain_policies_keep_checks_but_set_no_floor(self):
        route, _ = self.decide(RuntimeError("no key"), plain=TRIO)
        self.assertEqual(pick(route, "depth", "floor", "checks", "fallback"), ("STANDARD", [], ["t", "v", "d"], "Jev unavailable: no key"))
        route, _ = self.decide(RuntimeError("no key"), [GATE], TRIO)
        self.assertEqual(pick(route, "depth", "floor", "checks"), ("DEEP", ["Gate"], ["v", "t", "d"]))
