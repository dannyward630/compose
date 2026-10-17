import contextlib, importlib.machinery, importlib.util, io, json, os, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import subprocess, sys
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)

CREW = {"orchestrator": "claude:claude-opus-5-5", "groundwork": "claude:claude-sonnet-5-5",
        "default": "claude:claude-sonnet-5-5", "small": "claude:claude-haiku-5-5"}
SERVERS = ["claude_ai_Linear", "trail"]  # cmd_crew asks fc_mcp.installed_servers; no test runs the real `claude mcp list`


class RoleModels(unittest.TestCase):
    """Teammate sessions are Claude Code; models.crew picks the model per role, and a model id always names its harness."""
    def setUp(self):
        p = mock.patch.object(fc.fc_models, "model_available", return_value=(True, "answered")); p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(fc.fc_mcp, "installed_servers", return_value=SERVERS); p.start(); self.addCleanup(p.stop)
        p = mock.patch.dict(os.environ, {"COMPOSE_ROLE": "orchestrator"}); p.start(); self.addCleanup(p.stop)  # the team lead starts every teammate here

    def config(self, crew):
        d = Path(tempfile.mkdtemp())
        (d / "config.json").write_text(json.dumps({"models": {"implementer": "pi:x/y", "crew": crew}}))
        with mock.patch.object(fc.fc_config, "CONFIG_PATH", d / "config.json"):
            fc.fc_config.apply_config()
        self.addCleanup(setattr, fc.fc_config, "CREW_MODELS", {})

    def test_an_entry_can_carry_an_effort(self):
        self.config({**CREW, "orchestrator": {"model": "claude:claude-sonnet-5-5", "effort": "high"}})
        self.addCleanup(setattr, fc.fc_config, "CREW_EFFORT", {})
        self.assertEqual(fc.fc_crew.crew_model("orchestrator"), "claude:claude-sonnet-5-5")
        self.assertEqual(fc.fc_crew.crew_effort("orchestrator"), "high")
        self.assertIsNone(fc.fc_crew.crew_effort("groundwork"))  # a plain string keeps Claude Code's default effort

    def test_role_then_default_then_small_then_explicit(self):
        self.config(CREW)
        self.assertEqual(fc.fc_crew.crew_model("orchestrator"), "claude:claude-opus-5-5")
        self.assertEqual(fc.fc_crew.crew_model("q-neb-12"), "claude:claude-sonnet-5-5")  # no entry: default
        self.assertEqual(fc.fc_crew.crew_model("revert", "small"), "claude:claude-haiku-5-5")
        self.assertEqual(fc.fc_crew.crew_model("orchestrator", "claude:claude-x"), "claude:claude-x")

    def test_no_crew_config_keeps_claude_default(self):
        self.config({})
        self.assertEqual(fc.fc_crew.crew_model("groundwork"), "claude")
        self.assertIsNone(fc.fc_claude.claude_id("claude"))

    def test_an_opencode_id_for_a_crew_is_refused_naming_the_key(self):
        self.config({"tests": "openai/gpt-x"})
        with self.assertRaises(SystemExit) as e:
            fc.fc_crew.crew_model("tests")
        self.assertIn("models.crew.tests", str(e.exception))
        with self.assertRaises(SystemExit) as e:
            fc.fc_crew.crew_model("tests", "openai/gpt-x")
        self.assertIn("--model", str(e.exception))
        self.assertEqual(fc.fc_crew.crew_model("tests", "pi:openai/gpt-6-astra"), "pi:openai/gpt-6-astra")

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
        with mock.patch.object(fc.fc_core, "project_dir", return_value=proj), mock.patch.object(fc.fc_herdr, "project_worktree", return_value=proj), \
                mock.patch.object(fc.fc_herdr, "herdr_env", return_value=True), mock.patch.object(fc.fc_herdr, "herdr", herdr), \
                mock.patch.object(fc.fc_herdr, "herdr_space", return_value="w9"), mock.patch.object(fc.fc_crew, "crew_preamble", return_value=""), mock.patch.object(fc.fc_frame0, "frame0_register"), \
                mock.patch.object(fc.fc_claude, "claude_trusted", return_value=True), mock.patch.object(fc.fc_herdr, "herdr_await_start"), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            fc.fc_crew.cmd_crew(a)
        self.assertIn("teammate p-groundwork started in tab 'groundwork' of space p on claude:claude-sonnet-5-5", out.getvalue())
        start = next(c for c in calls if c[:2] == ("agent", "start"))
        self.assertEqual(start[start.index("--model") + 1], "claude-sonnet-5-5")
        self.assertEqual(json.loads((proj / "results" / "crew" / "p-groundwork.json").read_text())["model"], "claude:claude-sonnet-5-5")

    def test_task_claude_model_routes_to_claude_code_with_that_model(self):
        with mock.patch.object(fc.fc_claude, "claude_once", return_value=(None, "", 0, {})) as co, mock.patch.object(fc.fc_models, "pi_turn") as pt:
            fc.fc_implement.implementer("/tmp", "claude:claude-opus-5-5", "hi")
            fc.fc_implement.implementer("/tmp", "claude", "hi")
        self.assertEqual([c.kwargs["model"] for c in co.call_args_list], ["claude-opus-5-5", None])
        pt.assert_not_called()
        self.assertIsNone(fc.fc_models.fallback_for("claude:claude-opus-5-5"))


PLANNER = {"planner": {"model": "claude:claude-fable-5-1", "fallback": {"model": "claude:claude-opus-5-5", "effort": "high"}},
           "groundwork": "claude:claude-opus-5-5", "default": "claude:claude-sonnet-5-5"}


class PlannerChain(unittest.TestCase):
    """Planning (the wayfinder teammate, never the team lead) runs on `planner`: its model when Claude Code can run it, else its fallback."""
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        (d / "config.json").write_text(json.dumps({"models": {"implementer": "pi:x/y", "crew": PLANNER}}))
        for p in (mock.patch.object(fc.fc_config, "CONFIG_PATH", d / "config.json"), mock.patch.object(fc.fc_config, "PROBE_CACHE", d / "probe.json"),
                  mock.patch.object(fc.fc_mcp, "installed_servers", return_value=SERVERS), mock.patch.dict(os.environ, {"COMPOSE_ROLE": "orchestrator"})):
            p.start(); self.addCleanup(p.stop)
        fc.fc_config.apply_config(); fc.fc_models._PROBED.clear()
        self.addCleanup(fc.fc_models._PROBED.clear)
        for k in ("CREW_MODELS", "CREW_EFFORT", "CREW_FALLBACK"):
            self.addCleanup(setattr, fc.fc_config, k, {})
        self.probe_cache = d / "probe.json"

    def probe(self, ok, down=("claude-fable-5-1",)):
        """Every probe answers when ok; otherwise the models in `down` refuse with "model not found" and the rest answer."""
        def run(cmd, **kw):
            bad = not ok and cmd[cmd.index("--model") + 1] in down
            out = json.dumps({"is_error": bad, "result": "model not found" if bad else "ok"})
            return subprocess.CompletedProcess(cmd, 1 if bad else 0, out, "")
        return mock.patch.object(subprocess, "run", side_effect=run)

    def test_planning_roles_use_the_planner_and_others_do_not(self):
        with self.probe(True):
            self.assertEqual(fc.fc_crew.crew_pick("wayfinder")[:2], ("claude:claude-fable-5-1", None))
            self.assertEqual(fc.fc_crew.crew_pick("orchestrator")[:2], ("claude:claude-sonnet-5-5", None))  # the team lead delegates, it does not plan
            self.assertEqual(fc.fc_crew.crew_pick("q-neb-12")[:2], ("claude:claude-sonnet-5-5", None))  # no per-question agents any more
            self.assertEqual(fc.fc_crew.crew_pick("groundwork")[:2], ("claude:claude-opus-5-5", None))
            self.assertEqual(fc.fc_crew.crew_pick("helper")[:2], ("claude:claude-sonnet-5-5", None))

    def test_fallback_when_the_planner_model_is_unavailable(self):
        with self.probe(False):
            model, effort, note = fc.fc_crew.crew_pick("wayfinder")
        self.assertEqual((model, effort), ("claude:claude-opus-5-5", "high"))
        self.assertIn("unavailable", note); self.assertIn("model not found", note)

    def test_the_fallbacks_are_tried_in_order(self):
        astra, fable, opus = "pi:openai/gpt-6-astra", "claude:claude-fable-5-1", "claude:claude-opus-5-5"
        chain = {"planner": {"model": astra, "effort": "high", "fallback": [fable, {"model": opus, "effort": "high"}]}}
        d = Path(tempfile.mkdtemp()); (d / "c.json").write_text(json.dumps({"models": {"crew": chain}}))
        with mock.patch.object(fc.fc_config, "CONFIG_PATH", d / "c.json"):
            fc.fc_config.apply_config()
        for up, want in (({fable, astra}, astra), ({fable}, fable), ({opus}, opus)):  # a pi session has the Linear MCP too, so astra is probed first
            fc.fc_models._PROBED.clear()
            with mock.patch.object(fc.fc_models, "model_available", side_effect=lambda m: (m in up, "down")):
                model, effort, note = fc.fc_crew.crew_pick("wayfinder")
            self.assertEqual(model, want)
        self.assertEqual(effort, "high")
        with mock.patch.object(fc.fc_models, "model_available", side_effect=lambda m: (False, "down")), self.assertRaises(SystemExit) as e:
            fc.fc_crew.crew_pick("wayfinder")  # the last of the chain is probed too: nothing runs, so it fails naming each model and why
        self.assertIn(f"{fable} unavailable (down)", str(e.exception)); self.assertIn(f"{opus} unavailable (down)", str(e.exception))
        self.assertIn("models.crew.planner", str(e.exception))
        self.assertIn(f"{astra} unavailable (down), {fable} unavailable (down), using its fallback", note)
        with mock.patch.object(fc.fc_models, "model_available", return_value=(True, "")):  # a role with no Linear need still takes the pi model
            self.assertEqual(fc.fc_crew.crew_pick("helper", "planner")[0], astra)

    def test_a_pi_model_is_probed_with_pi_and_judged_by_its_events(self):
        ok = subprocess.CompletedProcess([], 0, json.dumps({"type": "message_end", "message": {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}}), "")
        bad = subprocess.CompletedProcess([], 0, json.dumps({"type": "message_end", "message": {"role": "assistant", "content": [], "stopReason": "error", "errorMessage": "Model not found: x"}}), "")
        self.assertEqual(fc.fc_models.probe_result("pi:openai/gpt-6-astra", ok), (True, "answered"))
        self.assertEqual(fc.fc_models.probe_result("pi:openai/x", bad)[0], False)
        self.assertIn("Model not found", fc.fc_models.probe_result("pi:openai/x", bad)[1])
        self.assertEqual(fc.fc_models.probe_command("pi:openai/gpt-6-astra")[0], "pi")
        self.assertIn("openai/gpt-6-astra", fc.fc_models.probe_command("pi:openai/gpt-6-astra"))

    def test_a_lone_model_is_probed_and_a_refusal_fails_before_any_tab(self):
        calls = []
        proj = Path(tempfile.mkdtemp()) / "p"; (proj / "results").mkdir(parents=True)
        a = SimpleNamespace(action="start", role="explore", repo=str(proj), project="p", model=None, title=None,
                            brief="look", cwd=None, force=False)
        with self.probe(False, down=("claude-sonnet-5-5",)), mock.patch.object(fc.fc_herdr, "herdr", lambda *x, **k: calls.append(x)), \
                mock.patch.object(fc.fc_herdr, "herdr_env", return_value=True), mock.patch.object(fc.fc_core, "project_dir", return_value=proj), \
                mock.patch.object(fc.fc_herdr, "project_worktree", return_value=proj), self.assertRaises(SystemExit) as e:
            fc.fc_crew.cmd_crew(a)  # models.crew.default is one entry with no fallback
        self.assertIn("claude:claude-sonnet-5-5 unavailable (model not found)", str(e.exception))
        self.assertIn("models.crew.default", str(e.exception))
        self.assertEqual(calls, [])
        with self.assertRaises(SystemExit) as e:
            fc.fc_crew.crew_pick("explore", "claude:claude-sonnet-5-5")  # an explicit --model is probed too (cached for the day now)
        self.assertIn("--model", str(e.exception))

    def test_headless_claude_runs_carry_no_compose_env(self):
        lead = {"COMPOSE_ROLE": "orchestrator", "COMPOSE_PROJECT": "p", "COMPOSE_REPO": "/r"}  # the team lead's tab
        done = subprocess.CompletedProcess([], 0, json.dumps({"is_error": False, "result": "ok"}), "")
        with mock.patch.dict(os.environ, lead), mock.patch.object(subprocess, "run", return_value=done) as run:
            fc.fc_models.probe_once("claude:claude-haiku-5-5", 60)  # its Stop hook would otherwise park the lead's watch in the probe
            fc.fc_claude.claude_once(".", "hi")
        for call in run.call_args_list:
            self.assertEqual([k for k in call.kwargs.get("env") or os.environ if k.startswith("COMPOSE_")], [])

    def test_the_probe_runs_once_a_day(self):
        with self.probe(True) as run:
            fc.fc_crew.crew_pick("wayfinder"); fc.fc_crew.crew_pick("wayfinder")
            self.assertEqual(run.call_count, 1)
        fc.fc_models._PROBED.clear()  # a new CLI process the same day reads the cache file
        with self.probe(False) as run:
            self.assertEqual(fc.fc_crew.crew_pick("wayfinder")[0], "claude:claude-fable-5-1")
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
        with self.probe(False), mock.patch.object(fc.fc_herdr, "herdr", herdr), mock.patch.object(fc.fc_herdr, "herdr_env", return_value=True), \
                mock.patch.object(fc.fc_core, "project_dir", return_value=proj), mock.patch.object(fc.fc_herdr, "project_worktree", return_value=proj), \
                mock.patch.object(fc.fc_herdr, "herdr_space", return_value="w9"), mock.patch.object(fc.fc_crew, "crew_preamble", return_value=""), \
                mock.patch.object(fc.fc_crew, "write_report"), mock.patch.object(fc.fc_frame0, "frame0_register"), mock.patch.object(fc.fc_claude, "claude_trusted", return_value=True), mock.patch.object(fc.fc_herdr, "herdr_await_start"), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            fc.fc_crew.cmd_crew(a)
        self.assertIn("WARNING: wayfinder wanted its first-choice model but claude:claude-fable-5-1 unavailable", out.getvalue())
        self.assertIn("teammate p-wayfinder started in tab 'wayfinder' of space p on claude:claude-opus-5-5 (high effort)", out.getvalue())
        start = next(c for c in calls if c[:2] == ("agent", "start"))
        self.assertIn("claude-opus-5-5", start); self.assertIn("--effort", start); self.assertIn("high", start)
        rec = json.loads(next((proj / "results" / "crew").glob("*.json")).read_text())
        self.assertEqual((rec["model"], rec["effort"]), ("claude:claude-opus-5-5", "high"))


class DesignerModels(unittest.TestCase):
    """design-NNN builders fall to models.crew.design; the designer defaults to Opus 5.5 at high effort."""
    def setUp(self):
        p = mock.patch.object(fc.fc_models, "model_available", return_value=(True, "answered")); p.start(); self.addCleanup(p.stop)
        p = mock.patch.object(fc.fc_mcp, "installed_servers", return_value=SERVERS); p.start(); self.addCleanup(p.stop)

    def config(self, crew):
        d = Path(tempfile.mkdtemp())
        (d / "config.json").write_text(json.dumps({"models": {"implementer": "pi:x/y", "crew": crew}}))
        with mock.patch.object(fc.fc_config, "CONFIG_PATH", d / "config.json"), mock.patch.object(fc.fc_config, "PROBE_CACHE", d / "probe.json"):
            fc.fc_config.apply_config()
        for k in ("CREW_MODELS", "CREW_EFFORT", "CREW_FALLBACK"): self.addCleanup(setattr, fc.fc_config, k, {})

    def test_design_roles_use_the_design_entry_else_default(self):
        self.config({**CREW, "design": {"model": "claude:claude-opus-5-5", "effort": "high"}})
        for role in ("design-003", "design-review"):
            self.assertEqual(fc.fc_crew.crew_pick(role)[:2], ("claude:claude-opus-5-5", "high"))
        self.assertEqual(fc.fc_crew.crew_pick("designs-003")[:2], ("claude:claude-sonnet-5-5", None))  # first word is designs
        self.config(CREW); self.assertEqual(fc.fc_crew.crew_pick("design-003")[:2], ("claude:claude-sonnet-5-5", None))

    def test_the_designer_defaults_to_opus_high_unless_configured(self):
        for crew in ({}, {**CREW, "design": "claude:claude-haiku-5-5"}):
            self.config(crew)
            self.assertEqual(fc.fc_crew.crew_pick("designer"), ("claude:claude-opus-5-5", "high", "models.crew.designer default"))
        self.config({**CREW, "designer": "claude:claude-sonnet-5-5"}); self.assertEqual(fc.fc_crew.crew_pick("designer"), ("claude:claude-sonnet-5-5", None, "models.crew.designer"))


class PiKeepsLinear(unittest.TestCase):
    """A pi session loads its MCP servers (Linear among them), so the Linear roles probe a pi model like any other."""
    astra, sonnet = "pi:openai/gpt-6-astra", "claude:claude-sonnet-5-5"
    setUp = PlannerChain.setUp

    def chain(self, role):
        d = Path(tempfile.mkdtemp()); (d / "c.json").write_text(json.dumps({"models": {"crew": {role: {"model": self.astra, "fallback": self.sonnet}}}}))
        with mock.patch.object(fc.fc_config, "CONFIG_PATH", d / "c.json"):
            fc.fc_config.apply_config()
        fc.fc_models._PROBED.clear()

    def test_linear_roles_take_the_pi_model(self):
        self.assertFalse(hasattr(fc, "LINEAR_ROLES"))
        for role in ("wayfinder", "planner", "designer", "planner-2"):
            self.chain(role.split("-")[0])
            with mock.patch.object(fc.fc_models, "model_available", return_value=(True, "")) as probe:
                model, _, note, skipped = fc.fc_crew.crew_pick_full(role)
            self.assertEqual((model, skipped), (self.astra, []), role)
            self.assertNotIn("Linear", note)
            self.assertEqual(probe.call_args_list[0].args, (self.astra,))  # probed, not filtered out

    def test_a_failed_pi_probe_reports_its_error(self):
        for role in ("wayfinder", "planner", "designer"):
            self.chain(role)
            with mock.patch.object(fc.fc_models, "model_available", side_effect=lambda m: (m != self.astra, "model not found")):
                model, _, note, skipped = fc.fc_crew.crew_pick_full(role)
            self.assertEqual(model, self.sonnet)
            self.assertEqual(skipped, [f"{self.astra} unavailable (model not found)"])
            self.assertNotIn("a pi session has no Linear tools", note)
        with mock.patch.object(fc.fc_models, "model_available", return_value=(False, "down")), self.assertRaises(SystemExit) as e:
            fc.fc_crew.crew_pick_full("designer")  # nothing runs: still exits naming each probe error
        self.assertIn(f"{self.astra} unavailable (down)", str(e.exception))


if __name__ == "__main__":
    unittest.main()
