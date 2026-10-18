import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, json, os, tempfile, unittest
from pathlib import Path
from unittest import mock
import subprocess, sys
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)


class Teardown(unittest.TestCase):
    """Nothing a project started stays open: done teammates close themselves, the team lead's done tears down the rest."""
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()) / ".compose" / "shop"
        self.proj.mkdir(parents=True)
        for name, tab in (("shop-orchestrator", "t3"), ("shop-tests", "t9"), ("shop-e2e", "t10")):
            (fc.fc_crew.crew_dir(self.proj) / f"{name}.json").write_text(json.dumps({"name": name, "title": name, "tab": tab, "pane": "p"}))
        fc.fc_crew.write_report(self.proj, "shop-tests", "done", "tests committed")
        fc.fc_crew.write_report(self.proj, "shop-e2e", "working", "checking")
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
            return fc.fc_crew.teardown(self.proj)

    def test_closes_runs_verify_and_done_crew_only(self):
        self.assertEqual(sorted(self.teardown()), sorted(["implementers", "006 006 Question", "verify", "verify 12:10", "tests"]))
        self.assertEqual(sorted(self.tabs), ["t1", "t10", "t11", "t2", "t3", "t6"])  # shell, status, team lead, unfinished teammate, others' tabs stay
        self.assertEqual(fc.fc_crew.crew_record(self.proj, "shop-tests")["closed"]["why"], "teardown")
        self.assertEqual(self.teardown(), [])  # idempotent

    def test_team_lead_done_tears_down_crew_done_closes_itself(self):
        def report(who):
            with mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch("builtins.print"), \
                    mock.patch.object(fc.fc_herdr, "herdr", self.herdr), mock.patch.object(fc.fc_herdr, "herdr_env", return_value=True), \
                    mock.patch.object(fc.fc_crew, "teardown") as td, mock.patch.object(subprocess, "Popen") as popen:
                fc.fc_crew.cmd_report(type("A", (), {"as_": who, "state": "done", "message": ["finished"]}))
            return td, popen
        td, popen = report("shop-e2e")
        td.assert_not_called()
        cmd, kw = popen.call_args
        self.assertEqual(cmd[0][-2:], ["shop-e2e", "t10"])  # waits for this agent, then closes its tab
        self.assertIn("agent wait", cmd[0][2])
        self.assertTrue(kw["start_new_session"])
        self.assertIn("closed", fc.fc_crew.crew_record(self.proj, "shop-e2e"))
        self.assertNotIn(("tab", "close", "t10"), self.calls)  # never closed synchronously, mid-turn
        td, popen = report("shop-orchestrator")
        td.assert_called_once_with(self.proj)
        popen.assert_not_called()


    def test_scratch_files_stay_after_done_and_teardown(self):
        log = fc.fc_crew.scratch_dir(self.proj, "shop-e2e") / "repro.log"
        log.parent.mkdir(parents=True)
        log.write_text("evidence")
        with mock.patch.object(fc.fc_core, "project_dir", return_value=self.proj), mock.patch("builtins.print"), \
                mock.patch.object(fc.fc_herdr, "herdr", self.herdr), mock.patch.object(fc.fc_herdr, "herdr_env", return_value=True), \
                mock.patch.object(subprocess, "Popen"), mock.patch.object(fc.fc_crew, "stop_listeners_under", return_value=[]) as stop:
            fc.fc_crew.cmd_report(type("A", (), {"as_": "shop-e2e", "state": "done", "message": ["finished"]}))
            stop.assert_called_with(log.parent)  # servers it left listening are stopped
        self.assertEqual(log.read_text(), "evidence")
        self.teardown()
        self.assertEqual(log.read_text(), "evidence")

    def test_a_shared_space_closes_only_this_projects_tabs(self):
        fc.fc_herdr.space_record(self.proj).write_text(json.dumps({"space": "w9"}))  # the space compose was started from
        self.tabs = {"t1": "shop shell", "t2": "shop status", "t3": "shop orchestrator", "t4": "shop implementers", "t7": "shop verify",
                     "t9": "shop tests", "t10": "shop e2e", "t20": "1", "t21": "cart implementers", "t22": "cart verify", "t23": "verify"}
        self.agents = [("shop-orchestrator", "t3")]
        with mock.patch.object(fc.fc_herdr, "herdr_project_space", return_value="w9"):
            self.assertEqual(sorted(self.teardown()), ["implementers", "tests", "verify"])
        self.assertEqual(sorted(self.tabs), ["t1", "t10", "t2", "t20", "t21", "t22", "t23", "t3"])  # the caller's and another project's tabs stay


if __name__ == "__main__":
    unittest.main()
