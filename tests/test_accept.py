import hermetic  # first: no test sees the real home
import hashlib, importlib.machinery, importlib.util, json, os, unittest
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


KEYS = ["event_id", "run_id", "commit_sha", "task_ids", "criterion_id", "phase", "source", "result", "fails_on_base", "detail", "cites", "needs"]
N1 = {"choice": "test", "probabilities": {"test": 1.0}}


def row(eid, phase, result, cids=()):
    return {"event_id": eid, "criterion_id": list(cids), "phase": phase, "result": result}


class SufficiencyEvents(unittest.TestCase):
    def judge(self, rows, answers):
        events = fc_accept.sufficiency_events(META, rows, answers, 0.6, "run1", "sha1")
        self.assertEqual(len(events), 2)
        for e in events:
            d = {k: v for k, v in e.items() if k != "event_id"}
            self.assertEqual(list(e), KEYS)
            self.assertEqual(e["event_id"], hashlib.sha256(json.dumps(d, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12])
        return events

    def test_event_shape_and_cites_at_threshold_in_order(self):
        rows = [row("r1", "review", "pass"), row("r2", "acceptance", "pass", [C2]), row("r3", "e2e", "pass", [C1])]
        e1, e2 = self.judge(rows, {"v1": {"choice": "proven"}, "n1": N1, "e1_r1": {"noul": 0.7}, "e1_r3": {"noul": 0.5},
                                    "v2": {"choice": "contradicted"}, "e2_r1": {"noul": 0.6}, "e2_r2": {"noul": 0.9}})
        base = {"run_id": "run1", "commit_sha": "sha1", "task_ids": ["031"], "phase": "sufficiency", "source": "verify", "fails_on_base": None}
        self.assertEqual({k: v for k, v in e1.items() if k != "event_id"}, {**base, "criterion_id": [C1], "result": "proven", "detail": "alpha",
                                                                              "cites": ["r1"], "needs": fc_accept.sufficiency_needs(N1)})
        self.assertEqual({k: v for k, v in e2.items() if k != "event_id"}, {**base, "criterion_id": [C2], "result": "contradicted", "detail": "beta",
                                                                              "cites": ["r1", "r2"], "needs": fc_accept.sufficiency_needs(None)})

    def test_missing_or_unknown_verdict_is_unproven(self):
        rows = [row("r1", "review", "pass")]
        e1, e2 = self.judge(rows, {"v2": {"choice": "bogus"}, "e1_r1": {"noul": 1}, "e2_r1": {"noul": 1}})
        self.assertEqual((e1["result"], e2["result"], e1["cites"]), ("unproven", "unproven", ["r1"]))

    def test_deterministic_fail_unproves_and_joins_cites_once(self):
        rows = [row("f1", "attempt", "fail", [C1]), row("f2", "final", "fail", [C1]), row("f3", "review", "fail"), row("f4", "sufficiency", "fail", [C2]),
                row("f5", "acceptance", "fail"), row("p1", "e2e", "pass")]
        e1, e2 = self.judge(rows, {"v1": {"choice": "proven"}, "e1_f1": {"noul": 1}, "e1_f3": {"noul": 1}, "e1_p1": {"noul": 1},
                                    "v2": {"choice": "proven"}, "e2_p1": {"noul": 1}})
        self.assertEqual((e1["result"], e1["cites"]), ("unproven", ["f1", "f3", "p1", "f2"]))
        self.assertEqual((e2["result"], e2["cites"]), ("proven", ["p1"]))

    def test_deterministic_fail_does_not_change_other_verdicts(self):
        e1, e2 = self.judge([row("f1", "checks", "fail")], {"v1": {"choice": "contradicted"}, "v2": {"choice": "unproven"}})
        self.assertEqual((e1["result"], e1["cites"], e2["result"]), ("contradicted", [], "unproven"))

    def test_proven_needs_a_cited_row_other_than_error(self):
        rows = [row("x1", "checks", "error"), row("p1", "e2e", "pass", [C1])]
        e1, e2 = self.judge(rows, {"v1": {"choice": "proven"}, "e1_x1": {"noul": 1}, "e1_p1": {"noul": 1}, "v2": {"choice": "proven"}, "e2_x1": {"noul": 1}})
        self.assertEqual((e1["result"], e2["result"], e2["cites"]), ("proven", "unproven", ["x1"]))
        self.assertEqual(self.judge([], {"v1": {"choice": "proven"}, "v2": {"choice": "contradicted"}})[0]["result"], "unproven")
