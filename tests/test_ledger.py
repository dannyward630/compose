import hermetic  # first: no test sees the real home
import hashlib, importlib.machinery, importlib.util, io, json, os, re, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import sys
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_ledger, fc_evidence  # noqa: E402


class Events(unittest.TestCase):
    ARGS = ("a1b2c3d4e5f6", "abc", ["003"], ["003.1:12345678"], "attempt", "run", "fail", None, "boom")

    def test_event_has_the_keys_in_order_and_a_stable_id(self):
        self.assertEqual(fc_ledger.KEYS, ("event_id", "run_id", "commit_sha", "task_ids", "criterion_id", "phase", "source", "result", "fails_on_base", "detail"))
        e = fc_ledger.event(*self.ARGS)
        self.assertEqual(list(e), list(fc_ledger.KEYS))
        rest = {k: v for k, v in e.items() if k != "event_id"}
        self.assertEqual(e["event_id"], hashlib.sha256(json.dumps(rest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12])
        self.assertEqual(fc_ledger.event(*self.ARGS), e)
        for i, other in enumerate(("r", "sha", ["004"], [], "final", "prove", "pass", True, "bang")):
            self.assertNotEqual(fc_ledger.event(*(self.ARGS[:i] + (other,) + self.ARGS[i + 1:]))["event_id"], e["event_id"], i)

    def test_event_stores_lists(self):
        e = fc_ledger.event("r", "", ("003", "004"), ("003.1:12345678",), "red", "run", "pass", False, "d")
        self.assertEqual((e["task_ids"], e["criterion_id"], e["fails_on_base"]), (["003", "004"], ["003.1:12345678"], False))

    def test_detail_is_scrubbed_one_line_and_cut(self):
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-secret-value-123"}):
            d = fc_ledger.event(*self.ARGS[:8], "  FAIL\n\tsk-secret-value-123 \r\n x  ")["detail"]
        self.assertEqual(d, "FAIL <redacted> x")
        long = fc_ledger.event(*self.ARGS[:8], "a\n\n b" * 200)["detail"]
        self.assertEqual((len(long), "\n" in long, "  " in long), (160, False, False))

    def test_criterion_ids_number_and_hash_each_criterion(self):
        sha = lambda t: hashlib.sha256(t.encode()).hexdigest()[:8]
        body = lambda c: "## Goal\nx\n\n## Acceptance criteria\n* works\n  * sub\n* " + c + "\n\n## Test plan\ny"
        ids = fc_ledger.criterion_ids({"id": "003", "body": body("fast")})
        self.assertEqual(ids, [f"003.1:{sha('works; sub')}", f"003.2:{sha('fast')}"])
        edited = fc_ledger.criterion_ids({"id": "003", "body": body("faster")})
        self.assertEqual((edited[0], edited[1] != ids[1], edited[1][:6]), (ids[0], True, "003.2:"))

    def test_run_id_is_kept_minted_and_replaced_on_fresh(self):
        proj = Path(tempfile.mkdtemp()) / "feat"
        proj.mkdir()
        a = fc_ledger.run_id(proj, "003")
        self.assertRegex(a, r"^[0-9a-f]{12}$")
        self.assertEqual(fc_ledger.run_id(proj, "003"), a)
        other = fc_ledger.run_id(proj, "004")
        fresh = fc_ledger.run_id(proj, "003", fresh=True)
        self.assertRegex(fresh, r"^[0-9a-f]{12}$")
        self.assertNotEqual(fresh, a)
        self.assertEqual(json.loads((proj / "results" / "runs.json").read_text()), {"003": fresh, "004": other})
        self.assertEqual(fc_ledger.run_id(proj, "003"), fresh)
