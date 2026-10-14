import importlib.machinery, importlib.util, io, json, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)


def issue(ident, title, desc="", blocked_by=()):
    return {"id": ident, "title": title, "description": desc, "status": "Todo", "blockedBy": list(blocked_by)}


def block(**kv):
    return "## Goal\nDo it.\n\n## Acceptance criteria\n- works\n\n```fast-coding\n" + "\n".join(f"{k}: {v}" for k, v in kv.items()) + "\n```\n"


class Sync(unittest.TestCase):
    """The team lead reads Linear through MCP and pipes the feature and its issues to `fast-coding sync`."""
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()) / "feat"
        self.proj.mkdir()
        (self.proj / "linear.json").write_text('{"feature": "ENG-1"}')

    def sync(self, issues, feature="ENG-1"):
        return fc.sync_tasks(self.proj, {"feature": {"id": feature, "title": "Feature", "description": "## Plan\nThe plan."}, "issues": issues})

    def test_tasks_come_from_issue_blocks(self):
        tasks = self.sync([
            issue("ENG-2", "Story A", "story text"),
            issue("ENG-3", "First", block(id="001", files="a.go, b.go", protected="a_test.go", test="go test ./...")),
            issue("ENG-4", "Second", block(id="002", files="c.go", test="go test", model="claude"), blocked_by=[{"id": "ENG-3", "title": "First"}, "ENG-77"]),
            issue("ENG-5", "Loose task", block(id="003", files="d.go", test="true")),
            issue("ENG-6", "No block: a decision ticket", "## Question\nWhich?")])
        self.assertEqual([t["id"] for t in tasks], ["001", "002", "003"])
        first, second = tasks[0], tasks[1]
        self.assertEqual(first["files"], ["a.go", "b.go"])
        self.assertEqual(first["protected"], ["a_test.go"])
        self.assertEqual(first["linear"], "ENG-3")
        self.assertEqual(first["body"], "## Goal\nDo it.\n\n## Acceptance criteria\n- works")  # the block is not part of the brief
        self.assertEqual(second["after"], "001")  # ENG-77 is outside the feature's tasks
        self.assertEqual(second["model"], "claude")
        self.assertEqual(fc.load_tasks(self.proj, required=True), tasks)  # the cache serves every later command
        self.assertEqual(fc.linear_cache(self.proj)["feature"]["description"], "## Plan\nThe plan.")
        self.assertEqual(fc.criteria_from_tasks(self.proj)[0], ("001", "works"))

    def test_big_tasks_are_flagged(self):
        small, wide, long = self.sync([
            issue("ENG-3", "Small", block(id="001", files="a.go, a2.go", test="t")),
            issue("ENG-4", "Wide", block(id="002", files="a.go, b.go, c.go", test="t")),
            issue("ENG-5", "Long", "x" * 3000 + "\n\n" + block(id="003", files="d.go", test="t"))])
        self.assertIsNone(fc.too_big(small))
        self.assertIn("owns 3 files", fc.too_big(wide))
        self.assertIn("brief is", fc.too_big(long))

    def clash_warning(self, *specs):
        """What `tasks` prints about a shared file for (id, after) tasks that all own x.go."""
        tasks = [{"id": i, "title": i, "files": ["x.go"], "protected": [], "test": "t", "after": a, "linear": "", "body": ""} for i, a in specs]
        out = io.StringIO()
        with mock.patch.object(fc, "load_tasks", return_value=tasks), mock.patch.object(fc, "project_dir", return_value=self.proj), \
                mock.patch.object(fc, "task_state", return_value={"state": "pending"}), mock.patch.object(fc, "sh"), \
                mock.patch("sys.stdout", out):
            fc.cmd_tasks(type("A", (), {"repo": str(self.proj)})())
        return "own the same file" in out.getvalue()

    def test_shared_file_clashes_only_between_unordered_tasks(self):
        self.assertFalse(self.clash_warning(("001", ""), ("002", "001"), ("003", "002")))  # a chain, transitively ordered
        self.assertTrue(self.clash_warning(("001", ""), ("002", "")))
        self.assertTrue(self.clash_warning(("001", "002"), ("002", ""), ("003", "002")))  # 001 and 003 are siblings

    def test_criteria_in_linear_bullets(self):
        desc = "## Goal\n\nDo it.\n\n## Acceptance criteria\n\n* one\n* two\n\n## Test plan\n\n* run\n\n```fast-coding\nid: 001\ntest: t\n```"
        self.sync([issue("ENG-3", "A", desc)])
        self.assertEqual(fc.criteria_from_tasks(self.proj), [("001", "one"), ("001", "two")])

    def test_refusals(self):
        for issues, feature in (([issue("ENG-3", "A", block(id="001", test="t")), issue("ENG-4", "B", block(id="001", test="t"))], "ENG-1"),
                                ([issue("ENG-3", "A", block(files="x"))], "ENG-1"),  # no id or test
                                ([], "ENG-9")):  # another feature than linear.json names
            with self.assertRaises(SystemExit):
                self.sync(issues, feature)
        with self.assertRaises(SystemExit):
            fc.sync_tasks(self.proj, {"issues": []})

    def test_unsynced_project_says_how(self):
        with self.assertRaises(SystemExit) as e:
            fc.load_tasks(self.proj, required=True)
        self.assertIn("fast-coding sync", str(e.exception))
        self.assertEqual(fc.load_tasks(self.proj), [])  # status and watch still work before a sync

    def test_cli_reads_stdin(self):
        payload = json.dumps({"feature": {"id": "ENG-1", "title": "F"}, "issues": [issue("ENG-3", "A", block(id="001", test="t"))]})
        with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch.object(fc.sys, "stdin", io.StringIO(payload)), \
                mock.patch("builtins.print"):
            fc.cmd_sync(type("A", (), {}))
        self.assertEqual(fc.load_tasks(self.proj)[0]["linear"], "ENG-3")


class DesignTasks(unittest.TestCase):
    """A `kind: design` task is built in Figma: it never clones, stacks, or is judged from files."""
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()).resolve() / ".fast-coding" / "p"
        self.proj.mkdir(parents=True)
        (self.proj / "linear.json").write_text('{"feature": "ENG-1"}')
        design = lambda i, nodes: issue(f"ENG-{i}", f"Page {i}", block(id=f"00{i}", kind="design", nodes=nodes, test="t"))
        self.tasks = fc.sync_tasks(self.proj, {"feature": {"id": "ENG-1", "title": "F", "description": ""}, "issues": [
            design(1, " Checkout/Cart ,Checkout/Pay"), issue("ENG-2", "Store", block(id="002", files="a.go, b.go", protected="a_test.go", test="go test")),
            design(3, "Home/Hero"), design(4, "Checkout/Summary"), design(5, "Home/Footer")]})
        self.by = {m["id"]: m for m in fc.load_tasks(self.proj)}

    def test_sync_keeps_kind_and_nodes_and_code_tasks_drops_design(self):
        self.assertEqual((self.by["001"]["kind"], self.by["001"]["nodes"]), ("design", ["Checkout/Cart", "Checkout/Pay"]))
        self.assertEqual({k: self.by["002"][k] for k in ("kind", "nodes", "files", "protected")},
                         {"kind": "code", "nodes": [], "files": ["a.go", "b.go"], "protected": ["a_test.go"]})
        self.assertEqual([m["id"] for m in fc.code_tasks(self.tasks + [{"id": "009"}])], ["002", "009"])  # no kind: an older sync, code

    def test_run_stack_and_acceptance_never_see_a_design_task(self):
        with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch.object(fc, "run_tasks") as run, \
                mock.patch.object(fc, "sh", return_value=SimpleNamespace(returncode=1, stdout="")):
            fc.cmd_run(SimpleNamespace(repo=str(self.proj), project="p", only=None, redo=False))
            with self.assertRaises(SystemExit) as e:
                fc.cmd_run(SimpleNamespace(repo=str(self.proj), project="p", only="001,003", redo=False))
        self.assertEqual([m["id"] for m in run.call_args.args[2]], ["002"])
        self.assertIn("no tasks on Linear under this feature carry a fast-coding block", str(e.exception))
        with mock.patch.object(fc, "task_branches", return_value={"fast/p/001": None, "fast/p/002": None}):
            self.assertEqual(fc.stack_order(Path("."), self.proj), ["fast/p/002"])
        reply = {"model": "m", "answers": {"c0": {"choice": "MET", "probabilities": {"MET": 0.9}}}}
        with mock.patch.object(fc, "ENV_FILE", self.proj / "none.env"), mock.patch.object(fc, "jev_ask", return_value=reply) as ask:
            fc.jev_acceptance({}, self.proj, "diff")
        self.assertEqual([c.args[3]["c0"]["instructions"]["task"] for c in ask.call_args_list], ["002"])

    def test_acceptance_passes_only_when_every_criterion_is_met(self):
        for choice, ok in (("MET", True), ("UNCLEAR", False), ("NOT_MET", False)):
            reply = {"model": "m", "answers": {"c0": {"choice": choice, "probabilities": {choice: 0.1}}}}
            with mock.patch.object(fc, "ENV_FILE", self.proj / "none.env"), mock.patch.object(fc, "jev_ask", return_value=reply), \
                    mock.patch.object(fc, "fast_json", return_value={"confirmed": False, "evidence": ""}):
                self.assertEqual(fc.jev_acceptance({}, self.proj, "diff")["pass"], ok, choice)

    def test_acceptance_with_no_criteria_fails_rather_than_passes(self):
        fc.sync_tasks(self.proj, {"feature": {"id": "ENG-1", "title": "F", "description": ""}, "issues": [issue("ENG-2", "Store", "```fast-coding\nid: 002\nfiles: a.go\ntest: go test\n```\n")]})
        with mock.patch.object(fc, "ENV_FILE", self.proj / "none.env"), mock.patch.object(fc, "jev_ask") as ask:
            res = fc.jev_acceptance({}, self.proj, "diff")
        self.assertEqual((res["pass"], res["note"], ask.called), (False, "no acceptance criteria to judge", False))

    def test_acceptance_confirm_unwraps_a_list_and_reports_a_failed_confirm_as_an_error(self):
        reply = {"model": "m", "answers": {"c0": {"choice": "NOT_MET", "probabilities": {"NOT_MET": 0.9}}}}
        for confirm, failed, error in (([{"confirmed": True, "evidence": "x"}], 1, None), ("nope", 0, True)):
            with mock.patch.object(fc, "ENV_FILE", self.proj / "none.env"), mock.patch.object(fc, "jev_ask", return_value=reply), \
                    mock.patch.object(fc, "fast_json", return_value=confirm):
                res = fc.jev_acceptance({}, self.proj, "diff")
            self.assertEqual((len(res["failed"]), "confirm call failed" in res.get("error", "") if error else "error" not in res, res["pass"]), (failed, True, False))

    def test_tasks_lists_nodes_and_warns_once_per_shared_open_page(self):
        out = io.StringIO()
        state = lambda repo, proj, m, head: {"state": "merged" if m["id"] == "003" else "pending"}
        with mock.patch.object(fc, "project_dir", return_value=self.proj), mock.patch.object(fc, "task_state", side_effect=state), \
                mock.patch.object(fc, "sh", return_value=SimpleNamespace(returncode=0, stdout="abc\n")), mock.patch("sys.stdout", out):
            fc.cmd_tasks(SimpleNamespace(repo=str(self.proj), project="p"))
        text = out.getvalue()
        self.assertIn("Checkout/Cart, Checkout/Pay", text)
        self.assertIn("WARNING two design tasks own the same page (one page per task):", text)
        self.assertIn("Checkout: 001, 004\n", text)  # one id per task, though 001 owns two nodes there
        self.assertNotIn("Home:", text)  # 003 is merged, so only 005 is open on Home

    def test_a_passed_design_task_stays_passed(self):
        for tid in ("001", "002"):
            (self.proj / "results" / f"{tid}.json").write_text('{"status": "passed"}')
        with mock.patch.object(fc, "sh", return_value=SimpleNamespace(returncode=1, stdout="")):
            rows = [fc.task_state(Path("."), self.proj, self.by[t], "HEAD")["state"] for t in ("001", "002")]
        self.assertEqual(rows, ["passed", "merged"])
