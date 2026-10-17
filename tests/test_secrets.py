import importlib.machinery, importlib.util, io, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(ROOT / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)

KEY = "sk-or-v1-test" + "0" * 52  # the workspace's OpenRouter key
TYPESAFE = "ts-test-" + "1" * 32  # set under `env` in the config
OTHER = "other-test-" + "2" * 32  # any *_API_KEY under `env`
DOTENV = "dotenv-test-" + "3" * 32  # TEXT_MODEL_API_KEY in ~/.compose/.env
SECRET_NAMES = ("OPENROUTER_API_KEY", "TEXT_MODEL_API_KEY", "TYPESAFE_API_KEY", "OPENCODE_CONFIG_CONTENT", "OTHER_API_KEY")
GIT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


class Secrets(unittest.TestCase):
    """compose's keys never reach project code's env, and never a text it sends to a model or writes to results/."""
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        cfg = self.root / "home" / "config.json"
        cfg.parent.mkdir()
        cfg.write_text(json.dumps({"openrouter_api_key": KEY, "env": {"TYPESAFE_API_KEY": TYPESAFE, "OTHER_API_KEY": OTHER, "PLAIN": "x"}}))
        (cfg.parent / ".env").write_text(f"TEXT_MODEL_API_KEY={DOTENV}\n")
        for p in (mock.patch.object(fc.fc_config, "CONFIG_PATH", cfg), mock.patch.object(fc.fc_config, "ENV_FILE", cfg.parent / ".env"),
                  mock.patch.object(fc.fc_config, "OPENROUTER_KEY", None), mock.patch.object(fc.fc_config, "LINEAR_KEY", None),
                  mock.patch.object(fc.fc_core, "SECRET_VARS", set(fc.fc_core.SECRET_VARS)), mock.patch.object(fc.fc_core, "SECRET_VALUES", set()),
                  mock.patch.dict(os.environ, {**GIT, "OPENCODE_CONFIG_CONTENT": "{}"})):
            p.start()
            self.addCleanup(p.stop)
        fc.fc_config.apply_config()

    def assertClean(self, text, names=True):
        for v in (KEY, TYPESAFE, OTHER, DOTENV):
            self.assertNotIn(v, text)
        for n in SECRET_NAMES if names else ():
            self.assertNotIn(n, text)

    def run_task(self, test):
        """One task whose test is `test`: the first attempt misses, the second passes. Returns (project dir, prompts)."""
        repo, proj = self.root / "repo", self.root / "proj"
        repo.mkdir(); proj.mkdir()
        git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        (repo / "a.txt").write_text("no\n")
        git("add", "-A"); git("commit", "-qm", "init")
        task = {"id": "001", "title": "answer", "files": ["a.txt"], "protected": [], "test": test, "model": "pi:p/m",
                "after": "", "linear": "ENG-1", "body": "## Goal\nWrite yes."}
        prompts = []
        def impl(cwd, model, prompt, session=None, task=None, timeout=None):
            prompts.append(prompt)
            (Path(cwd) / "a.txt").write_text(("a" if len(prompts) == 1 else "yes") + "\n")
            return "s", "", 1, {"tokens_in": 1, "tokens_out": 1, "cost": 0.0}
        with mock.patch.object(fc.fc_models, "pi_turn", impl), mock.patch.object(fc.fc_implement, "graft_pack", return_value=""), \
                mock.patch.object(fc.fc_implement, "condense_failure", return_value=""), mock.patch.object(fc.fc_linear, "linear_event"):
            r = fc.fc_implement.run_task(repo, proj, task, 3)
        self.assertEqual(r["status"], "passed")
        return proj, prompts

    def results_text(self, proj):
        return "\n".join(f.read_text() for f in sorted((proj / "results").rglob("*")) if f.is_file())

    # ---------- the env half ----------

    def test_a_task_test_runs_without_the_secret_vars(self):
        proj, prompts = self.run_task("python3 -c \"import os; assert open('a.txt').read().strip()=='yes', sorted(os.environ)\"")
        log = (proj / "results" / "001.test.log").read_text()
        self.assertIn("PLAIN", log)  # the rest of the env is there
        self.assertClean(log)
        self.assertClean(prompts[1])

    def test_compose_timed_runs_the_command_without_them(self):
        env = {**os.environ, "OPENROUTER_API_KEY": KEY, "TYPESAFE_API_KEY": TYPESAFE}
        p = subprocess.run([sys.executable, str(ROOT / "bin" / "compose.py"), "timed", "30", "--", "env"], capture_output=True, text=True, env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("PATH=", p.stdout)
        self.assertNotIn("OPENROUTER_API_KEY", p.stdout)
        self.assertNotIn("TYPESAFE_API_KEY", p.stdout)
        self.assertNotIn(KEY, p.stdout)

    def test_verify_checks_and_e2e_drivers_run_without_them(self):
        r = fc.fc_jev.driver_e2e({"name": "d", "setup": f"env > {self.root / 'setup-env'}", "setup_wait": 1, "driver": "env; exit 1"}, self.root)
        self.assertIn("PLAIN", r["stdout"])
        self.assertClean(r["stdout"])
        self.assertClean((self.root / "setup-env").read_text())
        a = SimpleNamespace(skip_e2e=True, skip_review=True)
        with mock.patch.object(fc.fc_herdr, "herdr_verify_panes", return_value={}):
            ok, report, findings = fc.fc_verify.run_stages(self.root, self.root, {"checks": ["env; exit 1"]}, a)
        self.assertFalse(ok)
        self.assertIn("PLAIN", report["checks"][0]["output"])
        self.assertClean(report["checks"][0]["output"])
        self.assertClean(findings)

    def test_harnesses_get_the_key_but_not_in_the_env_their_tools_inherit(self):
        run = mock.Mock(return_value=mock.Mock(stdout='{"type":"tool_execution_start"}', stderr="", returncode=0))
        with mock.patch.object(subprocess, "run", run):
            fc.fc_models.pi_turn(str(self.root), "openrouter-fast/x/y", "hi")
        cmd, env = run.call_args[0][0], run.call_args[1]["env"]
        self.assertEqual(cmd[cmd.index("--api-key") + 1], KEY)
        self.assertIn("PLAIN", env)
        self.assertClean(json.dumps(env))

        run = mock.Mock(return_value=mock.Mock(stdout='{"type":"text","sessionID":"s","part":{"text":"ok"}}', stderr="", returncode=0))
        with mock.patch.object(subprocess, "run", run):
            fc.fc_models.opencode(str(self.root), "openrouter/x", "hi")
        env = run.call_args[1]["env"]
        self.assertClean(json.dumps({k: v for k, v in env.items() if k != "OPENCODE_CONFIG_CONTENT"}))
        self.assertNotIn(KEY, env["OPENCODE_CONFIG_CONTENT"])
        f = Path(json.loads(env["OPENCODE_CONFIG_CONTENT"])["provider"]["openrouter"]["options"]["apiKey"][len("{file:"):-1])
        self.assertEqual(f.read_text(), KEY)
        self.assertEqual(oct(f.stat().st_mode & 0o777), "0o600")

        self.assertClean(json.dumps(fc.fc_claude.headless_env()))

    def test_the_herdr_pi_pane_gets_no_key_in_its_env(self):
        panes, starts = [], []
        with mock.patch.object(fc.fc_herdr, "herdr", return_value=None), \
                mock.patch.object(fc.fc_herdr, "herdr_implementer_pane", lambda space, cwd, env: panes.append(env) or "p1"), \
                mock.patch.object(fc.fc_herdr, "herdr_agent_start", lambda *a: starts.append(a) or {}), \
                mock.patch.object(fc.fc_herdr, "herdr_error", return_value=(None, "timeout")):
            with self.assertRaises(subprocess.TimeoutExpired):
                fc.fc_implement.herdr_pi(str(self.root / "wt"), "openrouter-fast/x/y", "hi", None,
                                         {"meta": {"id": "001"}, "proj": self.root / "proj", "space": "s"}, timeout=1)
        self.assertClean(json.dumps(panes[0]))
        self.assertEqual(starts[0][starts[0].index("--api-key") + 1], KEY)

    # ---------- the scrub half ----------

    def test_test_output_that_prints_a_key_is_scrubbed_everywhere_it_goes(self):
        (self.root / "leak").write_text(f"{KEY} {TYPESAFE} {OTHER} {DOTENV}")
        proj, prompts = self.run_task(f"python3 -c \"print(open('{self.root / 'leak'}').read()); assert open('a.txt').read().strip()=='yes'\"")
        self.assertIn(fc.fc_core.REDACTED, (proj / "results" / "001.test.log").read_text())
        self.assertClean(self.results_text(proj), names=False)
        self.assertIn(fc.fc_core.REDACTED, prompts[1])
        self.assertClean(prompts[1], names=False)

    def test_model_payloads_are_scrubbed_and_the_auth_header_kept(self):
        sent = []
        def urlopen(req, timeout=None):
            sent.append(req)
            body = {"choices": [{"message": {"content": '{"summary": "x"}'}}], "usage": {}}
            return mock.MagicMock(__enter__=lambda s: io.StringIO(json.dumps(body)), __exit__=lambda *a: False)
        with mock.patch("urllib.request.urlopen", urlopen):
            fc.fc_models.fast_json({"TEXT_MODEL_API_KEY": DOTENV}, f"system {KEY}", f"user {TYPESAFE}")
            fc.fc_models.jev_ask({"TYPESAFE_API_KEY": TYPESAFE}, {}, {"evidence": f"saw {OTHER}"}, {"q": {"instructions": KEY}}, "t")
        self.assertEqual([r.get_header("Authorization") for r in sent], [f"Bearer {DOTENV}", f"Bearer {TYPESAFE}"])
        for r in sent:
            self.assertClean(r.data.decode(), names=False)
            self.assertIn(fc.fc_core.REDACTED, r.data.decode())
        seen = []
        with mock.patch.object(fc.fc_models, "pi_turn", lambda cwd, model, prompt, session, timeout: seen.append(prompt) or ("s", "", 0, {})):
            fc.fc_implement.implementer(str(self.root), "pi:x/y", f"fix this: {KEY}")
        self.assertEqual(seen, [f"fix this: {fc.fc_core.REDACTED}"])

    def test_results_files_and_the_cli_output_are_scrubbed_but_the_config_keeps_its_keys(self):
        proj = self.root / "proj"
        (proj / "results").mkdir(parents=True)
        fc.fc_core.atomic_write(proj / "results" / "001.json", json.dumps({"log": [{"test_output": KEY}]}))
        fc.fc_change.write_change(proj, {"id": "C1", "results": {"001": {"log": [{"test_output": TYPESAFE}]}}})
        fc.fc_change.reflect(proj, "task:001", f"task 001 failed: {OTHER}")
        self.assertClean(self.results_text(proj), names=False)
        self.assertIn(fc.fc_core.REDACTED, (proj / "results" / "changes" / "C1.json").read_text())
        out = io.StringIO()
        fc.fc_core.Scrubbed(out).write(f"error {DOTENV}\n")
        self.assertEqual(out.getvalue(), f"error {fc.fc_core.REDACTED}\n")
        fc.fc_config.write_config(fc.fc_config.read_config())
        self.assertIn(KEY, fc.fc_config.CONFIG_PATH.read_text())


if __name__ == "__main__":
    unittest.main()
