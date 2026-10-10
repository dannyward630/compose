import importlib.machinery, importlib.util, json, os, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)

CREW = {"orchestrator": "claude:claude-opus-5-5", "groundwork": "claude:claude-sonnet-5-5",
        "default": "claude:claude-sonnet-5-5", "small": "claude:claude-haiku-5-5"}


class RoleModels(unittest.TestCase):
    """Crew sessions are Claude Code; models.crew picks the model per role, and a model id always names its harness."""
    def config(self, crew):
        d = Path(tempfile.mkdtemp())
        (d / "config.json").write_text(json.dumps({"models": {"implementer": "pi:x/y", "crew": crew}}))
        with mock.patch.object(fc, "CONFIG_PATH", d / "config.json"):
            fc.apply_config()
        self.addCleanup(setattr, fc, "CREW_MODELS", {})

    def test_an_entry_can_carry_an_effort(self):
        self.config({**CREW, "orchestrator": {"model": "claude:claude-sonnet-5-5", "effort": "high"}})
        self.addCleanup(setattr, fc, "CREW_EFFORT", {})
        self.assertEqual(fc.crew_model("orchestrator"), "claude:claude-sonnet-5-5")
        self.assertEqual(fc.crew_effort("orchestrator"), "high")
        self.assertIsNone(fc.crew_effort("groundwork"))  # a plain string keeps Claude Code's default effort

    def test_role_then_default_then_small_then_explicit(self):
        self.config(CREW)
        self.assertEqual(fc.crew_model("orchestrator"), "claude:claude-opus-5-5")
        self.assertEqual(fc.crew_model("q-neb-12"), "claude:claude-sonnet-5-5")  # no entry: default
        self.assertEqual(fc.crew_model("revert", "small"), "claude:claude-haiku-5-5")
        self.assertEqual(fc.crew_model("orchestrator", "claude:claude-x"), "claude:claude-x")

    def test_no_crew_config_keeps_claude_default(self):
        self.config({})
        self.assertEqual(fc.crew_model("groundwork"), "claude")
        self.assertIsNone(fc.claude_id("claude"))

    def test_pi_for_a_crew_is_refused_naming_the_key(self):
        self.config({"tests": "pi:openrouter-fast/z-ai/glm-5.3-flash"})
        with self.assertRaises(SystemExit) as e:
            fc.crew_model("tests")
        self.assertIn("models.crew.tests", str(e.exception))
        with self.assertRaises(SystemExit) as e:
            fc.crew_model("tests", "openai/gpt-x")
        self.assertIn("--model", str(e.exception))

    def test_crew_start_passes_the_model_to_claude_code(self):
        self.config(CREW)
        proj = Path(tempfile.mkdtemp()) / "p"; (proj / "results").mkdir(parents=True)
        calls = []
        def herdr(*args, check=False, timeout=120):
            calls.append(args)
            if args[:2] == ("tab", "create"):
                return {"tab": {"tab_id": "w9:t1"}, "root_pane": {"pane_id": "w9:p1"}}
            return None
        a = SimpleNamespace(action="start", role="groundwork", title="groundwork", brief="do it", force=False, cwd=None, model=None)
        with mock.patch.object(fc, "project_dir", return_value=proj), mock.patch.object(fc, "project_worktree", return_value=proj), \
                mock.patch.object(fc, "herdr_env", return_value=True), mock.patch.object(fc, "herdr", herdr), \
                mock.patch.object(fc, "herdr_space", return_value="w9"), mock.patch.object(fc, "crew_preamble", return_value=""):
            fc.cmd_crew(a)
        start = next(c for c in calls if c[:2] == ("agent", "start"))
        self.assertEqual(start[start.index("--model") + 1], "claude-sonnet-5-5")
        self.assertEqual(json.loads((proj / "results" / "crew" / "p-groundwork.json").read_text())["model"], "claude:claude-sonnet-5-5")

    def test_task_claude_model_routes_to_claude_code_with_that_model(self):
        with mock.patch.object(fc, "claude_once", return_value=(None, "", 0, {})) as co, mock.patch.object(fc, "pi_turn") as pt:
            fc.implementer("/tmp", "claude:claude-opus-5-5", "hi")
            fc.implementer("/tmp", "claude", "hi")
        self.assertEqual([c.kwargs["model"] for c in co.call_args_list], ["claude-opus-5-5", None])
        pt.assert_not_called()
        self.assertIsNone(fc.fallback_for("claude:claude-opus-5-5"))


if __name__ == "__main__":
    unittest.main()
