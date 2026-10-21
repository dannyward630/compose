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


def row(n, phase="attempt", source="run"):
    return {"event_id": f"{n:012x}", "run_id": "r", "commit_sha": "", "task_ids": ["003"], "criterion_id": [], "phase": phase,
            "source": source, "result": "fail", "fails_on_base": None, "detail": f"d{n}"}


class AddRow(unittest.TestCase):
    def setUp(self):
        self.calls, self.comments, self.fail, self.err, self.said = [], [], 0, "boom", []

        def gql(query, variables):
            self.calls.append(variables)
            if "commentCreate" not in query:
                return {"issue": {"id": "uuid-" + variables["id"], "identifier": variables["id"]}}
            if self.fail:
                self.fail -= 1
                raise RuntimeError(self.err)
            self.comments.append(variables["b"])
        for mod, name, value in ((fc.fc_config, "LINEAR_KEY", "lin_api_x"), (fc.fc_linear, "linear_gql", gql), (fc_ledger, "UNSAVED", []),
                                 (fc_ledger, "SAVED", set()), (fc.fc_core, "say", self.said.append)):
            p = mock.patch.object(mod, name, value); p.start(); self.addCleanup(p.stop)
        p = mock.patch("time.sleep"); self.sleep = p.start(); self.addCleanup(p.stop)

    def test_one_comment_holds_every_row_in_the_exact_text(self):
        rows = [row(1, "red"), row(2), row(3), row(4, "final", "prove")]
        self.assertTrue(fc_ledger.add_row("NEB-1", rows))
        self.assertEqual(self.comments[0].splitlines(), ["Evidence: run red, attempt, final", "", "```evidence", *map(json.dumps, rows), "```"])
        self.assertEqual((len(self.comments), self.calls[-1]["id"]), (1, "uuid-NEB-1"))

    def test_three_failed_tries_say_the_line_and_keep_the_rows_for_the_next_call(self):
        self.fail, self.err = 3, "x" * 300
        a, b, c = row(1), row(2), row(3)
        self.assertFalse(fc_ledger.add_row("NEB-1", [a, b]))
        self.assertEqual((len(self.calls) - 1, [c.args for c in self.sleep.call_args_list], fc_ledger.unsaved()), (3, [(2,), (2,)], [a, b]))
        self.assertEqual(self.said[-1], f"ledger NEB-1: evidence not saved after 3 tries, kept in memory: {a['event_id']}, {b['event_id']} ({'x' * 200})")
        self.assertTrue(fc_ledger.add_row("NEB-2", [c]))
        self.assertEqual((fc_ledger.unsaved(), self.comments[-1]), ([a, b], fc_ledger.comment_text([c])))
        self.assertTrue(fc_ledger.add_row("NEB-1", [c]))
        self.assertEqual((fc_ledger.unsaved(), self.comments[-1]), ([], fc_ledger.comment_text([a, b, c])))

    def test_a_late_success_saves_and_a_saved_row_is_never_written_again(self):
        self.fail = 2
        a, b = row(1), row(2)
        self.assertTrue(fc_ledger.add_row("NEB-1", [a, a]))
        self.assertEqual((self.comments, fc_ledger.unsaved(), self.said), ([fc_ledger.comment_text([a])], [], []))
        self.assertTrue(fc_ledger.add_row("NEB-1", [a, b]))
        self.assertTrue(fc_ledger.add_row("NEB-1", [a, b]))
        self.assertEqual(self.comments[1:], [fc_ledger.comment_text([b])])

    def test_no_key_or_no_issue_writes_nothing_and_keeps_nothing(self):
        with mock.patch.object(fc.fc_config, "LINEAR_KEY", None):
            self.assertTrue(fc_ledger.add_row("NEB-1", [row(1)]))
        self.assertTrue(fc_ledger.add_row("", [row(1)]))
        self.assertEqual((self.calls, fc_ledger.unsaved()), ([], []))

    def test_record_refreshes_only_when_the_write_succeeded(self):
        with mock.patch.object(fc_evidence, "refresh") as refresh:
            self.fail = 3
            self.assertFalse(fc_ledger.record("NEB-1", [row(1)]))
            refresh.assert_not_called()
            self.assertTrue(fc_ledger.record("NEB-1", [row(2)]))
            refresh.assert_called_once_with("NEB-1")
