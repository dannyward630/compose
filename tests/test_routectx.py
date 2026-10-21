import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, json, os, sys, tempfile, unittest
from pathlib import Path
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_routectx  # noqa: E402

STORY = {"id": "ENG-9", "title": "Story", "description": "## Goal\ns\n\n## Acceptance criteria\n* greets\n* waves", "status": "Todo", "blockedBy": []}
BUG = "## Goal\nFix it.\n\n## Acceptance criteria\n* shows the name\n* keeps the case\n\n## Reproduction\nRun the driver.\ncase: greet-name\n\n## Notes\nx"


def issue(n, files, body="## Goal\nx", status="Todo", block="", **kv):
    desc = f"{body}\n\n```compose\nid: {n:03}\ntest: t\nfiles: {files}\n{block}```\n"
    return {"id": f"ENG-{n}", "title": f"T{n}", "description": desc, "status": status, "blockedBy": [], **kv}


class Context(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.proj = self.repo / ".compose" / "p"
        (self.proj / "results").mkdir(parents=True)
        (self.repo / "bin").mkdir()
        (self.repo / "bin" / "x.py").write_text("")
        (self.repo / "README.md").write_text("")
        (self.proj / "verify.json").write_text(json.dumps({"e2e": [{"name": "greet-name"}, {"name": "seen"}]}))
        cases = [{"name": "greet-name", "verdict": "feature_missing"}, {"name": "seen", "verdict": "passed"}, {"name": "ghost", "verdict": "feature_missing"}]
        (self.proj / "results" / "prove.json").write_text(json.dumps({"cases": cases}))

    def ctx(self, mine, *others):
        issues = {i["id"]: i for i in (STORY, mine, *others)}
        tasks = [fc.fc_tasks.task_from_issue(i) for i in (mine, *others)]
        return fc_routectx.route_context(self.repo, self.proj, tasks[0], tasks, issues)

    def test_whole_context(self):
        mine = issue(1, "bin/x.py, README.md, src/new.py", BUG, block="route: implement-then-test\n", parentId="ENG-9", labels=["bug"])
        others = [issue(2, "z.py, bin/x.py"), issue(3, "a.py, z.py", "## Goal\nx", "In Progress"), issue(4, "done.py", status="Done"),
                  issue(5, "gone.py", status="Canceled"), issue(6, "gone2.py", status="cancelled")]
        self.assertEqual(self.ctx(mine, *others), {
            "task": "T1", "criteria": ["shows the name", "keeps the case"],
            "files": [{"path": "bin/x.py", "top": "bin", "exists": True}, {"path": "README.md", "top": ".", "exists": True},
                      {"path": "src/new.py", "top": "src", "exists": False}],
            "other_files": ["a.py", "bin/x.py", "z.py"], "story": {"title": "Story", "criteria": ["greets", "waves"]},
            "bug": {"label": True, "documented": True, "confirmed": True}, "pin": "implement-then-test"})

    def test_bug_and_story_holdouts(self):
        for body, bug in [("## Goal\nx", (False, False)), ("## Reproduction\n\n   \n## Notes\ncase: greet-name", (False, False)),
                          ("## Reproduction\ncase: seen", (True, False)), ("## Reproduction\ncase: ghost", (True, False))]:
            got = self.ctx(issue(1, "a.py", body, parentId="ENG-404", labels=["Feature"]))
            self.assertEqual(got["bug"], {"label": False, "documented": bug[0], "confirmed": bug[1]}, body)
            self.assertEqual((got["story"], got["pin"], got["other_files"]), (None, None, []))
        for name in ("results/prove.json", "verify.json"):
            (self.proj / name).unlink()
            self.assertEqual(self.ctx(issue(1, "a.py", BUG))["bug"], {"label": False, "documented": True, "confirmed": False}, name)

