import importlib.machinery, importlib.util, io, json, tempfile, unittest
from pathlib import Path
from unittest import mock

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)


def issue(ident, title, desc="", blocked_by=()):
    return {"id": ident, "title": title, "description": desc, "status": "Todo", "blockedBy": list(blocked_by)}


def block(**kv):
    return "## Goal\nDo it.\n\n## Acceptance criteria\n- works\n\n```fast-coding\n" + "\n".join(f"{k}: {v}" for k, v in kv.items()) + "\n```\n"


class Sync(unittest.TestCase):
    """The orchestrator reads Linear through MCP and pipes the feature and its issues to `fast-coding sync`."""
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
