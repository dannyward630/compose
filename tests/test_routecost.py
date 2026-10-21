import hermetic  # first: no test sees the real home
import json, os, sys, tempfile, unittest
from pathlib import Path
os.environ["HERDR_ENV"] = ""

BIN = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))
import fc_routecost  # noqa: E402


class Counts(unittest.TestCase):
    def proj(self, issues=None, **files):
        proj = Path(tempfile.mkdtemp()) / ".compose" / "p"
        (proj / "results").mkdir(parents=True)
        if issues is not None:
            (proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": [], "issues": {k: {"description": v} for k, v in issues.items()}}))
        for name, text in files.items(): (proj / "results" / f"{name}.json").write_text(text)
        return proj

    def test_route(self):
        r = lambda body: "## Route\n\n" + body
        proj = self.proj({"A-1": r("* workflow: test-first\n* depth: FAST\n"), "A-2": "no section here", "A-3": r("* workflow: magic\n* depth: DEEP\n"),
                          "A-4": r("* workflow: fix-then-regression-test\n")})
        route = lambda linear: fc_routecost.route(proj, {"id": "001", "linear": linear})
        self.assertEqual(route("A-1"), ("test-first", "FAST"))
        self.assertEqual(route("A-2"), ("-", "-"))
        self.assertEqual(route("A-3"), ("-", "DEEP"))
        self.assertEqual(route("A-4"), ("fix-then-regression-test", "-"))
        self.assertEqual(route("A-9"), ("-", "-"))
        self.assertEqual(fc_routecost.route(self.proj(), {"id": "001", "linear": "A-1"}), ("-", "-"))

    def test_rounds(self):
        self.assertEqual(fc_routecost.rounds(self.proj(verify='{"rounds": [{"fix_tasks": ["001"]}, {}]}')), [{"fix_tasks": ["001"]}, {}])
        self.assertEqual(fc_routecost.rounds(self.proj(smoke='{"rounds": [{}]}', review='{"rounds": [{}]}')), [])
        self.assertEqual(fc_routecost.rounds(self.proj(verify="not json{")), [])

    def test_fix_tasks(self):
        tasks = [{"id": "001", "files": ["a.py"], "protected": ["tests/test_a.py"]}, {"id": "002", "kind": "design", "files": ["a.py"]},
                 {"id": "003", "files": ["a.py", "b.py"]}, {"id": "004", "protected": ["c.py"]}]
        self.assertEqual(fc_routecost.fix_tasks(tasks, ["a.py"]), ["001", "003"])
        self.assertEqual(fc_routecost.fix_tasks(tasks, ["c.py", "tests/test_a.py"]), ["001", "004"])
        self.assertEqual(fc_routecost.fix_tasks(tasks, ["other.py"]), [])

    def test_counts(self):
        result = {"attempts": 3, "cost": 0.42, "log": [{"attempt": 1}, {"attempt": 2, "fallback": {"from": "a", "to": "b"}}, {"fallback": {}}]}
        rounds = [{"fix_tasks": ["001", "002"]}, {}, {"fix_tasks": ["002"]}, {"fix_tasks": ["001"]}]
        out = fc_routecost.counts(result, rounds, "001")
        self.assertEqual(out, {"attempts": 3, "escalations": 2, "fix_rounds": 2, "cost": 0.42})
        self.assertEqual(list(out), ["attempts", "escalations", "fix_rounds", "cost"])
        empty = fc_routecost.counts({}, [], "001")
        self.assertEqual(empty, {"attempts": 0, "escalations": 0, "fix_rounds": 0, "cost": 0.0})
        self.assertIsInstance(empty["cost"], float)
        self.assertEqual(fc_routecost.counts({"log": [{"attempt": 1}]}, [{}], "001")["escalations"], 0)


if __name__ == "__main__":
    unittest.main()
