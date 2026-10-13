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
    """Teammate sessions are Claude Code; models.crew picks the model per role, and a model id always names its harness."""
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

    def test_an_opencode_id_for_a_crew_is_refused_naming_the_key(self):
        self.config({"tests": "openai/gpt-x"})
        with self.assertRaises(SystemExit) as e:
            fc.crew_model("tests")
        self.assertIn("models.crew.tests", str(e.exception))
        with self.assertRaises(SystemExit) as e:
            fc.crew_model("tests", "openai/gpt-x")
        self.assertIn("--model", str(e.exception))
        self.assertEqual(fc.crew_model("tests", "pi:openai/gpt-6-astra"), "pi:openai/gpt-6-astra")

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
                mock.patch.object(fc, "herdr_space", return_value="w9"), mock.patch.object(fc, "crew_preamble", return_value=""), mock.patch.object(fc, "frame0_register"), \
                mock.patch.object(fc, "claude_trusted", return_value=True):
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


PLANNER = {"planner": {"model": "claude:claude-fable-5-1", "fallback": {"model": "claude:claude-opus-5-5", "effort": "high"}},
           "groundwork": "claude:claude-opus-5-5", "default": "claude:claude-sonnet-5-5"}


class PlannerChain(unittest.TestCase):
    """Planning (the wayfinder teammate, never the team lead) runs on `planner`: its model when Claude Code can run it, else its fallback."""
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        (d / "config.json").write_text(json.dumps({"models": {"implementer": "pi:x/y", "crew": PLANNER}}))
        for p in (mock.patch.object(fc, "CONFIG_PATH", d / "config.json"), mock.patch.object(fc, "PROBE_CACHE", d / "probe.json")):
            p.start(); self.addCleanup(p.stop)
        fc.apply_config(); fc._PROBED.clear()
        self.addCleanup(fc._PROBED.clear)
        for k in ("CREW_MODELS", "CREW_EFFORT", "CREW_FALLBACK"):
            self.addCleanup(setattr, fc, k, {})
        self.probe_cache = d / "probe.json"

    def probe(self, ok):
        out = json.dumps({"is_error": not ok, "result": "ok" if ok else "model not found"})
        return mock.patch.object(fc.subprocess, "run", return_value=fc.subprocess.CompletedProcess([], 0 if ok else 1, out, ""))

    def test_planning_roles_use_the_planner_and_others_do_not(self):
        with self.probe(True):
            self.assertEqual(fc.crew_pick("wayfinder")[:2], ("claude:claude-fable-5-1", None))
            self.assertEqual(fc.crew_pick("orchestrator")[:2], ("claude:claude-sonnet-5-5", None))  # the team lead delegates, it does not plan
            self.assertEqual(fc.crew_pick("q-neb-12")[:2], ("claude:claude-sonnet-5-5", None))  # no per-question agents any more
            self.assertEqual(fc.crew_pick("groundwork")[:2], ("claude:claude-opus-5-5", None))
            self.assertEqual(fc.crew_pick("helper")[:2], ("claude:claude-sonnet-5-5", None))

    def test_fallback_when_the_planner_model_is_unavailable(self):
        with self.probe(False):
            model, effort, note = fc.crew_pick("wayfinder")
        self.assertEqual((model, effort), ("claude:claude-opus-5-5", "high"))
        self.assertIn("unavailable", note); self.assertIn("model not found", note)

    def test_the_fallbacks_are_tried_in_order(self):
        astra, fable, opus = "pi:openai/gpt-6-astra", "claude:claude-fable-5-1", "claude:claude-opus-5-5"
        chain = {"planner": {"model": astra, "effort": "high", "fallback": [fable, {"model": opus, "effort": "high"}]}}
        d = Path(tempfile.mkdtemp()); (d / "c.json").write_text(json.dumps({"models": {"crew": chain}}))
        with mock.patch.object(fc, "CONFIG_PATH", d / "c.json"):
            fc.apply_config()
        for up, want in (({astra}, astra), ({fable, astra}, astra), ({fable}, fable), (set(), opus)):  # the last is never probed
            fc._PROBED.clear()
            with mock.patch.object(fc, "model_available", side_effect=lambda m: (m in up, "down")):
                model, effort, note = fc.crew_pick("wayfinder")
            self.assertEqual(model, want)
        self.assertEqual(effort, "high")
        self.assertIn(f"{astra} unavailable (down), {fable} unavailable (down), using its fallback", note)

    def test_a_pi_model_is_probed_with_pi_and_judged_by_its_events(self):
        ok = fc.subprocess.CompletedProcess([], 0, json.dumps({"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}}), "")
        bad = fc.subprocess.CompletedProcess([], 0, json.dumps({"type": "message_end", "message": {"role": "assistant", "content": [], "stopReason": "error", "errorMessage": "Model not found: x"}}), "")
        self.assertEqual(fc.probe_result("pi:openai/gpt-6-astra", ok), (True, "answered"))
        self.assertEqual(fc.probe_result("pi:openai/x", bad)[0], False)
        self.assertIn("Model not found", fc.probe_result("pi:openai/x", bad)[1])
        self.assertEqual(fc.probe_command("pi:openai/gpt-6-astra")[0], "pi")
        self.assertIn("openai/gpt-6-astra", fc.probe_command("pi:openai/gpt-6-astra"))

    def test_the_probe_runs_once_a_day(self):
        with self.probe(True) as run:
            fc.crew_pick("wayfinder"); fc.crew_pick("wayfinder")
            self.assertEqual(run.call_count, 1)
        fc._PROBED.clear()  # a new CLI process the same day reads the cache file
        with self.probe(False) as run:
            self.assertEqual(fc.crew_pick("wayfinder")[0], "claude:claude-fable-5-1")
            run.assert_not_called()
        self.assertIn("claude-fable-5-1", json.loads(self.probe_cache.read_text()))

    def test_crew_start_passes_the_chosen_model_and_effort(self):
        calls = []
        def herdr(*args, check=False, timeout=120):
            calls.append(args)
            if args[:2] == ("tab", "create"):
                return {"tab": {"tab_id": "w9:t9"}, "root_pane": {"pane_id": "w9:p1"}}
            return {}
        proj = Path(tempfile.mkdtemp()) / "p"; (proj / "results").mkdir(parents=True)
        a = SimpleNamespace(action="start", role="wayfinder", repo=str(proj), project="p", model=None, title=None,
                            brief="plan it", cwd=None, force=False)
        with self.probe(False), mock.patch.object(fc, "herdr", herdr), mock.patch.object(fc, "herdr_env", return_value=True), \
                mock.patch.object(fc, "project_dir", return_value=proj), mock.patch.object(fc, "project_worktree", return_value=proj), \
                mock.patch.object(fc, "herdr_space", return_value="w9"), mock.patch.object(fc, "crew_preamble", return_value=""), \
                mock.patch.object(fc, "write_report"), mock.patch.object(fc, "frame0_register"), mock.patch.object(fc, "claude_trusted", return_value=True):
            fc.cmd_crew(a)
        start = next(c for c in calls if c[:2] == ("agent", "start"))
        self.assertIn("claude-opus-5-5", start); self.assertIn("--effort", start); self.assertIn("high", start)
        rec = json.loads(next((proj / "results" / "crew").glob("*.json")).read_text())
        self.assertEqual((rec["model"], rec["effort"]), ("claude:claude-opus-5-5", "high"))


if __name__ == "__main__":
    unittest.main()
