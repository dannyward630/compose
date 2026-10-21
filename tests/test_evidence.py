import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, json, os, unittest
from pathlib import Path
from unittest import mock
import sys
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_evidence  # noqa: E402

QUERY = "query($id: String!, $after: String) { issue(id: $id) { comments(first: 100, after: $after) { pageInfo { hasNextPage endCursor } nodes { body createdAt } } } }"


def row(eid, **kv): return {"event_id": eid, "run_id": "r1", "commit_sha": "", "task_ids": ["001"], "criterion_id": [], "phase": "red", "source": "run",
            "result": "fail", "fails_on_base": None, "detail": "d", **kv}
def comment(at, *rows, junk=""):
    return {"body": "Evidence: run\n\n```evidence\n" + "\n".join(map(json.dumps, rows)) + junk + "\n```", "createdAt": at}
def page(nodes, cursor=None): return {"issue": {"comments": {"pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor}, "nodes": nodes}}}


class Rows(unittest.TestCase):
    def read(self, pages, **kw):
        gql = mock.Mock(side_effect=pages)
        with mock.patch.object(fc.fc_config, "LINEAR_KEY", "lin_api_x"), mock.patch.object(fc.fc_linear, "linear_gql", gql):
            return fc_evidence.rows("ENG-4", **kw), gql

    def test_parse_comment_reads_every_block_and_skips_other_lines(self):
        body = 'hi\n```evidence\n{"event_id": "a"}\n\nnot json\n[1]\n{"event_id": "b"}\n```\ntext\n```evidence\n{"event_id": "c"}\n```\n```python\n{"event_id": "d"}\n```'
        self.assertEqual(fc_evidence.parse_comment(body), [{"event_id": "a"}, {"event_id": "b"}, {"event_id": "c"}])

    def test_reads_every_page_once_per_event_oldest_first_with_at(self):
        a, b, c = row("a"), row("b"), row("c")
        got, gql = self.read([page([comment("2026-10-21T12:00:00.000Z", a), comment("2026-10-21T13:00:00.000Z", b)], "c1"),
                              page([comment("2026-10-21T09:00:00.000Z", c, junk="\nnot json"), comment("2026-10-21T08:00:00.000Z", a)])])
        self.assertEqual([(r["event_id"], r["at"]) for r in got], [("c", "2026-10-21T09:00:00.000Z"), ("a", "2026-10-21T12:00:00.000Z"), ("b", "2026-10-21T13:00:00.000Z")])
        self.assertEqual([c.args for c in gql.call_args_list], [(QUERY, {"id": "ENG-4", "after": None}), (QUERY, {"id": "ENG-4", "after": "c1"})])

    def test_filters_keep_matching_rows_and_empty_lists_match_any(self):
        rs = [row("a", task_ids=["001"], criterion_id=["001.1:aa"]), row("b", task_ids=["002"], criterion_id=["002.1:bb", "002.2:cc"], run_id="r2"),
              row("c", task_ids=[], criterion_id=[])]
        nodes = [comment("2026-10-21T0%d:00:00.000Z" % i, r) for i, r in enumerate(rs)]
        ids = lambda **kw: [r["event_id"] for r in self.read([page(nodes)], **kw)[0]]
        self.assertEqual(ids(), ["a", "b", "c"])
        self.assertEqual(ids(task_id="001"), ["a", "c"])
        self.assertEqual(ids(run_id="r2"), ["b"])
        self.assertEqual(ids(criterion_id="002.2:cc"), ["b", "c"])
        self.assertEqual(ids(task_id="002", criterion_id="001.1:aa"), ["c"])

    def test_empty_issue_or_no_key_reads_nothing_and_linear_errors_raise(self):
        gql = mock.Mock(side_effect=RuntimeError("boom"))
        with mock.patch.object(fc.fc_linear, "linear_gql", gql):
            for key, issue in (("lin_api_x", ""), (None, "ENG-4")):
                with mock.patch.object(fc.fc_config, "LINEAR_KEY", key): self.assertEqual(fc_evidence.rows(issue), [])
            gql.assert_not_called()
            with mock.patch.object(fc.fc_config, "LINEAR_KEY", "lin_api_x"), self.assertRaises(RuntimeError): fc_evidence.rows("ENG-4")
