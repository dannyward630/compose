import importlib.machinery, importlib.util, io, json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path
from unittest import mock
import sys, time
os.environ["FAST_CODING_NO_TREEHOUSE"] = "1"  # these cover the plain-worktree path; test_treehouse covers the pool
os.environ["FAST_CODING_E2E_HEADLESS"] = "1"  # testing the tool itself never opens a browser window; real projects keep theirs

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast_coding.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
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
        with mock.patch.object(fc.fc_implement, "implementer", impl), mock.patch.object(fc.fc_implement, "graft_pack", return_value=""), \
                mock.patch.object(fc.fc_config, "DEFAULT_MODEL", PRIMARY), mock.patch.object(fc.fc_config, "FALLBACK_MODEL", BACKUP), \
                mock.patch.dict(os.environ, {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}):
            return fc.fc_implement.run_task(repo, proj, task, 3, reset_files=reset_files), calls

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
        with mock.patch.object(fc.fc_implement, "implementer", impl), mock.patch.object(fc.fc_implement, "graft_pack", return_value=""), \
                mock.patch.dict(os.environ, {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}):
            fc.fc_implement.run_task(repo, proj, task, 3)
        self.assertGreaterEqual(limits[0], fc.fc_models.TURN_TIMEOUT + 300)

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
        with mock.patch.object(fc.fc_config, "FALLBACK_MODEL", BACKUP):
            self.assertIsNone(fc.fc_models.fallback_for(BACKUP))
            self.assertIsNone(fc.fc_models.fallback_for("claude"))

    def test_glm_is_the_default_with_no_fallback(self):
        self.assertIn("glm-5.3-flash@preset/glm-5-3-flash-fast", fc.fc_config.DEFAULT_MODEL)
        self.assertIsNone(fc.fc_models.fallback_for(fc.fc_config.DEFAULT_MODEL))


class Preflight(unittest.TestCase):
    def test_bad_model_stops_before_anything_runs(self):
        def impl(cwd, model, prompt, session=None, task=None, timeout=None):
            if model == BACKUP:
                raise RuntimeError("400 z-ai/glm-5-3-flash is not a valid model ID")
            if model == "pi:r/limited":
                raise fc.fc_models.RateLimited({"cost": 0.0})
            return "s", "OK", 0, {"cost": 0.0}
        with mock.patch.object(fc.fc_implement, "implementer", impl):
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
        fc.fc_worktree.ready_checkout(repo, wt)
        fc.fc_worktree.ready_checkout(repo, wt)  # idempotent: a re-run neither fails nor duplicates exclude lines
        self.assertTrue((wt / "client" / "node_modules").is_symlink())
        self.assertTrue((wt / "client" / "node_modules" / "jest").is_dir())
        if subprocess.run(["which", "graft"], capture_output=True).returncode == 0:
            subprocess.run(["graft", "build", "--no-gitignore", "--no-ignore", str(wt)], cwd=wt, capture_output=True)
        self.assertEqual(git(wt, "status", "--porcelain").stdout, "")
        exclude = (wt / ".git" / "info" / "exclude").read_text().splitlines()
        self.assertEqual(exclude.count("/client/node_modules"), 1)

    def test_install_command_replaces_borrowing(self):
        root = Path(tempfile.mkdtemp())
        repo, wt = root / "repo", root / "wt"
        (repo / "node_modules" / "old").mkdir(parents=True)
        (repo / ".gitignore").write_text("node_modules/\n")
        git = lambda cwd, *a: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True)
        git(repo, "init", "-q")
        git(repo, "add", "-A")
        git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        git(root, "clone", "-q", "--shared", str(repo), str(wt))
        (wt / "node_modules").symlink_to(repo / "node_modules")  # a link left by an earlier borrow
        fc.fc_worktree.ready_checkout(repo, wt, install="mkdir -p node_modules/fresh")
        self.assertFalse((wt / "node_modules").is_symlink())  # the install lives in the checkout, so build output cannot depend on the project worktree's path
        self.assertTrue((wt / "node_modules" / "fresh").is_dir())
        self.assertFalse((repo / "node_modules" / "fresh").exists())
        self.assertEqual(git(wt, "status", "--porcelain").stdout, "")
        (wt / "bun.lock").write_text("new\n")  # a lockfile change is what makes the install run again
        git(wt, "add", "-A")
        git(wt, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "dep")
        with self.assertRaises(RuntimeError):
            fc.fc_worktree.ready_checkout(repo, wt, install="exit 3")

    def test_install_reruns_only_when_the_lockfile_changes(self):
        root = Path(tempfile.mkdtemp())
        repo, wt = root / "repo", root / "wt"
        repo.mkdir()
        (repo / ".gitignore").write_text("node_modules/\n")
        (repo / "bun.lock").write_text("one\n")
        git = lambda cwd, *a: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True)
        git(repo, "init", "-q")
        git(repo, "add", "-A")
        git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        git(root, "clone", "-q", "--shared", str(repo), str(wt))
        install = "mkdir -p node_modules && cat bun.lock >> node_modules/seen"
        seen = lambda: (wt / "node_modules" / "seen").read_text()
        fc.fc_worktree.ready_checkout(repo, wt, install=install)
        fc.fc_worktree.ready_checkout(repo, wt, install=install)
        self.assertEqual(seen(), "one\n")  # the same lockfile: no second install
        (wt / "bun.lock").write_text("two\n")
        git(wt, "add", "-A")
        git(wt, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "dep")
        fc.fc_worktree.ready_checkout(repo, wt, install=install)
        self.assertEqual(seen(), "one\ntwo\n")  # a changed lockfile installs again

    def test_lockfile_task_installs_on_its_own_and_hands_it_over(self):
        root = Path(tempfile.mkdtemp())
        repo, wt = root / "repo", root / "wt"
        (repo / "node_modules" / "old").mkdir(parents=True)
        (repo / ".gitignore").write_text("node_modules/\n")
        (repo / "a.js").write_text("x\n")
        git = lambda cwd, *a: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True)
        git(repo, "init", "-q")
        git(repo, "add", "-A")
        git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        git(root, "clone", "-q", "--shared", str(repo), str(wt))
        for f in (["bun.lock"], ["a.js", "package-lock.json"]):
            self.assertTrue(fc.fc_worktree.names_lockfile({"files": f}))
        self.assertFalse(fc.fc_worktree.names_lockfile({"files": ["a.js"]}))
        fc.fc_worktree.ready_checkout(repo, wt, borrow=False)
        self.assertFalse((wt / "node_modules").exists())
        (wt / "node_modules" / "new").mkdir(parents=True)  # the task's own install
        real, seen = shutil.rmtree, []
        def rmtree(path, *a, **k):
            real(path, *a, **k)
            seen.append((repo / "node_modules").exists())
        with mock.patch.object(shutil, "rmtree", rmtree):
            fc.fc_worktree.adopt_installs(repo, wt)
        self.assertTrue(seen and all(seen), "the install dir was missing during the swap")
        self.assertTrue((repo / "node_modules" / "new").is_dir())
        self.assertFalse((repo / "node_modules" / "old").exists())
        self.assertFalse((repo / "node_modules").is_symlink())


class FixScope(unittest.TestCase):
    def verify(self, writes, reply="", cfg=None):
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
            self.prompt = prompt
            for f, text in writes.items():
                (Path(cwd) / f).write_text(text)
            return "s", reply, 1, {"cost": 0.0}
        stages = iter([(False, {}, "finding"), (True, {}, "")])
        with mock.patch.object(fc.fc_implement, "implementer", impl), mock.patch.object(fc.fc_implement, "graft_pack", return_value=""), \
                mock.patch.object(fc.fc_verify, "run_stages", lambda *a: next(stages)), mock.patch.object(fc.fc_verify, "review_inputs", return_value=(0, 0, 0, [])), \
                mock.patch.object(fc.fc_change, "reflect", return_value=(Path("/p/reflect.json"), {})):  # a failed verify screens: never call Jev
            with self.assertRaises(SystemExit) as cm:
                fc.fc_verify.verify_rounds(repo, proj, {"review_base": "main", **(cfg or {})}, type("A", (), {"fix": 2})(), [], time.time())
        return cm.exception.code, repo, json.loads((proj / "results" / "verify.json").read_text())

    def test_fix_inside_the_stack_commits_and_passes(self):
        code, repo, res = self.verify({"a.go": "fixed\n"})
        self.assertEqual((code, res["passed"]), (0, True))
        self.assertEqual((repo / "a.go").read_text(), "fixed\n")
        log = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=repo, capture_output=True, text=True).stdout
        self.assertEqual(log.strip(), "Fix a.go")  # describes the change, never the process

    def test_fix_commit_uses_the_fixers_one_line_description(self):
        _, repo, _ = self.verify({"a.go": "fixed\n"}, reply='"Match the autofill panel file name"\nI also changed...')
        self.assertEqual(subprocess.run(["git", "log", "-1", "--format=%s"], cwd=repo, capture_output=True, text=True).stdout.strip(),
                         "Match the autofill panel file name")
        _, repo, _ = self.verify({"a.go": "fixed\n"}, reply="Fix verification findings")  # a process message is not used
        self.assertEqual(subprocess.run(["git", "log", "-1", "--format=%s"], cwd=repo, capture_output=True, text=True).stdout.strip(), "Fix a.go")

    def test_fixer_is_told_the_design_context_and_the_simplicity_bar(self):
        self.verify({"a.go": "fixed\n"}, cfg={"review_context": "Paths are POSIX only by design."})
        self.assertIn("Paths are POSIX only by design.", self.prompt)
        self.assertIn("no hardening", self.prompt)

    def test_review_confirms_only_defects_against_the_requirements(self):
        systems = []
        def fj(env, system, user, max_tokens=4000):
            systems.append((system, user))
            return {"issues": [{"file": "a.mjs", "severity": "medium", "note": "handle Windows paths"}]} if "strict code reviewer" in system \
                else {"confirmed": True, "evidence": "e"}
        with mock.patch.object(fc.fc_models, "fast_json", fj), mock.patch.object(fc.fc_core, "load_env", return_value={}):
            fc.fc_verify.llm_review({"perspectives": ["correctness"]}, "diff", "THE PLAN", "", True)
        review, confirm = systems
        self.assertIn("hardening", review[0])
        self.assertIn("hardening", confirm[0])
        self.assertIn("THE PLAN", confirm[1])

    def test_review_drops_a_confirmation_whose_quote_is_not_in_the_code(self):
        def review(evidence, cfg=None):
            fj = lambda env, system, user, max_tokens=4000: {"issues": [{"file": "a.ts", "severity": "high", "note": "n"}]} \
                if "strict code reviewer" in system else {"confirmed": True, "evidence": evidence}
            with mock.patch.object(fc.fc_models, "fast_json", fj), mock.patch.object(fc.fc_core, "load_env", return_value={}):
                return fc.fc_verify.llm_review({"perspectives": ["spec"], **(cfg or {})}, "build: {\n  fileName: 'x.js',\n}", "plan", "", True)
        self.assertEqual(len(review("fileName:   'x.js',")["confirmed"]), 1)
        rv = review("lib output defaults to main.js")
        self.assertEqual((rv["confirmed"], rv["pass"]), ([], True))

    def test_lockfile_or_new_file_rejects_the_round_and_fails(self):
        code, repo, res = self.verify({"a.go": "fixed\n", "yarn.lock": "rewritten\n", "package-lock.json": "{}\n"})
        self.assertEqual((code, res["passed"]), (1, False))
        self.assertEqual(sorted(res["rejected_fixes"][0]["files"]), ["package-lock.json", "yarn.lock"])
        self.assertEqual((repo / "a.go").read_text(), "b\n")  # the whole round is reverted
        self.assertEqual((repo / "yarn.lock").read_text(), "lock\n")
        self.assertFalse((repo / "package-lock.json").exists())

    def test_no_stack_diff_still_refuses_lockfiles(self):
        self.assertEqual(fc.fc_verify.fix_strays(["src/x.go", "client/yarn.lock"], set()), ["client/yarn.lock"])
        self.assertEqual(fc.fc_verify.fix_strays(["src/x.go", "client/yarn.lock"], set(), {"client/yarn.lock"}), [])  # a task names it in files:
        self.assertEqual(fc.fc_verify.fix_strays(["a.go", "yarn.lock"], {"a.go"}, {"yarn.lock"}), [])


def ws(name=None, target=None, stdin=""):
    with mock.patch.object(sys, "stdin", io.StringIO(stdin)), mock.patch("builtins.print"):
        fc.fc_config.cmd_workspace(type("A", (), {"name": name, "target": target}))


class Workspaces(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "config.json"
        self.path.write_text('{"workspace": "work", "models": {"implementer": "pi:a/b", "fallback": "pi:g/h", "fix": "pi:f/x"},'
                             ' "workspaces": {"work": {"openrouter_api_key": "sk-work"},'
                             ' "personal": {"openrouter_api_key": "sk-home", "models": {"fallback": null}, "env": {"X_FC": "1"}}}}')
        self.patches = [mock.patch.object(fc.fc_config, "CONFIG_PATH", self.path), mock.patch.dict(os.environ, {}),
                        mock.patch.object(fc.fc_config, "DEFAULT_MODEL", fc.fc_config.DEFAULT_MODEL), mock.patch.object(fc.fc_config, "FALLBACK_MODEL", fc.fc_config.FALLBACK_MODEL),
                        mock.patch.object(fc.fc_config, "OPENROUTER_KEY", None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def test_active_workspace_sets_key_and_models(self):
        self.assertEqual(fc.fc_config.apply_config(), "work")
        self.assertEqual((fc.fc_config.OPENROUTER_KEY, os.environ["OPENROUTER_API_KEY"], os.environ["TEXT_MODEL_API_KEY"]), ("sk-work",) * 3)
        self.assertEqual(fc.fc_config.DEFAULT_MODEL, "pi:a/b")
        self.assertEqual(os.environ["FAST_CODING_FIX_MODEL"], "pi:f/x")
        self.assertIn("sk-work", os.environ["OPENCODE_CONFIG_CONTENT"])
        self.assertEqual(fc.fc_models.fallback_for("pi:a/b"), "pi:g/h")

    def test_switch_overrides_top_level(self):
        ws("personal")
        self.assertEqual(oct(self.path.stat().st_mode & 0o777), "0o600")
        self.assertEqual(fc.fc_config.apply_config(), "personal")
        self.assertEqual(fc.fc_config.OPENROUTER_KEY, "sk-home")
        self.assertEqual(os.environ["X_FC"], "1")
        self.assertEqual(fc.fc_config.DEFAULT_MODEL, "pi:a/b")  # inherited from the top level
        self.assertIsNone(fc.fc_models.fallback_for("pi:a/b"))  # personal turned the fallback off

    def test_unknown_workspace_refused(self):
        with self.assertRaises(SystemExit):
            ws("nope")

    def test_pi_gets_the_workspace_key(self):
        fc.fc_config.apply_config()
        run = mock.Mock(return_value=mock.Mock(stdout='{"type":"tool_execution_start"}', stderr="", returncode=0))
        with mock.patch.object(subprocess, "run", run):
            fc.fc_models.pi_turn(tempfile.mkdtemp(), "x/y", "hi")
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[cmd.index("--api-key") + 1], "sk-work")

    def test_pi_turn_reports_the_providers_error_not_stderr(self):
        err = json.dumps({"message": 'Preset "glm-5-3-flash-fast" not found for this user.', "code": 404,
                          "metadata": {"presetErrorCode": "preset_not_found", "presetSlug": "glm-5-3-flash-fast"}})
        end = json.dumps({"type": "message_end", "message": {"role": "assistant", "content": [], "stopReason": "error", "errorMessage": f"404: {err}"}})
        run = mock.Mock(return_value=mock.Mock(stdout=end + "\n", stderr="Warning: No project session found with id 'x'; creating a new session\n", returncode=0))
        with mock.patch.object(subprocess, "run", run), mock.patch.object(fc.fc_config, "WORKSPACE", "work"):
            with self.assertRaises(RuntimeError) as cm:
                fc.fc_models.pi_turn(tempfile.mkdtemp(), "x/y", "hi")
        self.assertIn("404", str(cm.exception))
        self.assertIn("preset 'glm-5-3-flash-fast' not found in workspace 'work'", str(cm.exception))
        self.assertNotIn("No project session", str(cm.exception))

    def test_add_key_switch_remove(self):
        ws("add", "client-x", stdin="sk-client\n")
        ws("client-x")
        self.assertEqual(fc.fc_config.apply_config(), "client-x")
        self.assertEqual(fc.fc_config.OPENROUTER_KEY, "sk-client")
        ws("key", "client-x", stdin="sk-rotated")
        fc.fc_config.apply_config()
        self.assertEqual(fc.fc_config.OPENROUTER_KEY, "sk-rotated")
        ws("remove", "client-x")  # removing the active one falls back to default
        self.assertNotIn("client-x", fc.fc_config.read_config()["workspaces"])
        self.assertEqual(fc.fc_config.settings(fc.fc_config.read_config())[0], "default")

    def test_keyless_add_fails_loudly_on_use(self):
        ws("add", "later")
        ws("later")
        with self.assertRaises(SystemExit):
            fc.fc_config.apply_config()

    def test_default_always_exists(self):
        ws("default")
        fc.fc_config.OPENROUTER_KEY = None
        self.assertEqual(fc.fc_config.apply_config(), "default")
        self.assertIsNone(fc.fc_config.OPENROUTER_KEY)  # no top-level key: harnesses keep their own auth stores
        self.assertEqual(fc.fc_config.DEFAULT_MODEL, "pi:a/b")
        for bad in (("add", "default"), ("add", "work"), ("remove", "default"), ("add", "a b"), ("add", None)):
            with self.assertRaises(SystemExit):
                ws(*bad)


class RetryMessage(unittest.TestCase):
    def run_three(self, summary="", backup=None):
        """Attempts write a, b, yes; the test prints 5,000 copies and fails until yes. Returns (result, prompts, logs seen, log path)."""
        root = Path(tempfile.mkdtemp())
        repo, proj = root / "repo", root / "proj"
        repo.mkdir(); proj.mkdir()
        git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        (repo / "a.txt").write_text("no\n")
        git("add", "-A"); git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        test = "python3 -c \"s=open('a.txt').read().strip(); print(s*5000); raise SystemExit(s!='yes')\""
        task = {"id": "001", "title": "answer", "files": ["a.txt"], "protected": [], "test": test,
                "model": PRIMARY, "after": "", "linear": "ENG-1", "body": "## Goal\nWrite yes."}
        log = proj / "results" / "001.test.log"
        prompts, seen = [], []
        def impl(cwd, model, prompt, session=None, task=None, timeout=None):
            prompts.append(prompt)
            seen.append(log.read_text() if log.exists() else None)
            (Path(cwd) / "a.txt").write_text(["a", "b", "yes"][len(prompts) - 1] + "\n")
            return "s", "", 1, {"tokens_in": 1, "tokens_out": 1, "cost": 0.0}
        with mock.patch.object(fc.fc_implement, "implementer", impl), mock.patch.object(fc.fc_implement, "graft_pack", return_value=""), \
                mock.patch.object(fc.fc_implement, "condense_failure", return_value=summary), \
                mock.patch.object(fc.fc_config, "DEFAULT_MODEL", PRIMARY), mock.patch.object(fc.fc_config, "FALLBACK_MODEL", backup), \
                mock.patch.dict(os.environ, {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}):
            return fc.fc_implement.run_task(repo, proj, task, 3), prompts, seen, log

    def test_retry_sends_a_short_tail_and_the_full_log_path(self):
        r, prompts, seen, log = self.run_three(summary="case_x expected yes, got a")
        self.assertEqual(r["status"], "passed")
        self.assertEqual(seen[1:], ["a" * 5000 + "\n", "b" * 5000 + "\n"])  # whole output, overwritten by the next failed attempt
        for p, ch in ((prompts[1], "a"), (prompts[2], "b")):
            self.assertIn("What failed:\ncase_x expected yes, got a\n", p)
            tail = p.split("Output (tail):\n", 1)[1].split("Full output: ", 1)[0]
            self.assertTrue(900 <= tail.count(ch) <= 1000, tail.count(ch))
            path = p.split("Full output: ", 1)[1].split(";", 1)[0]
            self.assertTrue(Path(path).is_absolute(), path)
            self.assertEqual(Path(path).resolve(), log.resolve())
        self.assertEqual([len(e["test_output"]) for e in r["log"][:2]], [3000, 3000])

    def test_no_summary_leaves_out_what_failed(self):
        _, prompts, _, _ = self.run_three(summary="")
        self.assertNotIn("What failed:", prompts[1])
        self.assertIn("Full output: ", prompts[1])

    def test_fallback_starts_from_the_task_and_ends_with_the_same_problems(self):
        r, prompts, _, _ = self.run_three(backup=BACKUP)
        self.assertEqual(r["log"][0]["fallback"]["to"], BACKUP)
        self.assertTrue(prompts[1].startswith(prompts[0]))
        problems = prompts[1][prompts[1].index("The test still fails."):]
        self.assertIn("Full output: ", problems)
        self.assertLess(len(problems), 2000)  # the short tail, not the 3,000-character one
