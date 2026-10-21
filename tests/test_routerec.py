import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, os, sys, unittest
from pathlib import Path
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_routerec  # noqa: E402  compose.py does not import it, so reach it from bin/ on sys.path

DEPTH = {"choice": "STANDARD", "probabilities": {"STANDARD": 0.72, "DEEP": 0.2, "FAST": 0.08}, "confidence": 0.65}
FLOW = {"choice": "TEST_FIRST", "probabilities": {"TEST_FIRST": 0.81, "IMPLEMENT_THEN_TEST": 0.19}, "confidence": 0.7}
NO_BUG = {"label": False, "documented": False, "confirmed": False}


def route(**kv):
    return {"workflow": "test-first", "depth": "STANDARD", "decided_by": "jev", "confidence": 0.65, "answers": {"depth": DEPTH, "workflow": FLOW},
            "retry": None, "fallback": None, "floor": [], "checks": [], **kv}


def state(files, criteria, other=(), bug=NO_BUG, pin=None):
    return {"task": "T", "criteria": [f"c{i}" for i in range(criteria)], "files": [{"path": p, "top": p.split("/")[0], "exists": e} for p, e in files],
            "other_files": sorted(other), "story": None, "bug": bug, "pin": pin}


class Reason(unittest.TestCase):
    def test_jev_choices_and_floor_after_jevs_own_depth(self):
        r = route(depth="DEEP", floor=["Verification gate", "Secrets"])
        s = state([("bin/x.py", True), ("tests/test_x.py", False)], 3, other=["bin/x.py", "src/y.py"])
        self.assertEqual(fc_routerec.route_reason(r, s), "Jev: depth STANDARD (p 0.72, confidence 0.65), workflow test-first (p 0.81, confidence 0.70); "
                         "2 files under bin, tests (1 new), 3 criteria, 1 shared with other open tasks; no Bug label; floor DEEP from Verification gate, Secrets")

    def test_jev_pinned_after_retry_with_bug_and_note(self):
        fast = {"choice": "FAST", "probabilities": {"FAST": 0.9, "STANDARD": 0.1}, "confidence": 0.8}
        r = route(workflow="implement-then-test", depth="FAST", answers={"depth": fast}, retry={"callers": {"bin/x.py": ["bin/y.py"]}}, note="policies unavailable: no Linear key")
        s = state([("bin/x.py", True)], 1, bug={"label": True, "documented": True, "confirmed": True}, pin="implement-then-test")
        self.assertEqual(fc_routerec.route_reason(r, s), "Jev: depth FAST (p 0.90, confidence 0.80), workflow implement-then-test pinned after a retry with dependency analysis; "
                         "1 file under bin (0 new), 1 criterion, 0 shared with other open tasks; Bug label, reproduction documented, confirmed; policies unavailable: no Linear key")

    def test_fallback_with_no_files_and_empty_note(self):
        r = route(decided_by="fallback", confidence=None, answers={}, fallback="Jev unavailable: timeout", note="")
        s = state([], 0, other=["a.py"], bug={"label": True, "documented": False, "confirmed": False})
        self.assertEqual(fc_routerec.route_reason(r, s), "fallback STANDARD test-first: Jev unavailable: timeout; "
                         "0 files (0 new), 0 criteria, 0 shared with other open tasks; Bug label, reproduction not documented, not confirmed")

    def test_fallback_pinned_after_retry_without_dependencies(self):
        low = {"choice": "DEEP", "probabilities": {"DEEP": 0.4}, "confidence": 0.3}
        r = route(workflow="fix-then-regression-test", decided_by="pin + fallback", confidence=0.3, answers={"depth": low}, retry={"unavailable": "trail missing"}, fallback="confidence below 0.6")
        s = state([("tests/a.py", False), ("bin/b.py", True), ("tests/c.py", False)], 2, other=["bin/b.py", "tests/c.py", "z.py"], pin="fix-then-regression-test")
        self.assertEqual(fc_routerec.route_reason(r, s), "fallback STANDARD fix-then-regression-test pinned: confidence below 0.6 after a retry, dependency analysis unavailable; "
                         "3 files under tests, bin (2 new), 2 criteria, 2 shared with other open tasks; no Bug label")


if __name__ == "__main__":
    unittest.main()
