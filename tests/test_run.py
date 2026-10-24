import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, json, os, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)

STANDARD = "claude:claude-sonnet-5-5"
OTHER = "claude:claude-opus-5-5"


def route(depth): return f"## Route\n\n* workflow: test-first\n* depth: {depth}\n"


class SuiteAfterEachTask(unittest.TestCase):
    def test_a_whole_suite_in_the_checks_a_task_runs_is_warned_about_with_the_task_count(self):
        said = fc.fc_run.suite_warning({"checks": ["ruff check .", "python3 -m tests.run"]}, 33)
        self.assertIn("`python3 -m tests.run`", said)
        self.assertIn("after each of the 33 tasks", said)
        self.assertIn("task_checks", said)

    def test_no_warning_for_cheap_checks_task_checks_or_one_task(self):
        for cfg, n in (({"checks": ["ruff check ."]}, 33), ({"checks": ["python3 -m tests.run"], "task_checks": ["ruff check ."]}, 33), ({"checks": ["python3 -m tests.run"]}, 1), ({}, 33)):
            self.assertIsNone(fc.fc_run.suite_warning(cfg, n))


class RunStartsOnTier(unittest.TestCase):
    def setUp(self):
        self.proj = Path(tempfile.mkdtemp()) / ".compose" / "p"
        (self.proj / "results").mkdir(parents=True)
        issues = {"NEB-1": {"description": route("DEEP")}, "NEB-2": {"description": route("FAST")}}
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": [], "issues": issues}))

    def run_tasks(self, *tasks):
        """Runs `run_tasks` up to preflight; returns the models preflight was asked about."""
        seen = []
        def stop(models): seen.append(set(models)); raise SystemExit("stop")
        with mock.patch.object(fc.fc_run, "preflight", side_effect=stop), mock.patch.object(fc.fc_proc, "keep_awake"), self.assertRaises(SystemExit):
            fc.fc_run.run_tasks(self.proj.parent.parent, self.proj, list(tasks), SimpleNamespace(trunk=None, no_stack=True))
        return seen[0]

    def task(self, tid, linear, model=OTHER, auto=True):
        return {"id": tid, "linear": linear, "model": model, **({"model_auto": True} if auto else {})}

    def test_a_deep_auto_task_reaches_preflight_on_standard(self):
        t = self.task("001", "NEB-1")
        self.assertIn(STANDARD, self.run_tasks(t))
        self.assertEqual(t["model"], STANDARD)

    def test_a_fast_auto_task_reaches_preflight_on_the_default_implementer(self):
        t = self.task("001", "NEB-2")
        self.assertIn(fc.fc_config.DEFAULT_MODEL, self.run_tasks(t))
        self.assertEqual(t["model"], fc.fc_config.DEFAULT_MODEL)

    def test_a_task_with_its_own_model_keeps_it_whatever_the_route(self):
        t = self.task("001", "NEB-1", model="pi:a/b", auto=False)
        self.assertIn("pi:a/b", self.run_tasks(t))
        self.assertEqual(t["model"], "pi:a/b")

    def test_every_task_gets_its_own_start_model(self):
        deep, fast, own = self.task("001", "NEB-1"), self.task("002", "NEB-2"), self.task("003", "NEB-1", model="pi:a/b", auto=False)
        seen = self.run_tasks(deep, fast, own)
        self.assertEqual([t["model"] for t in (deep, fast, own)], [STANDARD, fc.fc_config.DEFAULT_MODEL, "pi:a/b"])
        self.assertLessEqual({STANDARD, fc.fc_config.DEFAULT_MODEL, "pi:a/b"}, seen)

