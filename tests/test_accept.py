import hermetic  # first: no test sees the real home
import hashlib, importlib.machinery, importlib.util, os, unittest
from pathlib import Path
import sys
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_accept  # noqa: E402

VERDICTS = ("proven", "unproven", "contradicted")
NEEDS = ("test", "prove", "check", "e2e", "review", "acceptance", "manual", "none")
META = {"id": "031", "title": "t", "body": "## Acceptance criteria\n* alpha\n* beta\n"}
C1, C2 = (f"031.{n}:{hashlib.sha256(t.encode()).hexdigest()[:8]}" for n, t in ((1, "alpha"), (2, "beta")))


class SufficiencyQuestions(unittest.TestCase):
    def test_questions_per_criterion_and_row(self):
        rows = [{"event_id": "x1", "criterion_id": [C1]}, {"event_id": "x2", "criterion_id": [C2]}, {"event_id": "x3", "criterion_id": []},
                {"event_id": "x4", "criterion_id": [C2, C1]}]
        qs = fc_accept.sufficiency_questions(META, rows)
        self.assertEqual(list(qs), ["v1", "n1", "e1_x1", "e1_x3", "e1_x4", "v2", "n2", "e2_x2", "e2_x3", "e2_x4"])
        for n, text in ((1, "alpha"), (2, "beta")):
            self.assertEqual(qs[f"v{n}"]["type"], "choice")
            self.assertEqual(list(qs[f"v{n}"]["criteria"]), list(VERDICTS))
            self.assertEqual(qs[f"n{n}"]["type"], "choice")
            self.assertEqual(list(qs[f"n{n}"]["criteria"]), list(NEEDS))
            self.assertLessEqual({"031", text}, set(qs[f"v{n}"]["instructions"].values()))
        for name, event_id in (("e1_x1", "x1"), ("e2_x4", "x4")):
            self.assertEqual(qs[name]["type"], "noul")
            self.assertTrue({"031", event_id} <= set(qs[name]["instructions"].values()))
        self.assertIn("alpha", qs["e1_x3"]["instructions"].values())
        self.assertIn("beta", qs["e2_x3"]["instructions"].values())

    def test_no_rows_asks_only_verdict_and_needs(self):
        self.assertEqual(list(fc_accept.sufficiency_questions(META, [])), ["v1", "n1", "v2", "n2"])

    def test_needs_adds_likely_values_in_order(self):
        needs = fc_accept.sufficiency_needs
        self.assertEqual(needs({"choice": "test", "probabilities": {"test": 0.9, "e2e": 0.25, "review": 0.24}}), ["test", "e2e"])
        self.assertEqual(needs({"choice": "review", "probabilities": {"test": 0.5, "check": 0.3, "prove": 0.1}}), ["test", "check", "review"])

    def test_needs_drops_none_beside_another_value(self):
        needs = fc_accept.sufficiency_needs
        self.assertEqual(needs({"choice": "none", "probabilities": {"none": 0.6, "test": 0.3}}), ["test"])
        self.assertEqual(needs({"choice": "test", "probabilities": {"none": 0.9}}), ["test"])
        self.assertEqual(needs({"choice": "none", "probabilities": {"none": 0.9}}), ["none"])

    def test_needs_reads_a_missing_or_unknown_choice_as_manual(self):
        needs = fc_accept.sufficiency_needs
        self.assertEqual(needs(None), ["manual"])
        self.assertEqual(needs({"choice": "bogus", "probabilities": {}}), ["manual"])
        self.assertEqual(needs({"choice": "bogus", "probabilities": {"test": 0.5}}), ["test", "manual"])
