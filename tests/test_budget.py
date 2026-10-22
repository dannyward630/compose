import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, io, json, os, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_tierspend  # noqa: E402


class Budget(unittest.TestCase):
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()) / ".compose" / "p"
        (self.proj / "results").mkdir(parents=True)
        self.report = self.proj / "results" / "crew" / "frontier-budget.status"

    def hold(self, spend, tier="frontier"):
        with mock.patch.object(fc_tierspend, "frontier", return_value=spend):
            return fc.fc_budget.hold(self.proj, tier)

    def set_limit(self, dollars):
        with mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), redirect_stdout(io.StringIO()) as out:
            fc.fc_budget.cmd_budget(SimpleNamespace(repo=".", project="p", tier="frontier", dollars=dollars))
        return out.getvalue()

    def test_limit_defaults_to_25_and_a_broken_file_does_too(self):
        self.assertEqual(fc.fc_budget.limit(self.proj), 25.0)
        (self.proj / "results" / "budget.json").write_text("{not json")
        self.assertEqual(fc.fc_budget.limit(self.proj), 25.0)

    def test_budget_command_sets_the_limit_and_prints_it(self):
        self.assertEqual(self.set_limit(40.0), "frontier limit $40.00 for p\n")
        self.assertEqual(fc.fc_budget.limit(self.proj), 40.0)
        self.assertEqual(json.loads((self.proj / "results" / "budget.json").read_text()), {"frontier": 40.0})

    def test_frontier_at_the_limit_runs_at_standard_and_reports_needs_user(self):
        self.assertEqual(self.hold(25.0), "standard")
        self.assertEqual(self.hold(30.5), "standard")
        first, second = [json.loads(l) for l in self.report.read_text().splitlines()]
        self.assertEqual(first["state"], "needs-user")
        self.assertEqual(first["message"], "frontier spend $25.00 reached the $25.00 limit of p: new frontier work runs at standard; raise it with compose budget --project p frontier <dollars>")
        self.assertIn("$30.50", second["message"])
        self.assertRegex(first["at"], r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$")

    def test_the_limit_comes_from_the_budget_file(self):
        self.set_limit(40.0)
        self.assertEqual(self.hold(30.0), "frontier")
        self.assertFalse(self.report.exists())
        self.assertEqual(self.hold(40.0), "standard")
        self.assertIn("reached the $40.00 limit", json.loads(self.report.read_text())["message"])

    def test_frontier_under_the_limit_and_other_tiers_return_unchanged_with_no_report(self):
        self.assertEqual(self.hold(24.99), "frontier")
        for tier in ("standard", "cheap", None): self.assertEqual(self.hold(99.0, tier), tier)
        self.assertFalse(self.report.exists())
