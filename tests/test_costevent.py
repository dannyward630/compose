import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, json, os, sys, tempfile, unittest
from pathlib import Path
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_costevent

TASKS = [{"id": "001", "linear": "XX-1"}, {"id": "002", "linear": "XX-2", "kind": "design"}, {"id": "003", "linear": "XX-3"}]
ROUTE = "## Route\n\n* workflow: test-first\n* depth: FAST\n"


class VerifyEvents(unittest.TestCase):
    def project(self, rounds):
        proj = Path(tempfile.mkdtemp()) / ".compose" / "p"
        (proj / "results").mkdir(parents=True)
        (proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": TASKS, "issues": {"XX-1": {"description": ROUTE}, "XX-2": {"description": ROUTE}}}))
        if rounds is not None: (proj / "results" / "verify.json").write_text(json.dumps({"rounds": rounds}))
        return proj

    def events(self, rounds, passed=True):
        return fc_costevent.verify_events(self.project(rounds), TASKS, passed, 0.25, "run-1", "abc123")

    def numbers(self, e):
        return [e["task_ids"], e["workflow"], e["depth"], e["attempts"], e["escalations"], e["fix_rounds"], e["cost"]]

    def test_task_events_then_verify_event(self):
        rounds = [{"fix_tasks": ["001"]}, {}, {"fix_tasks": ["001", "003"]}, {"fix_tasks": []}]
        evs = self.events(rounds)
        self.assertEqual([self.numbers(e) for e in evs], [
            [["001"], "test-first", "FAST", 0, 0, 2, 0.0],
            [["003"], "-", "-", 0, 0, 1, 0.0],
            [["001", "003"], "-", "-", 0, 0, 3, 0.25]])
        for e in evs:
            self.assertEqual((e["phase"], e["source"], e["result"], e["run_id"], e["commit_sha"], e["criterion_id"]), ("cost", "verify", "pass", "run-1", "abc123", []))

    def test_failed_verify_records_fail(self):
        self.assertEqual({e["result"] for e in self.events([], passed=False)}, {"fail"})

    def test_no_fix_rounds_are_zero(self):
        for rounds in (None, [{}, {"stage": "smoke"}]):
            self.assertEqual([e["fix_rounds"] for e in self.events(rounds)], [0, 0, 0])
