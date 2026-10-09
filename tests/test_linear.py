import importlib.machinery, importlib.util, json, tempfile, unittest
from pathlib import Path
from unittest import mock

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)


def issue(ident, title, desc="", blocked_by=(), children=()):
    return {"identifier": ident, "title": title, "description": desc, "state": {"name": "Todo"},
            "inverseRelations": {"nodes": [{"type": "blocks", "issue": {"identifier": b}} for b in blocked_by]
                                 + [{"type": "related", "issue": {"identifier": "ENG-99"}}]},
            "children": {"nodes": list(children)}}


def block(**kv):
    return "## Goal\nDo it.\n\n## Acceptance criteria\n- works\n\n```fast-coding\n" + "\n".join(f"{k}: {v}" for k, v in kv.items()) + "\n```\n"


class Sync(unittest.TestCase):
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()) / "feat"
        self.proj.mkdir()
        (self.proj / "linear.json").write_text('{"feature": "ENG-1"}')

    def sync(self, root):
        with mock.patch.object(fc, "linear_query", return_value={"issue": root}):
            return fc.sync_tasks(self.proj)

    def test_tasks_come_from_issue_blocks(self):
        root = issue("ENG-1", "Feature", "## Plan\nThe plan.", children=[
            issue("ENG-2", "Story A", "story text", children=[
                issue("ENG-3", "First", block(id="001", files="a.go, b.go", protected="a_test.go", test="go test ./...")),
                issue("ENG-4", "Second", block(id="002", files="c.go", test="go test", model="claude"), blocked_by=["ENG-3", "ENG-77"])]),
            issue("ENG-5", "Loose task", block(id="003", files="d.go", test="true")),
            issue("ENG-6", "No block: a decision ticket", "## Question\nWhich?")])
        tasks = self.sync(root)
        self.assertEqual([t["id"] for t in tasks], ["001", "002", "003"])
        first, second = tasks[0], tasks[1]
        self.assertEqual(first["files"], ["a.go", "b.go"])
        self.assertEqual(first["protected"], ["a_test.go"])
        self.assertEqual(first["linear"], "ENG-3")
        self.assertEqual(first["body"], "## Goal\nDo it.\n\n## Acceptance criteria\n- works")  # the block is not part of the brief
        self.assertEqual(second["after"], "001")  # blocked by ENG-3; ENG-77 is outside the feature and the related link is not a block
        self.assertEqual(second["model"], "claude")
        self.assertEqual(fc.load_tasks(self.proj), tasks)  # the cache serves no-network commands
        self.assertEqual(fc.linear_cache(self.proj)["feature"]["description"], "## Plan\nThe plan.")
        self.assertEqual(fc.criteria_from_tasks(self.proj)[0], ("001", "works"))

    def test_criteria_in_linear_bullets(self):
        desc = "## Goal\n\nDo it.\n\n## Acceptance criteria\n\n* one\n* two\n\n## Test plan\n\n* run\n\n```fast-coding\nid: 001\ntest: t\n```"
        self.sync(issue("ENG-1", "F", children=[issue("ENG-3", "A", desc)]))
        self.assertEqual(fc.criteria_from_tasks(self.proj), [("001", "one"), ("001", "two")])

    def test_duplicate_ids_refused(self):
        root = issue("ENG-1", "F", children=[issue("ENG-3", "A", block(id="001", test="t")), issue("ENG-4", "B", block(id="001", test="t"))])
        with self.assertRaises(SystemExit):
            self.sync(root)

    def test_block_needs_id_and_test(self):
        with self.assertRaises(SystemExit):
            self.sync(issue("ENG-1", "F", children=[issue("ENG-3", "A", block(files="x"))]))

    def test_missing_feature_link(self):
        (self.proj / "linear.json").unlink()
        with self.assertRaises(SystemExit):
            fc.sync_tasks(self.proj)

    def test_no_key_says_how(self):
        with mock.patch.dict(fc.os.environ, {}, clear=True), self.assertRaises(SystemExit) as e:
            fc.linear_query("query { viewer { id } }", {})
        self.assertIn("workspace key", str(e.exception))
