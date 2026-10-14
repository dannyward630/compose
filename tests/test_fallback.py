import importlib.machinery, importlib.util, io, json, os, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock
os.environ["FAST_CODING_NO_TREEHOUSE"] = "1"  # these cover the plain-worktree path; test_treehouse covers the pool
os.environ["FAST_CODING_E2E_HEADLESS"] = "1"  # testing the tool itself never opens a browser window; real projects keep theirs

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)


PRIMARY, BACKUP = "pi:p/primary", "pi:b/backup"


class Fallback(unittest.TestCase):
    def run_once(self, first, reset_files=False):
        """The primary model behaves as `first` ("error" or "miss"); the fallback writes the answer. Returns (result, models called)."""
        root = Path(tempfile.mkdtemp())
        repo, proj = root / "repo", root / "proj"
        repo.mkdir(); proj.mkdir()
        git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        (repo / "a.txt").write_text("no\n")
        git("add", "-A"); git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        task = {"id": "001", "title": "answer", "files": ["a.txt"], "protected": [], "test": "grep -q yes a.txt",
                "model": PRIMARY, "after": "", "linear": "ENG-1", "body": "## Goal\nWrite yes."}
        calls = []
        def impl(cwd, model, prompt, session=None, task=None, timeout=None):
            calls.append(model)
            if model == PRIMARY and first == "error":
                raise RuntimeError("provider refused the request")
            (Path(cwd) / "a.txt").write_text("yes\n" if model == BACKUP else "nope\n")
            return "s", "", 1, {"tokens_in": 1, "tokens_out": 1, "cost": 0.0}
        with mock.patch.object(fc, "implementer", impl), mock.patch.object(fc, "graft_pack", return_value=""), \
                mock.patch.object(fc, "DEFAULT_MODEL", PRIMARY), mock.patch.object(fc, "FALLBACK_MODEL", BACKUP), \
                mock.patch.dict(os.environ, {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}):
            return fc.run_task(repo, proj, task, 3, reset_files=reset_files), calls

    def test_turn_limit_leaves_room_for_the_tasks_test(self):
        root = Path(tempfile.mkdtemp())
        repo, proj = root / "repo", root / "proj"
        repo.mkdir(); proj.mkdir()
        git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        (repo / "a.txt").write_text("no\n")
        git("add", "-A"); git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        task = {"id": "001", "title": "answer", "files": ["a.txt"], "protected": [], "test": "grep -q yes a.txt", "test_timeout": 300,
                "model": PRIMARY, "after": "", "linear": "ENG-1", "body": "## Goal\nWrite yes."}
        limits = []
        def impl(cwd, model, prompt, session=None, task=None, timeout=None):
            limits.append(timeout)
            (Path(cwd) / "a.txt").write_text("yes\n")
            return "s", "", 1, {"tokens_in": 1, "tokens_out": 1, "cost": 0.0}
        with mock.patch.object(fc, "implementer", impl), mock.patch.object(fc, "graft_pack", return_value=""), \
                mock.patch.dict(os.environ, {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}):
            fc.run_task(repo, proj, task, 3)
        self.assertGreaterEqual(limits[0], fc.TURN_TIMEOUT + 300)

    def test_error_falls_back(self):
        r, calls = self.run_once("error")
        self.assertEqual(r["status"], "passed")
        self.assertEqual(calls, [PRIMARY, BACKUP])
        self.assertEqual(r["model"], BACKUP)
        self.assertEqual(r["attempts"], 2)
        self.assertEqual(r["log"][0]["fallback"]["why"], "errored")

    def test_miss_falls_back_with_feedback(self):
        r, calls = self.run_once("miss")
        self.assertEqual(r["status"], "passed")
        self.assertEqual(calls, [PRIMARY, BACKUP])

    def test_fallback_has_no_fallback(self):
        with mock.patch.object(fc, "FALLBACK_MODEL", BACKUP):
            self.assertIsNone(fc.fallback_for(BACKUP))
            self.assertIsNone(fc.fallback_for("claude"))

    def test_glm_is_the_default_with_no_fallback(self):
        self.assertIn("glm-5.3-flash@preset/glm-5-3-flash-fast", fc.DEFAULT_MODEL)
        self.assertIsNone(fc.fallback_for(fc.DEFAULT_MODEL))


class Preflight(unittest.TestCase):
    def test_bad_model_stops_before_anything_runs(self):
        def impl(cwd, model, prompt, session=None, task=None, timeout=None):
            if model == BACKUP:
                raise RuntimeError("400 z-ai/glm-5-3-flash is not a valid model ID")
            if model == "pi:r/limited":
                raise fc.RateLimited({"cost": 0.0})
            return "s", "OK", 0, {"cost": 0.0}
        with mock.patch.object(fc, "implementer", impl):
            fc.preflight({PRIMARY, "pi:r/limited", "claude", None})  # a rate limit proves the model resolved; claude is not probed
            with self.assertRaises(SystemExit) as cm:
                fc.preflight({PRIMARY, BACKUP})
        self.assertIn(BACKUP, str(cm.exception))
        self.assertIn("not a valid model ID", str(cm.exception))


class ReadyCheckout(unittest.TestCase):
    def test_clone_borrows_installs_and_stays_clean(self):
        root = Path(tempfile.mkdtemp())
        repo, wt = root / "repo", root / "wt"
        (repo / "client" / "node_modules" / "jest").mkdir(parents=True)
        (repo / "client" / "app.js").write_text("x\n")
        (repo / "a.py").write_text("def f():\n    return 1\n")
        (repo / ".gitignore").write_text("node_modules/\n")
        git = lambda cwd, *a: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True)
        git(repo, "init", "-q")
        git(repo, "add", "-A")
        git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        git(root, "clone", "-q", "--shared", str(repo), str(wt))
        fc.ready_checkout(repo, wt)
        fc.ready_checkout(repo, wt)  # idempotent: a re-run neither fails nor duplicates exclude lines
        self.assertTrue((wt / "client" / "node_modules").is_symlink())
        self.assertTrue((wt / "client" / "node_modules" / "jest").is_dir())
        if subprocess.run(["which", "graft"], capture_output=True).returncode == 0:
            subprocess.run(["graft", "build", "--no-gitignore", "--no-ignore", str(wt)], cwd=wt, capture_output=True)
        self.assertEqual(git(wt, "status", "--porcelain").stdout, "")
        exclude = (wt / ".git" / "info" / "exclude").read_text().splitlines()
        self.assertEqual(exclude.count("/client/node_modules"), 1)


class FixScope(unittest.TestCase):
    def verify(self, writes):
        """A stack with one layer changing a.go; the first stage run fails, the fixer writes `writes`, later runs pass."""
        root = Path(tempfile.mkdtemp())
        repo, proj = root / "repo", root / "proj"
        repo.mkdir(); proj.mkdir()
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=repo, check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        (repo / "a.go").write_text("a\n"); (repo / "yarn.lock").write_text("lock\n")
        git("add", "-A"); git("commit", "-qm", "init")
        git("checkout", "-qb", "layer")
        (repo / "a.go").write_text("b\n")
        git("commit", "-qam", "layer")
        def impl(cwd, model, prompt, session=None, task=None, timeout=None):
            for f, text in writes.items():
                (Path(cwd) / f).write_text(text)
            return "s", "", 1, {"cost": 0.0}
        stages = iter([(False, {}, "finding"), (True, {}, "")])
        with mock.patch.object(fc, "implementer", impl), mock.patch.object(fc, "graft_pack", return_value=""), \
                mock.patch.object(fc, "run_stages", lambda *a: next(stages)), mock.patch.object(fc, "review_inputs", return_value=(0, 0, 0, [])), \
                mock.patch.object(fc, "reflect", return_value=(Path("/p/reflect.json"), {})):  # a failed verify screens: never call Jev
            with self.assertRaises(SystemExit) as cm:
                fc.verify_rounds(repo, proj, {"review_base": "main"}, type("A", (), {"fix": 2})(), [], fc.time.time())
        return cm.exception.code, repo, json.loads((proj / "results" / "verify.json").read_text())

    def test_fix_inside_the_stack_commits_and_passes(self):
        code, repo, res = self.verify({"a.go": "fixed\n"})
        self.assertEqual((code, res["passed"]), (0, True))
        self.assertEqual((repo / "a.go").read_text(), "fixed\n")
        log = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=repo, capture_output=True, text=True).stdout
        self.assertEqual(log.strip(), "Fix verification findings")  # plain, never the tool's name

    def test_lockfile_or_new_file_rejects_the_round_and_fails(self):
        code, repo, res = self.verify({"a.go": "fixed\n", "yarn.lock": "rewritten\n", "package-lock.json": "{}\n"})
        self.assertEqual((code, res["passed"]), (1, False))
        self.assertEqual(sorted(res["rejected_fixes"][0]["files"]), ["package-lock.json", "yarn.lock"])
        self.assertEqual((repo / "a.go").read_text(), "b\n")  # the whole round is reverted
        self.assertEqual((repo / "yarn.lock").read_text(), "lock\n")
        self.assertFalse((repo / "package-lock.json").exists())

    def test_no_stack_diff_still_refuses_lockfiles(self):
        self.assertEqual(fc.fix_strays(["src/x.go", "client/yarn.lock"], set()), ["client/yarn.lock"])


def ws(name=None, target=None, stdin=""):
    with mock.patch.object(fc.sys, "stdin", io.StringIO(stdin)), mock.patch("builtins.print"):
        fc.cmd_workspace(type("A", (), {"name": name, "target": target}))


class Workspaces(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "config.json"
        self.path.write_text('{"workspace": "work", "models": {"implementer": "pi:a/b", "fallback": "pi:g/h", "fix": "pi:f/x"},'
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
        self.assertEqual(fc.fallback_for("pi:a/b"), "pi:g/h")

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

    def test_pi_turn_reports_the_providers_error_not_stderr(self):
        err = json.dumps({"message": 'Preset "glm-5-3-flash-fast" not found for this user.', "code": 404,
                          "metadata": {"presetErrorCode": "preset_not_found", "presetSlug": "glm-5-3-flash-fast"}})
        end = json.dumps({"type": "message_end", "message": {"role": "assistant", "content": [], "stopReason": "error", "errorMessage": f"404: {err}"}})
        run = mock.Mock(return_value=mock.Mock(stdout=end + "\n", stderr="Warning: No project session found with id 'x'; creating a new session\n", returncode=0))
        with mock.patch.object(fc.subprocess, "run", run), mock.patch.object(fc, "WORKSPACE", "work"):
            with self.assertRaises(RuntimeError) as cm:
                fc.pi_turn(tempfile.mkdtemp(), "x/y", "hi")
        self.assertIn("404", str(cm.exception))
        self.assertIn("preset 'glm-5-3-flash-fast' not found in workspace 'work'", str(cm.exception))
        self.assertNotIn("No project session", str(cm.exception))

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
