import importlib.machinery, importlib.util, io, json, os, tempfile, unittest, urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import sys
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)


def issue(ident, title, desc="", blocked_by=()):
    return {"id": ident, "title": title, "description": desc, "status": "Todo", "blockedBy": list(blocked_by)}


def block(**kv):
    return "## Goal\nDo it.\n\n## Acceptance criteria\n- works\n\n```compose\n" + "\n".join(f"{k}: {v}" for k, v in kv.items()) + "\n```\n"


class Sync(unittest.TestCase):
    """The team lead reads Linear through MCP and pipes the feature and its issues to `compose sync`."""
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()) / "feat"
        self.proj.mkdir()
        (self.proj / "linear.json").write_text('{"feature": "ENG-1"}')

    def sync(self, issues, feature="ENG-1"):
        return fc.fc_tasks.sync_tasks(self.proj, {"feature": {"id": feature, "title": "Feature", "description": "## Plan\nThe plan."}, "issues": issues})

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
        self.assertEqual(fc.fc_tasks.load_tasks(self.proj, required=True), tasks)  # the cache serves every later command
        self.assertEqual(fc.fc_tasks.linear_cache(self.proj)["feature"]["description"], "## Plan\nThe plan.")
        self.assertEqual(fc.fc_tasks.criteria_from_tasks(self.proj)[0], ("001", "works"))

    def test_story_scope_and_done_tasks(self):
        def story_task(ident, parent, tid, state="Todo"):
            return {**issue(ident, tid, block(id=tid, files=f"{tid}.go", test="t")), "parentId": parent, "status": state}
        issues = [{**issue("ENG-2", "Story A"), "parentId": "ENG-1"}, {**issue("ENG-9", "Story B"), "parentId": "ENG-1"},
                  story_task("ENG-3", "ENG-2", "001", "Done"), story_task("ENG-4", "ENG-2", "002"), story_task("ENG-5", "ENG-9", "003")]
        self.assertEqual([t["id"] for t in self.sync(issues)], ["001", "002", "003"])  # no stories set: unchanged
        (self.proj / "linear.json").write_text('{"feature": "ENG-1", "stories": ["ENG-9"]}')
        self.assertEqual([t["id"] for t in self.sync(issues)], ["003"])
        with self.assertRaises(SystemExit) as no_parent:  # a scoped project fails loudly on issues synced without parentId
            self.sync([issue("ENG-9", "Story B"), issue("ENG-5", "Task", block(id="003", files="a.go", test="t"))])
        self.assertIn("parentId", str(no_parent.exception))
        self.assertIn("ENG-5", str(no_parent.exception))
        self.assertEqual(set(fc.fc_tasks.linear_cache(self.proj)["issues"]), {"ENG-9", "ENG-5"})
        (self.proj / "linear.json").write_text('{"feature": "ENG-1"}')
        done, todo = self.sync(issues)[:2]
        state = lambda m: fc.fc_status.task_state(self.proj, self.proj, m, "HEAD")["state"]
        self.assertEqual((state(done), state(todo)), ("merged", "pending"))
        self.assertTrue(fc.fc_tasks.linear_done(done) and not fc.fc_tasks.linear_done(todo))

    def test_big_tasks_are_flagged(self):
        small, wide, long = self.sync([
            issue("ENG-3", "Small", block(id="001", files="a.go, a2.go", test="t")),
            issue("ENG-4", "Wide", block(id="002", files="a.go, b.go, c.go", test="t")),
            issue("ENG-5", "Long", "x" * 3000 + "\n\n" + block(id="003", files="d.go", test="t"))])
        self.assertIsNone(fc.fc_spec.too_big(small))
        self.assertIn("owns 3 files", fc.fc_spec.too_big(wide))
        self.assertIn("brief is", fc.fc_spec.too_big(long))

    def clash_warning(self, *specs):
        """What `tasks` prints about a shared file for (id, after) tasks that all own x.go."""
        tasks = [{"id": i, "title": i, "files": ["x.go"], "protected": [], "test": "t", "after": a, "linear": "", "body": ""} for i, a in specs]
        out = io.StringIO()
        with mock.patch.object(fc.fc_tasks, "load_tasks", return_value=tasks), mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), \
                mock.patch.object(fc.fc_status, "task_state", return_value={"state": "pending"}), mock.patch.object(fc.fc_core, "sh"), \
                mock.patch("sys.stdout", out):
            fc.fc_spec.cmd_tasks(type("A", (), {"repo": str(self.proj)})())
        return "own the same file" in out.getvalue()

    def test_shared_file_clashes_only_between_unordered_tasks(self):
        self.assertFalse(self.clash_warning(("001", ""), ("002", "001"), ("003", "002")))  # a chain, transitively ordered
        self.assertTrue(self.clash_warning(("001", ""), ("002", "")))
        self.assertTrue(self.clash_warning(("001", "002"), ("002", ""), ("003", "002")))  # 001 and 003 are siblings

    def test_criteria_in_linear_bullets(self):
        desc = "## Goal\n\nDo it.\n\n## Acceptance criteria\n\n* one\n* two\n\n## Test plan\n\n* run\n\n```compose\nid: 001\ntest: t\n```"
        self.sync([issue("ENG-3", "A", desc)])
        self.assertEqual(fc.fc_tasks.criteria_from_tasks(self.proj), [("001", "one"), ("001", "two")])

    def test_refusals(self):
        for issues, feature in (([issue("ENG-3", "A", block(id="001", test="t")), issue("ENG-4", "B", block(id="001", test="t"))], "ENG-1"),
                                ([issue("ENG-3", "A", block(files="x"))], "ENG-1"),  # no id or test
                                ([], "ENG-9")):  # another feature than linear.json names
            with self.assertRaises(SystemExit):
                self.sync(issues, feature)
        with self.assertRaises(SystemExit):
            fc.fc_tasks.sync_tasks(self.proj, {"issues": []})

    def test_unsynced_project_says_how(self):
        with self.assertRaises(SystemExit) as e:
            fc.fc_tasks.load_tasks(self.proj, required=True)
        self.assertIn("compose sync", str(e.exception))
        self.assertEqual(fc.fc_tasks.load_tasks(self.proj), [])  # status and watch still work before a sync

    def test_cli_reads_stdin(self):
        payload = json.dumps({"feature": {"id": "ENG-1", "title": "F"}, "issues": [issue("ENG-3", "A", block(id="001", test="t"))]})
        with mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch.object(sys, "stdin", io.StringIO(payload)), \
                mock.patch("builtins.print"):
            fc.fc_linear.cmd_sync(type("A", (), {"from_linear": False}))
        self.assertEqual(fc.fc_tasks.load_tasks(self.proj)[0]["linear"], "ENG-3")


class DesignTasks(unittest.TestCase):
    """A `kind: design` task is built in Figma: it never clones, stacks, or is judged from files."""
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()).resolve() / ".compose" / "p"
        self.proj.mkdir(parents=True)
        (self.proj / "linear.json").write_text('{"feature": "ENG-1"}')
        design = lambda i, nodes: issue(f"ENG-{i}", f"Page {i}", block(id=f"00{i}", kind="design", nodes=nodes, test="t"))
        self.tasks = fc.fc_tasks.sync_tasks(self.proj, {"feature": {"id": "ENG-1", "title": "F", "description": ""}, "issues": [
            design(1, " Checkout/Cart ,Checkout/Pay"), issue("ENG-2", "Store", block(id="002", files="a.go, b.go", protected="a_test.go", test="go test")),
            design(3, "Home/Hero"), design(4, "Checkout/Summary"), design(5, "Home/Footer")]})
        self.by = {m["id"]: m for m in fc.fc_tasks.load_tasks(self.proj)}

    def test_sync_keeps_kind_and_nodes_and_code_tasks_drops_design(self):
        self.assertEqual((self.by["001"]["kind"], self.by["001"]["nodes"]), ("design", ["Checkout/Cart", "Checkout/Pay"]))
        self.assertEqual({k: self.by["002"][k] for k in ("kind", "nodes", "files", "protected")},
                         {"kind": "code", "nodes": [], "files": ["a.go", "b.go"], "protected": ["a_test.go"]})
        self.assertEqual([m["id"] for m in fc.fc_tasks.code_tasks(self.tasks + [{"id": "009"}])], ["002", "009"])  # no kind: an older sync, code

    def test_run_stack_and_acceptance_never_see_a_design_task(self):
        with mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch.object(fc.fc_run, "run_tasks") as run, \
                mock.patch.object(fc.fc_core, "sh", return_value=SimpleNamespace(returncode=1, stdout="")):
            fc.fc_run.cmd_run(SimpleNamespace(repo=str(self.proj), project="p", only=None, redo=False))
            with self.assertRaises(SystemExit) as e:
                fc.fc_run.cmd_run(SimpleNamespace(repo=str(self.proj), project="p", only="001,003", redo=False))
        self.assertEqual([m["id"] for m in run.call_args.args[2]], ["002"])
        self.assertIn("no tasks on Linear under this feature carry a compose block", str(e.exception))
        with mock.patch.object(fc.fc_worktree, "task_branches", return_value={"fast/p/001": None, "fast/p/002": None}):
            self.assertEqual(fc.fc_worktree.stack_order(Path("."), self.proj), ["fast/p/002"])
        reply = {"model": "m", "answers": {"c0": {"choice": "MET", "probabilities": {"MET": 0.9}}}}
        with mock.patch.object(fc.fc_config, "ENV_FILE", self.proj / "none.env"), mock.patch.object(fc.fc_models, "jev_ask", return_value=reply) as ask:
            fc.fc_verify.jev_acceptance({}, self.proj, "diff")
        self.assertEqual([c.args[3]["c0"]["instructions"]["task"] for c in ask.call_args_list], ["002"])

    def test_acceptance_passes_only_when_every_criterion_is_met(self):
        for choice, ok in (("MET", True), ("UNCLEAR", False), ("NOT_MET", False)):
            reply = {"model": "m", "answers": {"c0": {"choice": choice, "probabilities": {choice: 0.1}}}}
            with mock.patch.object(fc.fc_config, "ENV_FILE", self.proj / "none.env"), mock.patch.object(fc.fc_models, "jev_ask", return_value=reply), \
                    mock.patch.object(fc.fc_models, "fast_json", return_value={"confirmed": False, "evidence": ""}):
                self.assertEqual(fc.fc_verify.jev_acceptance({}, self.proj, "diff")["pass"], ok, choice)

    def test_acceptance_re_asks_a_refuted_not_met_once_and_a_confirm_error_never(self):
        first = {"model": "m", "answers": {"c0": {"choice": "NOT_MET", "probabilities": {"NOT_MET": 0.9}}}}
        again = lambda c: {"model": "m", "answers": {"c0": {"choice": c, "probabilities": {c: 0.9}}}}
        for second, confirm, ok, calls in (("MET", {"confirmed": False, "evidence": "satisfied"}, True, 2), ("NOT_MET", {"confirmed": False, "evidence": "satisfied"}, False, 2),
                                           ("MET", "nope", False, 1)):
            with mock.patch.object(fc.fc_config, "ENV_FILE", self.proj / "none.env"), mock.patch.object(fc.fc_models, "jev_ask", side_effect=[first, again(second)]) as ask, \
                    mock.patch.object(fc.fc_models, "fast_json", return_value=confirm):
                res = fc.fc_verify.jev_acceptance({}, self.proj, "diff")
            self.assertEqual((res["pass"], ask.call_count), (ok, calls), (second, confirm))
        self.assertEqual((res["criteria"][0]["choice"]), "NOT_MET")

    def test_acceptance_state_leaves_out_lockfiles_and_stays_under_the_judge_token_limit(self):
        """TypeSafe answers HTTP 400 max_tokens_exceeded for a state of about 35k characters; a lockfile is noise, not code."""
        repo = Path(tempfile.mkdtemp())
        (repo / "bun.lock").write_text("lock\n" * 20000)
        (repo / "a.go").write_text("package a\n" * 6000)
        (repo / "b.go").write_text("package b\n")
        fc.fc_tasks.sync_tasks(self.proj, {"feature": {"id": "ENG-1", "title": "F", "description": ""}, "issues": [
            issue("ENG-2", "Store", block(id="002", files="a.go, bun.lock", protected="b.go", test="go test"))]})
        reply = {"model": "m", "answers": {"c0": {"choice": "MET", "probabilities": {"MET": 0.9}}}}
        with mock.patch.object(fc.fc_config, "ENV_FILE", self.proj / "none.env"), mock.patch.object(fc.fc_models, "jev_ask", return_value=reply) as ask:
            fc.fc_verify.jev_acceptance({}, self.proj, "diff", repo=repo)
        code = ask.call_args.args[2]["code"]
        self.assertNotIn("bun.lock", code)
        self.assertLessEqual(len(code), fc.fc_verify.JEV_CODE_CAP)

    def test_a_rejected_request_reports_the_providers_error_body(self):
        err = urllib.error.HTTPError("u", 400, "Bad Request", {}, io.BytesIO(b'{"detail":{"error_type":"max_tokens_exceeded"}}'))
        self.addCleanup(err.close)
        with mock.patch.object(urllib.request, "urlopen", side_effect=err):
            with self.assertRaises(RuntimeError) as e:
                fc.fc_models.http_json(mock.Mock(), "typesafe (Jev acceptance)")
        self.assertEqual(str(e.exception), 'typesafe (Jev acceptance): HTTP 400 Bad Request: {"detail":{"error_type":"max_tokens_exceeded"}}')
        self.assertTrue(err.fp.closed)

    def test_a_refused_payment_closes_the_error_and_still_raises_payment_required(self):
        for code, reason, body in ((402, "Payment Required", b""), (403, "Forbidden", b"insufficient credits on this key")):
            err = urllib.error.HTTPError("u", code, reason, {}, io.BytesIO(body))
            with mock.patch.object(urllib.request, "urlopen", side_effect=err):
                with self.assertRaises(fc.fc_models.PaymentRequired) as e:
                    fc.fc_models.http_json(mock.Mock(), "openrouter")
            self.assertEqual((e.exception.provider, e.exception.message), ("openrouter", body.decode() or f"HTTP {code}"))
            self.assertTrue(err.fp.closed, code)

    def test_acceptance_with_no_criteria_fails_rather_than_passes(self):
        fc.fc_tasks.sync_tasks(self.proj, {"feature": {"id": "ENG-1", "title": "F", "description": ""}, "issues": [issue("ENG-2", "Store", "```compose\nid: 002\nfiles: a.go\ntest: go test\n```\n")]})
        with mock.patch.object(fc.fc_config, "ENV_FILE", self.proj / "none.env"), mock.patch.object(fc.fc_models, "jev_ask") as ask:
            res = fc.fc_verify.jev_acceptance({}, self.proj, "diff")
        self.assertEqual((res["pass"], res["note"], ask.called), (False, "no acceptance criteria to judge", False))

    def test_acceptance_confirm_unwraps_a_list_and_reports_a_failed_confirm_as_an_error(self):
        reply = {"model": "m", "answers": {"c0": {"choice": "NOT_MET", "probabilities": {"NOT_MET": 0.9}}}}
        for confirm, failed, error in (([{"confirmed": True, "evidence": "x"}], 1, None), ("nope", 0, True)):
            with mock.patch.object(fc.fc_config, "ENV_FILE", self.proj / "none.env"), mock.patch.object(fc.fc_models, "jev_ask", return_value=reply), \
                    mock.patch.object(fc.fc_models, "fast_json", return_value=confirm):
                res = fc.fc_verify.jev_acceptance({}, self.proj, "diff")
            self.assertEqual((len(res["failed"]), "confirm call failed" in res.get("error", "") if error else "error" not in res, res["pass"]), (failed, True, False))

    def test_tasks_lists_nodes_and_warns_once_per_shared_open_page(self):
        out = io.StringIO()
        state = lambda repo, proj, m, head: {"state": "merged" if m["id"] == "003" else "pending"}
        with mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch.object(fc.fc_status, "task_state", side_effect=state), \
                mock.patch.object(fc.fc_core, "sh", return_value=SimpleNamespace(returncode=0, stdout="abc\n")), mock.patch("sys.stdout", out):
            fc.fc_spec.cmd_tasks(SimpleNamespace(repo=str(self.proj), project="p"))
        text = out.getvalue()
        self.assertIn("Checkout/Cart, Checkout/Pay", text)
        self.assertIn("WARNING two design tasks own the same page (one page per task):", text)
        self.assertIn("Checkout: 001, 004\n", text)  # one id per task, though 001 owns two nodes there
        self.assertNotIn("Home:", text)  # 003 is merged, so only 005 is open on Home

    def test_a_passed_design_task_stays_passed(self):
        for tid in ("001", "002"):
            (self.proj / "results" / f"{tid}.json").write_text('{"status": "passed"}')
        with mock.patch.object(fc.fc_core, "sh", return_value=SimpleNamespace(returncode=1, stdout="")):
            rows = [fc.fc_status.task_state(Path("."), self.proj, self.by[t], "HEAD")["state"] for t in ("001", "002")]
        self.assertEqual(rows, ["passed", "merged"])
