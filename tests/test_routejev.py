import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, json, os, sys, unittest
from pathlib import Path
from unittest import mock
os.environ.update(COMPOSE_NO_TREEHOUSE="1", HERDR_ENV="")
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
        self.assertEqual(route, {"workflow": "fix-then-regression-test", "depth": "STANDARD", "decided_by": "jev", "confidence": 0.6,
                                 "answers": good["answers"], "retry": None, "fallback": None, "floor": [], "checks": []})
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
