import importlib.machinery, importlib.util, io, json, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast_coding.py")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)

KEY = "lin_api_SECRET_do_not_print"
STATES = [{"id": f"s-{n}", "name": n, "type": t} for n, t in
          (("Todo", "unstarted"), ("In Progress", "started"), ("In Review", "started"), ("Done", "completed"))]


class FakeLinear:
    """Linear's GraphQL API in memory: feature ENG-1 > story ENG-2 > tasks ENG-3, ENG-4."""
    def __init__(self):
        self.state = {"ENG-1": "Todo", "ENG-2": "Todo", "ENG-3": "Todo", "ENG-4": "Todo"}
        self.parent = {"ENG-2": "ENG-1", "ENG-3": "ENG-2", "ENG-4": "ENG-2"}
        self.comments, self.calls = [], 0

    def node(self, i):
        return {"name": self.state[i], "type": next(s["type"] for s in STATES if s["name"] == self.state[i])}

    def __call__(self, query, variables):
        self.calls += 1
        if "issueUpdate" in query:
            self.state[variables["id"]] = next(s["name"] for s in STATES if s["id"] == variables["s"])
            return {"issueUpdate": {"success": True}}
        if "commentCreate" in query:
            self.comments.append((variables["id"], variables["b"]))
            return {"commentCreate": {"success": True}}
        i = variables["id"]
        return {"issue": {"id": i, "identifier": i, "state": self.node(i), "team": {"states": {"nodes": STATES}},
                          "parent": {"identifier": self.parent[i]} if i in self.parent else None,
                          "children": {"nodes": [{"identifier": c, "state": self.node(c)} for c, p in self.parent.items() if p == i]}}}


class LinearKey(unittest.TestCase):
    def setUp(self):
        self.cfg = Path(tempfile.mkdtemp()) / "config.json"
        self.cfg.write_text(json.dumps({"workspace": "work", "workspaces": {"work": {"openrouter_api_key": "sk-or-x"}}}))
        p = mock.patch.object(fc, "CONFIG_PATH", self.cfg); p.start(); self.addCleanup(p.stop)

    def workspace(self, *args, stdin=""):
        a = SimpleNamespace(name=args[0] if args else None, target=args[1] if len(args) > 1 else None, linear="--linear" in args)
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(stdin)), redirect_stdout(out):
            fc.cmd_workspace(a)
        return out.getvalue()

    def test_the_key_comes_from_stdin_is_stored_per_workspace_and_never_printed(self):
        out = self.workspace("key", "work", "--linear", stdin=KEY + "\n")
        self.assertEqual(json.loads(self.cfg.read_text())["workspaces"]["work"]["linear_api_key"], KEY)
        self.assertNotIn(KEY, out)
        listing = self.workspace()
        self.assertIn("linear key set", listing); self.assertNotIn(KEY, listing)

    def test_listing_says_not_set(self):
        self.assertIn("linear key not set", self.workspace())


class LinearStates(unittest.TestCase):
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp())
        (self.proj / "linear.json").write_text(json.dumps({"feature": "ENG-1"}))
        self.lin = FakeLinear()
        for name, value in (("LINEAR_KEY", KEY), ("linear_gql", self.lin), ("say", lambda m: None)):
            p = mock.patch.object(fc, name, value); p.start(); self.addCleanup(p.stop)
        fc._linear_warned.clear()

    def result(self, status="passed", log=None):
        return {"status": status, "branch": "fast/p/001", "attempts": 2, "cost": 0.0123, "model": "pi:x/glm", "log": log or []}

    def test_the_state_table_runs_from_cli_events(self):
        fc.linear_event(self.proj, {"linear": "ENG-3"}, "dispatched")
        self.assertEqual([self.lin.state[i] for i in ("ENG-3", "ENG-2", "ENG-1")], ["In Progress"] * 3)
        fc.linear_event(self.proj, {"linear": "ENG-3"}, "passed", self.result())
        self.assertEqual((self.lin.state["ENG-3"], self.lin.state["ENG-2"]), ("In Review", "In Progress"))  # ENG-4 not started
        fc.linear_event(self.proj, {"linear": "ENG-4"}, "dispatched")
        fc.linear_event(self.proj, {"linear": "ENG-4"}, "passed", self.result())
        self.assertEqual(self.lin.state["ENG-2"], "In Review")
        self.assertEqual(self.lin.state["ENG-1"], "In Progress")  # every story In Review, but verify has not passed
        fc.linear_verified(self.proj)
        self.assertEqual(self.lin.state["ENG-1"], "In Review")
        self.assertIn("fast/p/001", self.lin.comments[0][1]); self.assertIn("2 attempt(s)", self.lin.comments[0][1])
        self.assertIn("$0.0123", self.lin.comments[0][1]); self.assertIn("pi:x/glm", self.lin.comments[0][1])

    def test_a_failure_stays_in_progress_with_its_cause(self):
        fc.linear_event(self.proj, {"linear": "ENG-3"}, "failed",
                        self.result("failed", [{"test_output": "ok a\nFAIL TestScore: got 1 want 2"}]))
        self.assertEqual(self.lin.state["ENG-3"], "In Progress")
        self.assertIn("FAIL TestScore: got 1 want 2", self.lin.comments[0][1])

    def test_no_key_skips_once_with_how_to_set_it(self):
        said = []
        with mock.patch.object(fc, "LINEAR_KEY", None), mock.patch.object(fc, "say", said.append):
            fc.linear_event(self.proj, {"linear": "ENG-3"}, "dispatched")
            fc.linear_event(self.proj, {"linear": "ENG-4"}, "dispatched")
        self.assertEqual(self.lin.calls, 0)
        self.assertEqual(len(said), 1); self.assertIn("--linear", said[0])

    def test_a_linear_outage_never_stops_the_run(self):
        said = []
        with mock.patch.object(fc, "linear_gql", side_effect=OSError("connection refused")), mock.patch.object(fc, "say", said.append):
            fc.linear_event(self.proj, {"linear": "ENG-3"}, "passed", self.result())
            fc.linear_verified(self.proj)
        self.assertTrue(any("update failed" in s for s in said))

    def test_untracked_tasks_leave_linear_alone(self):
        fc.linear_event(self.proj, {}, "dispatched")
        self.assertEqual(self.lin.calls, 0)

class SyncFromLinear(unittest.TestCase):
    """Feature ENG-1 > stories ENG-2, ENG-3 > tasks; ENG-2 has 3 tasks served 2 per page."""
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp())
        (self.proj / "linear.json").write_text(json.dumps({"feature": "ENG-1"}))
        self.queries = []
        for name, value in (("LINEAR_KEY", KEY), ("linear_gql", self.gql), ("say", lambda m: None)):
            p = mock.patch.object(fc, name, value); p.start(); self.addCleanup(p.stop)

    def node(self, i, parent, blocked=()):
        desc = f"brief {i}\n\n```fast-coding\nid: 00{i[-1]}\ntest: t\n```" if parent == "ENG-2" else f"text {i}"
        return {"identifier": i, "title": f"T{i}", "description": desc, "state": {"name": "Todo"}, "parent": {"identifier": parent} if parent else None,
                "inverseRelations": {"nodes": [{"type": "blocks", "issue": {"identifier": b}} for b in blocked] + [{"type": "related", "issue": {"identifier": "ENG-99"}}]}}

    def gql(self, query, variables):
        self.queries.append(query)
        kids = {"ENG-1": ["ENG-2", "ENG-3"], "ENG-2": ["ENG-4", "ENG-5", "ENG-6"], "ENG-3": []}
        if "children" not in query:
            return {"issue": self.node("ENG-1", None)}
        ids, after = kids[variables["id"]], variables["after"]
        start = int(after) if after else 0
        chunk = ids[start:start + 2] if variables["id"] == "ENG-2" else ids
        nodes = [self.node(i, variables["id"], ["ENG-4"] if i == "ENG-5" else ()) for i in chunk]
        more = start + len(chunk) < len(ids)
        return {"issue": {"children": {"pageInfo": {"hasNextPage": more, "endCursor": str(start + 2)}, "nodes": nodes}}}

    def sync(self):
        out = io.StringIO()
        with redirect_stdout(out), mock.patch.object(fc, "project_dir", return_value=self.proj):
            fc.cmd_sync(SimpleNamespace(from_linear=True))
        return out.getvalue()

    def test_payload_is_the_stdin_shape_with_every_page(self):
        data = fc.linear_sync_payload(self.proj)
        self.assertEqual(data["feature"], {"id": "ENG-1", "title": "TENG-1", "description": "text ENG-1"})
        self.assertEqual([i["id"] for i in data["issues"]], ["ENG-2", "ENG-4", "ENG-5", "ENG-6", "ENG-3"])
        task = data["issues"][2]
        self.assertEqual((task["parentId"], task["status"], task["blockedBy"]), ("ENG-2", "Todo", ["ENG-4"]))
        self.assertIn("```fast-coding", task["description"])
        self.assertFalse(any(w in q for q in self.queries for w in ("mutation", KEY)))  # read-only

    def test_sync_stores_the_tasks_with_their_blockers(self):
        self.assertIn("3 task(s) synced", self.sync())
        tasks = json.loads((self.proj / "results" / "tasks.json").read_text())["tasks"]
        self.assertEqual([(t["id"], t["after"]) for t in tasks], [("004", ""), ("005", "004"), ("006", "")])

    def test_stories_scope_skips_other_stories_children(self):
        (self.proj / "linear.json").write_text(json.dumps({"feature": "ENG-1", "stories": ["ENG-3"]}))
        self.assertEqual([i["id"] for i in fc.linear_sync_payload(self.proj)["issues"]], ["ENG-3"])

    def test_no_key_points_to_stdin_and_prints_no_key(self):
        with mock.patch.object(fc, "LINEAR_KEY", None), self.assertRaises(SystemExit) as e:
            fc.linear_sync_payload(self.proj)
        self.assertIn("pipe the JSON on stdin", str(e.exception))
        self.assertNotIn(KEY, str(e.exception))


if __name__ == "__main__":
    unittest.main()
