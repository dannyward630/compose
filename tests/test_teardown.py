import importlib.machinery, importlib.util, json, tempfile, unittest
from pathlib import Path
from unittest import mock
import subprocess, sys

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast_coding.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)


class Teardown(unittest.TestCase):
    """Nothing a project started stays open: done teammates close themselves, the team lead's done tears down the rest."""
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()) / ".fast-coding" / "shop"
        self.proj.mkdir(parents=True)
        for name, tab in (("shop-orchestrator", "t3"), ("shop-tests", "t9"), ("shop-e2e", "t10")):
            (fc.crew_dir(self.proj) / f"{name}.json").write_text(json.dumps({"name": name, "title": name, "tab": tab, "pane": "p"}))
        fc.write_report(self.proj, "shop-tests", "done", "tests committed")
        fc.write_report(self.proj, "shop-e2e", "working", "checking")
        self.tabs = {"t1": "shell", "t2": "status", "t3": "orchestrator", "t4": "implementers", "t5": "006 006 Question",
                     "t6": "009 someone else's", "t7": "verify", "t8": "verify 12:10", "t9": "tests", "t10": "e2e", "t11": "notes"}
        self.agents = [("shop-orchestrator", "t3"), ("shop-006", "t5"), ("other-009", "t6")]
        self.calls = []

    def herdr(self, *args, check=False, timeout=120):
        self.calls.append(args)
        if args[:2] == ("tab", "list"):
            return {"tabs": [{"tab_id": t, "label": l} for t, l in self.tabs.items()]}
        if args[:2] == ("agent", "list"):
            return {"agents": [{"name": n, "tab_id": t, "workspace_id": "w9"} for n, t in self.agents]}
        if args[:2] == ("tab", "close"):
            self.tabs.pop(args[2])

    def teardown(self):
        with mock.patch.object(fc.fc_herdr, "herdr", self.herdr), mock.patch.object(fc.fc_herdr, "herdr_env", return_value=True), \
                mock.patch.object(fc.fc_herdr, "herdr_find_space", return_value="w9"), mock.patch("builtins.print"):
            return fc.teardown(self.proj)

    def test_closes_runs_verify_and_done_crew_only(self):
        self.assertEqual(sorted(self.teardown()), sorted(["implementers", "006 006 Question", "verify", "verify 12:10", "tests"]))
        self.assertEqual(sorted(self.tabs), ["t1", "t10", "t11", "t2", "t3", "t6"])  # shell, status, team lead, unfinished teammate, others' tabs stay
        self.assertEqual(fc.crew_record(self.proj, "shop-tests")["closed"]["why"], "teardown")
        self.assertEqual(self.teardown(), [])  # idempotent

    def test_team_lead_done_tears_down_crew_done_closes_itself(self):
        def report(who):
            with mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch("builtins.print"), \
                    mock.patch.object(fc.fc_herdr, "herdr", self.herdr), mock.patch.object(fc.fc_herdr, "herdr_env", return_value=True), \
                    mock.patch.object(fc, "teardown") as td, mock.patch.object(subprocess, "Popen") as popen:
                fc.cmd_report(type("A", (), {"as_": who, "state": "done", "message": ["finished"]}))
            return td, popen
        td, popen = report("shop-e2e")
        td.assert_not_called()
        cmd, kw = popen.call_args
        self.assertEqual(cmd[0][-2:], ["shop-e2e", "t10"])  # waits for this agent, then closes its tab
        self.assertIn("agent wait", cmd[0][2])
        self.assertTrue(kw["start_new_session"])
        self.assertIn("closed", fc.crew_record(self.proj, "shop-e2e"))
        self.assertNotIn(("tab", "close", "t10"), self.calls)  # never closed synchronously, mid-turn
        td, popen = report("shop-orchestrator")
        td.assert_called_once_with(self.proj)
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
