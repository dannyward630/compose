import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, io, json, os, subprocess, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import sys
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_ledger  # noqa: E402


class DoneEvidence(unittest.TestCase):
    def setUp(self):
        self.proj, self.repo = Path(tempfile.mkdtemp()) / "feat", Path(tempfile.mkdtemp())
        (self.proj / "results").mkdir(parents=True)
        git = lambda *args: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()
        git("init", "-q", "-b", "main"); (self.repo / "a.py").write_text("1\n"); git("add", "-A"); git("commit", "-q", "-m", "a")
        git("branch", "task-021"); self.tip = git("rev-parse", "task-021")
        (self.proj / "verify.json").write_text('{"task_prefix": "task-"}')
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"tasks": [{"id": "021", "title": "a", "linear": "ENG-4"}, {"id": "022", "title": "b", "linear": "ENG-5"}, {"id": "023", "title": "c"}]}))
        self.calls = mock.Mock()
        for mod, name, kw in ((fc.fc_core, "project_dir", {"return_value": self.proj}), (fc_ledger, "run_id", {"side_effect": lambda proj, tid: "run-" + tid}),
                              (fc_ledger, "criterion_ids", {"side_effect": lambda meta: [meta["id"] + ".1:x"]}), (fc_ledger, "event", {"side_effect": lambda *a: a}),
                              (fc_ledger, "record", {"return_value": True}), (fc_ledger, "record_task", {"return_value": True}), (fc.fc_linear, "linear_event", {})):
            p = mock.patch.object(mod, name, **kw); self.calls.attach_mock(p.start(), name); self.addCleanup(p.stop)

    def done(self, only):
        out = io.StringIO()
        with redirect_stdout(out):
            fc.fc_status.cmd_done(SimpleNamespace(repo=str(self.repo), only=only, note="by hand"))
        return out.getvalue()

    def recorded(self):
        """(issue, events) per write, in call order: `record(issue, events)` or `record_task(repo, proj, meta, events)`."""
        return [c[1] if c[0] == "record" else (c[1][2].get("linear"), c[1][3]) for c in self.calls.mock_calls if c[0] in ("record", "record_task")]

    def test_each_task_records_one_done_event_on_its_own_issue(self):
        (self.proj / "results" / "021.json").write_text('{"branch": "task-021"}')
        self.done("021,022,023")
        done = lambda tid, sha: [(f"run-{tid}", sha, [tid], [f"{tid}.1:x"], "done", "done", "pass", None, "hand done: by hand")]
        self.assertEqual(self.recorded(), [("ENG-4", done("021", self.tip)), ("ENG-5", done("022", "")), (None, done("023", ""))])

    def test_the_write_is_recorded_once_beside_the_hand_done_linear_event(self):
        self.done("021")
        names = [c[0] for c in self.calls.mock_calls if c[0] in ("linear_event", "record", "record_task")]
        self.assertIn(names, (["linear_event", "record"], ["record_task", "linear_event"]))

    def test_unknown_id_records_nothing_and_writes_no_result(self):
        out = self.done("999")
        self.assertEqual((out, self.recorded(), list((self.proj / "results").glob("999.json"))), ("999: no such task (run `compose sync` if it is new on Linear)\n", [], []))
