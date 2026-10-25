import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, io, json, os, sys, tempfile, unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)

URL = "https://linear.app/acme/project/my-shop-abc123"


def issue(ident, state="Todo", labels=("Story",), parent=None):
    return {"id": ident, "title": f"{ident} title", "state": state, "labels": list(labels), "parent": parent}


def node(i):
    return {"identifier": i["id"], "title": i["title"], "state": {"name": i["state"]}, "labels": {"nodes": [{"name": l} for l in i["labels"]]}, "parent": {"identifier": i["parent"]} if i["parent"] else None}


def sheet(keep=(), verify=(), cancel_subtree=None, tickets=(), reasons=None, new=()):
    t = list(tickets) + ([{"id": cancel_subtree, "sort": "cancel", "reason": "appux", "subtree": True}] if cancel_subtree else [])
    return {"keep": list(keep), "verify": list(verify), "tickets": t, "reasons": {"appux": "App UI and UX was a mistake.", "dup": "A duplicate."} if reasons is None else reasons, "new": list(new)}


class FakeLinear:
    def __init__(self):
        self.pages, self.queries, self.mutations = [], [], []

    def gql(self, query, variables):
        self.queries.append(query)
        if "projects(" in query:
            return {"projects": {"nodes": [{"id": "p1", "name": "Shop", "url": URL, "teams": {"nodes": [{"id": "t1", "name": "Engineering", "key": "NEB"}]}}]}}
        if "mutation" in query:
            self.mutations.append(query)
            return {}
        n = int(variables["after"][1:]) + 1 if variables["after"] else 1
        page = self.pages[n - 1]
        return {"issues": {"pageInfo": {"hasNextPage": n < len(self.pages), "endCursor": f"c{n}"}, "nodes": [node(i) for i in page]}}

    def list_query(self):
        return next(q for q in self.queries if "issues(" in q)


class Reconcile(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp()).resolve()
        (self.repo / ".compose").mkdir()
        (self.repo / ".compose" / "linear.json").write_text(json.dumps({"project": URL, "team": "Engineering"}))
        self.tmp = Path(tempfile.mkdtemp())
        self.linear = FakeLinear()
        self.issues = [issue("NEB-1", labels=("Epic",)), issue("NEB-2", labels=("Feature",), parent="NEB-1"), issue("NEB-3", parent="NEB-2"),
                       issue("NEB-4", parent="NEB-2"), issue("NEB-5", parent="NEB-2")]
        self.issues[2]["labels"] = ["Story", "Ready"]
        self.linear.pages = [self.issues]
        for mod, name, value in ((fc.fc_config, "LINEAR_KEY", "lin_api_x"), (fc.fc_linear, "linear_gql", self.linear.gql)):
            p = mock.patch.object(mod, name, value); p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(Path, "home", return_value=self.tmp); p.start(); self.addCleanup(p.stop)

    def args(self, action, **kw):
        return SimpleNamespace(repo=str(self.repo), action=action, file=kw.get("file"), go=None)

    def out(self, action, **kw):
        out = io.StringIO()
        with redirect_stdout(out):
            fc.fc_reconcile.cmd_reconcile(self.args(action, **kw))
        return out.getvalue().splitlines()

    def fails(self, action, **kw):
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as e:
            fc.fc_reconcile.cmd_reconcile(self.args(action, **kw))
        code = e.exception.code
        return (1 if isinstance(code, str) else code), ((code if isinstance(code, str) else "") + err.getvalue()).strip()

    def write(self, name, text):
        p = self.tmp / name
        p.write_text(text)
        return str(p)

    def sheet(self, raw=None):
        raw = raw or {"keep": ["NEB-1"], "verify": ["NEB-3"],
                      "tickets": [{"id": "NEB-2", "sort": "cancel", "reason": "appux", "subtree": True}, {"id": "NEB-4", "sort": "merge", "into": "NEB-3", "reason": "dup"}],
                      "reasons": {"appux": self.write("appux.md", "App UI and UX was a mistake."), "dup": self.write("dup.md", "A duplicate.")},
                      "new": [{"key": "N1", "title": "So far: the draft report and its evidence", "parent": "NEB-1", "label": "Feature", "body": self.write("b.md", "Body.")}]}
        return self.write("sheet.json", json.dumps(raw))

    def stored(self, in_progress=None):
        self.issues = [dict(i, state="In Progress" if i["id"] == in_progress else i["state"]) for i in self.issues]
        s = sheet(keep=["NEB-1"], verify=["NEB-3"],
                  tickets=[{"id": "NEB-4", "sort": "merge", "into": "NEB-3", "reason": "dup"}], cancel_subtree="NEB-2",
                  new=[{"key": "N1", "title": "So far: the draft report and its evidence", "parent": "NEB-1", "label": "Feature", "body": "Body.", "deep_dive": False}])
        s["tickets"].append({"id": "NEB-3", "sort": "keep", "title": "RS1. Chat with the Guide", "drop_ready": True, "reason": "dup", "deep_dive": True})
        s["verify"] = ["NEB-6"]
        self.issues = self.issues + [issue("NEB-6", parent="NEB-1")]
        return {**s, "issues": self.issues}

    def test_list_prints_every_open_ticket_as_a_tree_from_every_page(self):
        self.linear.pages = [[issue("NEB-1", labels=("Epic",)), issue("NEB-3", parent="NEB-2")], [issue("NEB-2", labels=("Feature",), parent="NEB-1")]]
        self.assertEqual(self.out("list"), ["NEB-1 Todo Epic NEB-1 title", "  NEB-2 Todo Feature NEB-2 title", "    NEB-3 Todo Story NEB-3 title"])
        self.assertIn('state: {type: {nin: ["completed", "canceled"]}}', self.linear.list_query())

    def test_a_good_sheet_is_stored_with_its_reason_texts_and_the_check_says_so(self):
        out = self.out("check", file=self.sheet())
        self.assertEqual(out[-1], "checked: 5 open tickets sorted (1 kept, 1 to verify, 2 canceled, 1 merged), 1 new; compose reconcile show prints the proposal")
        stored = json.loads(fc.fc_reconcile.sheet_path("p1").read_text())
        self.assertEqual((stored["reasons"]["appux"], stored["applied"], stored["go"], stored["project"]["name"]), ("App UI and UX was a mistake.", {}, [], "Shop"))

    def test_every_open_ticket_is_sorted_exactly_once(self):
        problems = fc.fc_reconcile.check_sheet(sheet(keep=["NEB-1", "NEB-1"]), self.issues)
        self.assertIn("NEB-1 is sorted twice", problems)
        self.assertIn("NEB-4 is open and not sorted", problems)

    def test_a_subtree_cancel_stops_at_a_descendant_sorted_on_its_own(self):
        got = fc.fc_reconcile.expand(sheet(cancel_subtree="NEB-2", verify=["NEB-3"]), self.issues)
        self.assertEqual((got["NEB-3"]["sort"], got["NEB-5"]["sort"], got["NEB-5"]["under"]), ("verify", "cancel", "NEB-2"))

    def test_a_subtree_cancel_does_not_walk_past_a_kept_or_verified_ticket(self):
        issues = self.issues + [issue("NEB-6", parent="NEB-3"), issue("NEB-7", parent="NEB-4")]
        s = sheet(keep=["NEB-1", "NEB-3"], verify=["NEB-4"], cancel_subtree="NEB-2")
        got = fc.fc_reconcile.expand(s, issues)
        self.assertEqual((got["NEB-5"]["sort"], "NEB-6" in got, "NEB-7" in got), ("cancel", False, False))
        problems = fc.fc_reconcile.check_sheet(s, issues)
        self.assertIn("NEB-6 is open and not sorted", problems)
        self.assertIn("NEB-7 is open and not sorted", problems)

    def test_a_sheet_that_is_not_json_or_has_an_entry_without_an_id_exits_with_a_message(self):
        self.assertEqual(self.fails("check", file=self.write("bad.json", "{nope")), (1, f"sheet {self.tmp / 'bad.json'}: not valid JSON (Expecting property name enclosed in double quotes: line 1 column 2 (char 1))"))
        raw = {"tickets": [{"sort": "keep"}]}
        self.assertEqual(self.fails("check", file=self.write("noid.json", json.dumps(raw))), (1, "sheet: a tickets entry has no id: {'sort': 'keep'}"))

    def test_a_sheet_of_the_wrong_shape_exits_with_a_message_not_a_traceback(self):
        for raw, msg in (({"keep": "NEB-1"}, "sheet: keep must be a list"), ({"verify": {"a": 1}}, "sheet: verify must be a list"),
                         ({"tickets": "NEB-1"}, "sheet: tickets must be a list"), ({"keep": [3]}, "sheet: a keep entry must be a ticket id like NEB-12: 3"),
                         ({"verify": [["NEB-1"]]}, "sheet: a verify entry must be a ticket id like NEB-12: ['NEB-1']"),
                         ({"tickets": ["NEB-1"]}, "sheet: a tickets entry must be an object with an id: 'NEB-1'"),
                         ({"reasons": ["x"]}, "sheet: reasons must map a reason name to the path of its text file"),
                         ({"reasons": {"x": 4}}, "sheet: reason x must be the path of a text file: 4"),
                         ({"new": ["N1"]}, "sheet: a new entry must be an object with a key: 'N1'"),
                         ({"new": [{"title": "t"}]}, "sheet: a new entry must be an object with a key: {'title': 't'}"),
                         ({"new": [{"key": "N1", "body": 5}]}, "sheet: new N1 body must be the path of a text file: 5")):
            self.assertEqual(self.fails("check", file=self.write("s.json", json.dumps(raw))), (1, msg))

    def test_check_refuses_bad_entries_and_stores_nothing(self):
        bad = {"tickets": [{"id": "NEB-9", "sort": "keep"}, {"id": "NEB-4", "sort": "merge", "into": "NEB-2", "reason": "dup"},
                           {"id": "NEB-1", "sort": "cancel"}, {"id": "NEB-5", "sort": "verify", "title": "x"}, {"id": "NEB-3", "sort": "keep", "drop_ready": True, "reason": "r"}]}
        problems = fc.fc_reconcile.check_sheet(sheet(**bad, cancel_subtree="NEB-2"), self.issues)
        for p in ("NEB-9 is not an open ticket of this project", "NEB-4 merges into NEB-2, which this sheet cancels",
                  "NEB-1 is canceled without a reason", "NEB-5 is sorted verify: it takes no changes", "reason r has no text"):
            self.assertIn(p, problems)
        self.assertEqual(self.fails("check", file=self.sheet({**bad, "reasons": {}, "cancel": []})), (1, "\n".join(fc.fc_reconcile.check_sheet(sheet(**bad, reasons={}), self.issues))))
        self.assertFalse(fc.fc_reconcile.sheet_path("p1").exists())

    def test_drop_ready_needs_the_ready_label_and_new_tickets_need_a_real_parent_and_label(self):
        self.issues[2]["labels"] = ["Story"]
        s = sheet(keep=["NEB-1", "NEB-2", "NEB-4", "NEB-5"], tickets=[{"id": "NEB-3", "sort": "keep", "drop_ready": True, "reason": "dup"}],
                  new=[{"key": "N1", "title": "t", "parent": "NEB-4", "label": "Task"}, {"key": "N2", "title": "t", "parent": "N1", "label": "Story"}])
        s["new"][0]["parent"] = "NEB-9"
        problems = fc.fc_reconcile.check_sheet(s, self.issues)
        self.assertIn("NEB-3 drops Ready but does not carry it", problems)
        self.assertTrue(any(p.startswith("new N1 has parent NEB-9") for p in problems))
        self.assertTrue(any(p.startswith("new N1 has label 'Task'") for p in problems))
        self.assertFalse(any(p.startswith("new N2") for p in problems))

    def test_a_missing_reason_file_exits_naming_it_and_a_half_applied_sheet_is_not_replaced(self):
        raw = {"keep": [], "tickets": [], "reasons": {"x": "/nope/x.md"}}
        self.assertEqual(self.fails("check", file=self.write("s.json", json.dumps(raw)))[1], "reason x: no file /nope/x.md")
        self.out("check", file=self.sheet())
        path = fc.fc_reconcile.sheet_path("p1")
        stored = json.loads(path.read_text()); stored["applied"] = {"NEB-2": "x"}; path.write_text(json.dumps(stored))
        code, msg = self.fails("check", file=self.sheet())
        self.assertTrue(msg.startswith("a reconcile is half applied (1 of 5): finish it with compose reconcile apply --go"), msg)

    def test_show_without_a_stored_sheet_says_how_to_get_one(self):
        self.assertEqual(self.fails("show"), (1, "no checked reconcile for Shop: compose reconcile check --file <sheet> first"))

    def test_proposal_sections_in_order_with_reasons_grouped_and_running_work_named(self):
        text = fc.fc_reconcile.render_proposal(self.stored(in_progress="NEB-5"))
        self.assertEqual([l for l in text.splitlines() if l.startswith("## ")],
                         ["## Cancel", "## Merge", "## Running work this stops", "## Rename", "## Ready removed (needs shaping)",
                          "## Label deep-dive", "## New tickets", "## Left for you to verify", "## Keep"])
        self.assertTrue(text.startswith("6 open tickets: 2 kept, 1 left for you to verify, 2 canceled, 1 merged; 1 new.\n"))
        self.assertIn("App UI and UX was a mistake.\n\n- NEB-2 NEB-2 title, and the 1 open ticket under it", text)
        self.assertIn("- NEB-4 NEB-4 title, into NEB-3 NEB-3 title", text)
        self.assertIn("- NEB-5 NEB-5 title (In Progress)", text)
        self.assertIn('- NEB-3: "NEB-3 title" becomes "RS1. Chat with the Guide"', text)
        self.assertIn("- N1 So far: the draft report and its evidence (Feature under NEB-1, needs shaping)", text)
        self.assertNotIn(chr(0x2014), text)

    def test_show_prints_the_stored_proposal(self):
        self.out("check", file=self.sheet())
        self.assertTrue(self.out("show")[0].startswith("5 open tickets: 1 kept, 1 left for you to verify, 2 canceled, 1 merged; 1 new."))


if __name__ == "__main__":
    unittest.main()
