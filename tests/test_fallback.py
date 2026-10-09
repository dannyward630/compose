import importlib.machinery, importlib.util, io, os, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)


class Fallback(unittest.TestCase):
    def run_once(self, first, reset_files=False):
        """gpt-oss behaves as `first` ("error" or "miss"); GLM writes the answer. Returns (result, models called)."""
        root = Path(tempfile.mkdtemp())
        repo, proj = root / "repo", root / "proj"
        repo.mkdir(); proj.mkdir()
        git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        (repo / "a.txt").write_text("no\n")
        git("add", "-A"); git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        task = proj / "001-answer.md"
        task.write_text("---\nid: 001\ntitle: answer\nfiles: a.txt\ntest: grep -q yes a.txt\n---\n## Goal\nWrite yes.\n")
        calls = []
        def impl(cwd, model, prompt, session=None, task=None):
            calls.append(model)
            if "gpt-oss" in model and first == "error":
                raise RuntimeError("provider refused the request")
            (Path(cwd) / "a.txt").write_text("yes\n" if "glm" in model else "nope\n")
            return "s", "", 1, {"tokens_in": 1, "tokens_out": 1, "cost": 0.0}
        with mock.patch.object(fc, "implementer", impl), mock.patch.object(fc, "graft_pack", return_value=""), \
                mock.patch.dict(os.environ, {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}):
            return fc.run_task(repo, proj, task, 3, reset_files=reset_files), calls

    def test_error_falls_back(self):
        r, calls = self.run_once("error")
        self.assertEqual(r["status"], "passed")
        self.assertEqual(calls, [fc.DEFAULT_MODEL, fc.FALLBACK_MODEL])
        self.assertEqual(r["model"], fc.FALLBACK_MODEL)
        self.assertEqual(r["attempts"], 2)
        self.assertEqual(r["log"][0]["fallback"]["why"], "errored")

    def test_miss_falls_back_with_feedback(self):
        r, calls = self.run_once("miss")
        self.assertEqual(r["status"], "passed")
        self.assertEqual(calls, [fc.DEFAULT_MODEL, fc.FALLBACK_MODEL])

    def test_glm_has_no_fallback(self):
        self.assertIsNone(fc.fallback_for(fc.FALLBACK_MODEL))
        self.assertIsNone(fc.fallback_for("claude"))


def ws(name=None, target=None, stdin=""):
    with mock.patch.object(fc.sys, "stdin", io.StringIO(stdin)), mock.patch("builtins.print"):
        fc.cmd_workspace(type("A", (), {"name": name, "target": target}))


class Workspaces(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "config.json"
        self.path.write_text('{"workspace": "work", "models": {"implementer": "pi:a/b", "fix": "pi:f/x"},'
                             ' "workspaces": {"work": {"openrouter_api_key": "sk-work"},'
                             ' "personal": {"openrouter_api_key": "sk-home", "models": {"fallback": null}, "env": {"X_FC": "1"}}}}')
        self.patches = [mock.patch.object(fc, "CONFIG_PATH", self.path), mock.patch.dict(os.environ, {}),
                        mock.patch.object(fc, "DEFAULT_MODEL", fc.DEFAULT_MODEL), mock.patch.object(fc, "FALLBACK_MODEL", fc.FALLBACK_MODEL),
                        mock.patch.object(fc, "OPENROUTER_KEY", None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def test_active_workspace_sets_key_and_models(self):
        self.assertEqual(fc.apply_config(), "work")
        self.assertEqual((fc.OPENROUTER_KEY, os.environ["OPENROUTER_API_KEY"], os.environ["TEXT_MODEL_API_KEY"]), ("sk-work",) * 3)
        self.assertEqual(fc.DEFAULT_MODEL, "pi:a/b")
        self.assertEqual(os.environ["FAST_CODING_FIX_MODEL"], "pi:f/x")
        self.assertIn("sk-work", os.environ["OPENCODE_CONFIG_CONTENT"])
        self.assertEqual(fc.fallback_for("pi:a/b"), fc.FALLBACK_MODEL)

    def test_switch_overrides_top_level(self):
        ws("personal")
        self.assertEqual(oct(self.path.stat().st_mode & 0o777), "0o600")
        self.assertEqual(fc.apply_config(), "personal")
        self.assertEqual(fc.OPENROUTER_KEY, "sk-home")
        self.assertEqual(os.environ["X_FC"], "1")
        self.assertEqual(fc.DEFAULT_MODEL, "pi:a/b")  # inherited from the top level
        self.assertIsNone(fc.fallback_for("pi:a/b"))  # personal turned the fallback off

    def test_unknown_workspace_refused(self):
        with self.assertRaises(SystemExit):
            ws("nope")

    def test_pi_gets_the_workspace_key(self):
        fc.apply_config()
        run = mock.Mock(return_value=mock.Mock(stdout='{"type":"tool_execution_start"}', stderr="", returncode=0))
        with mock.patch.object(fc.subprocess, "run", run):
            fc.pi_turn(tempfile.mkdtemp(), "x/y", "hi")
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[cmd.index("--api-key") + 1], "sk-work")

    def test_add_key_switch_remove(self):
        ws("add", "client-x", stdin="sk-client\n")
        ws("client-x")
        self.assertEqual(fc.apply_config(), "client-x")
        self.assertEqual(fc.OPENROUTER_KEY, "sk-client")
        ws("key", "client-x", stdin="sk-rotated")
        fc.apply_config()
        self.assertEqual(fc.OPENROUTER_KEY, "sk-rotated")
        ws("remove", "client-x")  # removing the active one falls back to default
        self.assertNotIn("client-x", fc.read_config()["workspaces"])
        self.assertEqual(fc.settings(fc.read_config())[0], "default")

    def test_keyless_add_fails_loudly_on_use(self):
        ws("add", "later")
        ws("later")
        with self.assertRaises(SystemExit):
            fc.apply_config()

    def test_default_always_exists(self):
        ws("default")
        fc.OPENROUTER_KEY = None
        self.assertEqual(fc.apply_config(), "default")
        self.assertIsNone(fc.OPENROUTER_KEY)  # no top-level key: harnesses keep their own auth stores
        self.assertEqual(fc.DEFAULT_MODEL, "pi:a/b")
        for bad in (("add", "default"), ("add", "work"), ("remove", "default"), ("add", "a b"), ("add", None)):
            with self.assertRaises(SystemExit):
                ws(*bad)
