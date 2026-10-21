import hermetic  # first: no test sees the real home
import importlib, importlib.machinery, importlib.util, json, os, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock
import sys
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_depth  # noqa: E402


class StackDepth(unittest.TestCase):
    """The stack's depth is its deepest code task's route depth."""


class DepthConfig(unittest.TestCase):
    """The verify settings at the stack's depth."""


CFG = {"review": True, "jev_acceptance": True, "e2e": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}
SHA = "0123456789abcdef0123456789abcdef01234567"


class DepthEvents(unittest.TestCase):
    """The stages the depth skips go on the feature's ledger."""
    def setUp(self):
        self.ledger = importlib.import_module("fc_ledger")  # the foundation's module, not on every branch
        self.repo = Path(tempfile.mkdtemp()).resolve(); self.proj = self.repo / ".compose" / "p"; self.proj.mkdir(parents=True)
        (self.proj / "linear.json").write_text(json.dumps({"feature": "ENG-1"}))
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=self.repo, check=True, capture_output=True, text=True)
        git("init", "-q", "-b", "main"); (self.repo / "a.txt").write_text("x"); git("add", "-A"); git("commit", "-qm", "init")
        self.head = git("rev-parse", "HEAD").stdout.strip()

    def events(self, cfg, run_cfg, depth="FAST", sha=SHA):
        return fc_depth.depth_events(cfg, run_cfg, depth, "061", sha)

    def expect(self, got, stages, sha=SHA, depth="FAST"):
        self.assertEqual(len(got), len(stages))
        for e, stage in zip(got, stages):
            self.assertEqual(e, self.ledger.event("", sha, [], [], e["phase"], "verify", "skipped", None, f"{stage} skipped at depth {depth} (deepest task 061)"))

    def test_fast_skips_review_acceptance_and_the_left_out_e2e_cases_in_order(self):
        self.expect(self.events(CFG, {"review": False, "e2e": [{"name": "b"}]}), ["review", "acceptance", "e2e a", "e2e c"])

    def test_only_the_stages_cfg_runs_and_run_cfg_does_not_are_skipped(self):
        self.expect(self.events({**CFG, "review": False, "jev_acceptance": False}, {"review": False, "e2e": []}), ["e2e a", "e2e b", "e2e c"])
        self.expect(self.events(CFG, {"review": True, "e2e": CFG["e2e"]}), ["acceptance"])
        self.expect(self.events({"e2e": [{"name": "a"}]}, {"review": False, "e2e": []}), ["review", "acceptance", "e2e a"])  # review and acceptance default on

    def test_standard_and_deep_give_no_events(self):
        for depth in ("STANDARD", "DEEP"):
            self.assertEqual(self.events(CFG, {"review": True, "e2e": CFG["e2e"]}, depth), [])

    def test_record_depth_writes_the_events_on_the_feature_once_at_head(self):
        run_cfg = {"review": False, "e2e": [{"name": "a"}]}
        with mock.patch.object(self.ledger, "add_row", return_value=False) as add_row:
            self.assertIs(fc_depth.record_depth(self.proj, self.repo, CFG, run_cfg, "FAST", "061"), False)
        add_row.assert_called_once_with("ENG-1", self.events(CFG, run_cfg, sha=self.head))

    def test_record_depth_with_no_events_returns_true_without_add_row(self):
        with mock.patch.object(self.ledger, "add_row") as add_row:
            self.assertIs(fc_depth.record_depth(self.proj, self.repo, CFG, {"review": True, "e2e": CFG["e2e"]}, "DEEP", "061"), True)
        add_row.assert_not_called()


class VerifyDepth(unittest.TestCase):
    """verify runs the stages of the stack's deepest task."""
