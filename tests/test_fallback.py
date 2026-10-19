import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, io, json, os, shutil, subprocess, tempfile, unittest
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock
import sys, time
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"  # these cover the plain-worktree path; test_treehouse covers the pool
os.environ["HERDR_ENV"] = ""
os.environ["COMPOSE_E2E_HEADLESS"] = "1"  # testing the tool itself never opens a browser window; real projects keep theirs

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)


PRIMARY, BACKUP = "pi:p/primary", "pi:b/backup"


class Fallback(unittest.TestCase):
    def run_once(self, first, reset_files=False, after=2, edit=None):
        """The primary model behaves as `first` ("error", "miss", or "rate"); the fallback writes the answer. Returns (result, models called);
        the prompts land in self.prompts."""
        root = Path(tempfile.mkdtemp())
        repo, proj = root / "repo", root / "proj"
        repo.mkdir(); proj.mkdir()
        git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        (repo / "a.txt").write_text("no\n")
        git("add", "-A"); git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        task = {"id": "001", "title": "answer", "files": ["a.txt"], "protected": [], "test": "grep -q yes a.txt",
                "model": PRIMARY, "after": "", "linear": "ENG-1", "body": "## Goal\nWrite yes."}
        calls, self.prompts = [], []
        def impl(cwd, model, prompt, session=None, task=None, timeout=None):
            calls.append(model); self.prompts.append(prompt)
            if model == PRIMARY and first == "error":
                raise RuntimeError("provider refused the request")
            if model == PRIMARY and first == "rate":
                if edit:  # the turn edits, then the provider cuts it short
                    (Path(cwd) / "a.txt").write_text(edit)
                raise fc.fc_models.RateLimited({"cost": 0.0})
            (Path(cwd) / "a.txt").write_text("yes\n" if model == BACKUP else "nope\n")
            return "s", "", 1, {"tokens_in": 1, "tokens_out": 1, "cost": 0.0}
        with mock.patch.object(fc.fc_implement, "implementer", impl), mock.patch.object(fc.fc_implement, "trail_pack", return_value=""), \
                mock.patch.object(fc.fc_config, "DEFAULT_MODEL", PRIMARY), mock.patch.object(fc.fc_config, "FALLBACK_MODEL", BACKUP), \
                mock.patch.object(fc.fc_config, "FALLBACK_AFTER", after), mock.patch.object(fc.fc_config, "TEST_READER", None), \
                mock.patch.dict(os.environ, {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}):
            return fc.fc_implement.run_task(repo, proj, task, 3, reset_files=reset_files), calls

    def test_turn_limit_has_no_room_for_a_test_run(self):
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
        with mock.patch.object(fc.fc_implement, "implementer", impl), mock.patch.object(fc.fc_implement, "trail_pack", return_value=""), \
                mock.patch.dict(os.environ, {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}):
            fc.fc_implement.run_task(repo, proj, task, 3)
        self.assertEqual(limits[0], fc.fc_models.TURN_TIMEOUT)  # compose runs the test after the turn, never inside it

    def test_error_falls_back_after_two(self):
        r, calls = self.run_once("error")
        self.assertEqual(r["status"], "passed")
        self.assertEqual(calls, [PRIMARY, PRIMARY, BACKUP])
        self.assertEqual(r["model"], BACKUP)
        self.assertEqual(r["attempts"], 3)
        self.assertEqual(r["log"][1]["fallback"]["why"], "errored")

    def test_two_misses_then_the_fallback(self):
        r, calls = self.run_once("miss")
        self.assertEqual(r["status"], "passed")
        self.assertEqual(calls, [PRIMARY, PRIMARY, BACKUP])
        self.assertNotIn("fallback", r["log"][0])
        self.assertEqual(r["log"][1]["fallback"]["why"], "missed")
        self.assertEqual(self.run_once("miss", after=1)[1], [PRIMARY, BACKUP])  # models.fallback_after

    def test_rate_limit_switches_at_once(self):
        r, calls = self.run_once("rate")
        self.assertEqual((r["status"], calls), ("passed", [PRIMARY, BACKUP]))

    def test_a_turn_cut_short_is_tested_on_the_edit_it_left(self):
        r, calls = self.run_once("rate", edit="yes\n")
        self.assertEqual((r["status"], calls), ("passed", [PRIMARY]))
        r, calls = self.run_once("rate", edit="maybe\n")
        self.assertEqual((r["status"], calls), ("passed", [PRIMARY, BACKUP]))
        self.assertIn("A previous attempt left edits in the files and did not pass", self.prompts[1])
        self.assertIn("grep -q yes a.txt", self.prompts[1].split("did not pass")[1])

    def test_implementer_is_told_not_to_run_the_test(self):
        self.run_once("miss")
        self.assertIn("grep -q yes a.txt", self.prompts[0])
        self.assertIn("Do not run it", self.prompts[0])
        self.assertNotIn(" timed ", self.prompts[0])
        self.assertNotIn("Run the test command", self.prompts[0])

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
            fc.fc_run.preflight({PRIMARY, "pi:r/limited", "claude", None})  # a rate limit proves the model resolved; claude is not probed
            with self.assertRaises(SystemExit) as cm:
                fc.fc_run.preflight({PRIMARY, BACKUP})
        self.assertIn(BACKUP, str(cm.exception))
        self.assertIn("not a valid model ID", str(cm.exception))

    def test_a_pi_auth_key_that_shadows_the_workspace_key_stops_before_any_probe(self):
        auth = Path(tempfile.mkdtemp()) / "auth.json"
        auth.write_text(json.dumps({"openrouter-fast": {"type": "api_key", "key": "k"}, "anthropic": {}}))
        probed = []
        impl = lambda cwd, model, *a, **kw: probed.append(model) or ("s", "OK", 0, {"cost": 0.0})
        with mock.patch.object(fc.fc_implement, "implementer", impl), mock.patch.object(fc.fc_run.fc_pi, "PI_AUTH", auth), \
                mock.patch.object(fc.fc_config, "WORKSPACE", "personal"):
            fc.fc_run.preflight({"pi:openrouter/x", "claude"})  # no pi model of this run uses openrouter-fast
            with self.assertRaises(SystemExit) as cm:
                fc.fc_run.preflight({"pi:openrouter-fast/z-ai/glm", "pi:openrouter/x"})
        self.assertEqual(probed, ["pi:openrouter/x"])
        for words in (str(auth), "openrouter-fast", "'personal'"):
            self.assertIn(words, str(cm.exception))
        self.assertNotIn("model id", str(cm.exception))


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
        if subprocess.run(["which", "trail"], capture_output=True).returncode == 0:
            subprocess.run(["trail", "build", "--no-gitignore", "--no-ignore", str(wt)], cwd=wt, capture_output=True)
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
    def verify(self, writes, reply="", cfg=None, pack=""):
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
        with mock.patch.object(fc.fc_implement, "implementer", impl), mock.patch.object(fc.fc_implement, "trail_pack", return_value=pack), \
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

    def test_fixer_gets_the_trail_pack(self):
        self.verify({"a.go": "fixed\n"}, pack="PACK")
        self.assertIn("CONTEXT PACK from trail (exact file:line). Use it instead of exploring.\nPACK\n\n", self.prompt)
        self.assertNotRegex(self.prompt, r"\bgraft\b")

    def test_review_confirms_only_defects_against_the_requirements(self):
        systems = []
        def fj(env, system, user, **kw):
            systems.append((system, user))
            return {"issues": [{"file": "a.mjs", "severity": "medium", "note": "handle Windows paths"}]} if "strict code reviewer" in system \
                else {"confirmed": True, "evidence": "e"}
        with mock.patch.object(fc.fc_models, "fast_json", fj), mock.patch.object(fc.fc_core, "load_env", return_value={}):
            fc.fc_verify.llm_review({"perspectives": ["correctness"]}, "diff", "THE PLAN", "", True)
        review, confirm = systems
        self.assertIn("hardening", review[0])
        self.assertIn("hardening", confirm[0])
        self.assertIn("THE PLAN", confirm[1])

    def test_a_review_cut_off_at_its_token_budget_is_asked_again_with_a_bigger_one(self):
        full = json.dumps({"issues": [{"file": "a.go", "severity": "low", "note": "n"}]})
        for need, found in ((3000, "n"), (10 ** 6, "did not return usable findings")):  # tokens the whole reply needs
            budgets = []
            def http(req, provider, timeout=90, need=need):
                budgets.append(json.loads(req.data)["max_tokens"])
                short = budgets[-1] < need
                return {"choices": [{"message": {"content": full[:20] if short else full}, "finish_reason": "length" if short else "stop"}]}
            with mock.patch.object(fc.fc_models, "http_json", http), mock.patch.object(fc.fc_core, "load_env", return_value={"TEXT_MODEL_API_KEY": "k"}):
                rv = fc.fc_verify.llm_review({"perspectives": ["spec"]}, "diff", "plan", "", True)
            self.assertEqual(budgets, [1500, 1500 * fc.fc_models.CUT_RETRY])
            self.assertIn(found, rv["issues"][0]["note"])

    def test_a_review_reply_that_is_not_json_is_asked_again(self):
        good = json.dumps({"issues": [{"file": "a.go", "severity": "low", "note": "n"}]})
        for replies, found in ((['{\n  issues": []\n}', good], "n"), (["{issues: []}", "", "never asked"], "did not return usable findings")):
            asked = []
            def http(req, provider, timeout=90, replies=replies):
                asked.append(json.loads(req.data)["max_tokens"])
                return {"choices": [{"message": {"content": replies[len(asked) - 1]}, "finish_reason": "stop"}]}
            with mock.patch.object(fc.fc_models, "http_json", http), mock.patch.object(fc.fc_core, "load_env", return_value={"TEXT_MODEL_API_KEY": "k"}):
                rv = fc.fc_verify.llm_review({"perspectives": ["docs"]}, "diff", "plan", "docs", True)
            self.assertEqual(asked, [1500, 1500])
            self.assertIn(found, rv["issues"][0]["note"])

    def test_review_confirms_only_a_quoted_wrong_line_the_fix_changes(self):
        def review(reply, finding=None, code="build: {\n  fileName: 'x.js',\n}", perspective="spec", cfg=None, users=None):
            def fj(env, system, user, **kw):
                if "strict code reviewer" in system:
                    return {"issues": [finding or {"file": "a.ts", "severity": "high", "note": "n"}]}
                (users if users is not None else []).append(user)
                return reply
            with mock.patch.object(fc.fc_models, "fast_json", fj), mock.patch.object(fc.fc_core, "load_env", return_value={}):
                return fc.fc_verify.llm_review({"perspectives": [perspective], **(cfg or {})}, code, "plan", "==== README.md ====\nREAD ME", True)
        rv = review({"wrong_line": "fileName:   'x.js',", "fixed_line": "fileName: 'x.mjs',", "confirmed": True})
        self.assertEqual([(i["evidence"], i["fix"]) for i in rv["confirmed"]], [("fileName:   'x.js',", "fileName: 'x.mjs',")])
        for reply in ({"wrong_line": "lib output defaults to main.js", "fixed_line": "x", "confirmed": True},  # not a quote of the code
                      {"wrong_line": "", "fixed_line": "x", "confirmed": True},  # no line named
                      {"confirmed": True, "evidence": "fileName: 'x.js',"}):  # a verdict and a quote, but no wrong line
            rv = review(reply)
            self.assertEqual((rv["confirmed"], rv["pass"]), ([], True), reply)
        # A finding whose own text says the code meets the rule in the design context: the line as it must read is the line as it is.
        line = 'state = "ended" if last.get("state") not in (None, "done") and tab_closed(c, agents) else last.get("state", "-")'
        context = "crew list shows `ended` for a closed teammate whose last report is any state but done"
        finding = {"file": "bin/fc_crew.py", "line": 177, "severity": "high", "note": "crew list shows \"ended\" for any closed teammate whose last "
                   "report is not \"done\", but the spec says only for teammates whose last report is any state but done. The diff excludes None "
                   "and \"done\" but still includes other states correctly."}
        users = []
        rv = review({"requirement": context, "wrong_line": line, "fixed_line": " " + line, "confirmed": True}, finding, "+            " + line, "docs",
                    {"review_context": context}, users)
        self.assertEqual((rv["confirmed"], rv["pass"]), ([], True))
        self.assertIn("is the line as it is", rv["issues"][0]["evidence"])
        for seen in (context, "bin/fc_crew.py:177:", "READ ME"):
            self.assertIn(seen, users[0])

    def test_review_counts_only_well_formed_findings_and_prints_each_on_one_line(self):
        # A reviewer that spent its JSON reply on its reasoning: the schema echoed back, then objects of loose thoughts.
        reasoning = [{"file": "str", "line": "int|null", "severity": "high|medium|low", "note": "str}]}`.\n  *   Avoid repeating words."},
                     {"severity": "high", "Analysis": "Seems to align with C1. C1:"}, {"issue": "then later", "line": "If the diff relies on it"},
                     {"file": "a.py", "line": 2.5, "severity": "low", "note": "n"}, {"file": "", "severity": "low", "note": "n"}]
        confirms = []
        def fj(env, system, user, **kw):
            if "strict code reviewer" in system:
                return {"issues": reasoning + [{"file": "a.py", "line": 2, "severity": "high", "note": "add\n  subtracts"}]}
            confirms.append(user)
            return {"wrong_line": "return a - b", "fixed_line": "return a + b", "confirmed": True}
        proj = Path(tempfile.mkdtemp()) / "p"; (proj / "results").mkdir(parents=True)
        out = io.StringIO()
        with mock.patch.object(fc.fc_models, "fast_json", fj), mock.patch.object(fc.fc_core, "load_env", return_value={}), \
                mock.patch.object(fc.fc_verify, "review_inputs", return_value=("return a - b", "plan", "", [])), redirect_stdout(out):
            ok, report, findings = fc.fc_verify.run_stages(proj, proj, {"perspectives": ["correctness"], "jev_acceptance": False},
                                                           type("A", (), {"skip_e2e": True, "skip_review": False}))
        self.assertEqual((ok, len(confirms), [i["file"] for i in report["review"]["issues"]]), (False, 1, ["a.py"]))
        self.assertIn("1 confirmed of 1 raised, 5 malformed dropped", out.getvalue())
        self.assertIn("confirmed [high/correctness] a.py:2: add subtracts\n", out.getvalue())
        self.assertIn("Evidence: return a - b\nMust read: return a + b", findings)
        self.assertNotIn("Avoid", out.getvalue() + findings)
        self.assertNotIn("Analysis", out.getvalue() + findings)

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


def ws(name=None, target=None, stdin="", linear=False):
    out = io.StringIO()
    with mock.patch.object(sys, "stdin", io.StringIO(stdin)), redirect_stdout(out):
        fc.fc_config.cmd_workspace(type("A", (), {"name": name, "target": target, "linear": linear}))
    return out.getvalue()


class Workspaces(unittest.TestCase):
    def setUp(self):
        root = Path(tempfile.mkdtemp())
        self.path, self.auth = root / "config.json", root / "auth.json"
        self.path.write_text('{"workspace": "work", "models": {"implementer": "pi:a/b", "fallback": "pi:g/h", "fallback_after": 3,'
                             ' "test_reader": "claude:claude-haiku-x"},'
                             ' "workspaces": {"work": {}, "personal": {"models": {"fallback": null}}}}')
        self.auth.write_text(json.dumps({"workspaces": {"default": {"openrouter": "sk-or-test-d0d0", "linear": "lin-test-def"},
                                                        "work": {"openrouter": "sk-or-test-w1x2"}}, "typesafe": "ts-test"}))
        for p in (mock.patch.object(fc.fc_config, "CONFIG_PATH", self.path), mock.patch.object(fc.fc_config, "AUTH_PATH", self.auth),
                  mock.patch.object(fc.fc_config, "ENV_FILE", root / ".env"),
                  mock.patch.dict(os.environ, {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"]}, clear=True),  # the real environment may hold real keys
                  mock.patch.object(fc.fc_config, "DEFAULT_MODEL", fc.fc_config.DEFAULT_MODEL), mock.patch.object(fc.fc_config, "FALLBACK_MODEL", fc.fc_config.FALLBACK_MODEL),
                  mock.patch.object(fc.fc_config, "OPENROUTER_KEY", None), mock.patch.object(fc.fc_config, "LINEAR_KEY", None), mock.patch.object(fc.fc_config, "PARALLEL", None)):
            p.start(); self.addCleanup(p.stop)

    def keys(self):
        return fc.fc_config.OPENROUTER_KEY, fc.fc_config.LINEAR_KEY, os.environ.get("OPENROUTER_API_KEY"), os.environ.get("TEXT_MODEL_API_KEY")

    def same(self, got, want):
        """Compares item by item without printing either side: a wrong value may be a real key."""
        self.assertEqual(len(got), len(want))
        for i, (g, w) in enumerate(zip(got, want)):
            self.assertTrue(g == w, f"item {i} differs")

    def test_keys_come_from_auth_json_with_the_default_fallback(self):
        self.same((fc.fc_config.apply_config(), *self.keys()), ("work", "sk-or-test-w1x2", "lin-test-def", "sk-or-test-w1x2", "sk-or-test-w1x2"))
        self.same((os.environ.get("TYPESAFE_API_KEY"), "OPENCODE_CONFIG_CONTENT" in os.environ), ("ts-test", False))  # OpenCode reads its key from a file
        self.assertEqual((fc.fc_config.DEFAULT_MODEL, fc.fc_models.fallback_for("pi:a/b")), ("pi:a/b", "pi:g/h"))
        self.assertEqual((fc.fc_config.FALLBACK_AFTER, fc.fc_config.TEST_READER), (3, "claude:claude-haiku-x"))
        ws("personal")  # no auth.json entry of its own
        self.same((fc.fc_config.apply_config(), *self.keys()), ("personal", "sk-or-test-d0d0", "lin-test-def", "sk-or-test-d0d0", "sk-or-test-d0d0"))

    def test_old_keys_move_first_one_stderr_line_each_and_stdout_stays_clean(self):
        fc_auth = fc.fc_config.fc_auth  # the module apply_config calls, also after another test file reloaded bin/
        def move(*paths):  # the move lands the old config.json key in auth.json
            self.auth.write_text(json.dumps({"workspaces": {"work": {"openrouter": "sk-or-test-mv01"}}}))
            return ["moved workspaces.work.openrouter_api_key out of config.json", "moved TYPESAFE_API_KEY out of .env"]
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(fc_auth, "move_keys", side_effect=move) as moved, redirect_stdout(out), redirect_stderr(err):
            fc.fc_config.apply_config()
        moved.assert_called_once_with(self.path, fc.fc_config.ENV_FILE, self.auth)
        self.same((err.getvalue().splitlines(), out.getvalue(), fc.fc_config.OPENROUTER_KEY), (move(), "", "sk-or-test-mv01"))

    def test_parallel_comes_from_the_config_and_a_workspace_overrides_it(self):
        fc.fc_config.apply_config()
        self.assertIsNone(fc.fc_config.PARALLEL)  # unset: each command keeps its own default
        cfg = fc.fc_config.read_config()
        cfg["parallel"], cfg["workspaces"]["personal"]["parallel"] = 20, 5
        self.path.write_text(json.dumps(cfg))
        fc.fc_config.apply_config()
        self.assertEqual(fc.fc_config.PARALLEL, 20)
        ws("personal")
        fc.fc_config.apply_config()
        self.assertEqual(fc.fc_config.PARALLEL, 5)
        for bad in (0, "many", 2.5, True):
            self.path.write_text(json.dumps({**cfg, "workspace": "default", "parallel": bad}))
            with self.assertRaisesRegex(SystemExit, "parallel must be a whole number"):
                fc.fc_config.apply_config()

    def test_add_key_remove_and_listing_use_auth_json_and_never_print_a_key(self):
        listing = ws("add", "client-x", stdin="sk-or-test-c1c1\n") + ws("key", "client-x", stdin="lin-test-cx\n", linear=True)
        listing += ws("key", "default", stdin="sk-or-test-r0t8\n") + ws()
        self.same([json.loads(self.auth.read_text())["workspaces"]["client-x"]], [{"openrouter": "sk-or-test-c1c1", "linear": "lin-test-cx"}])
        for line in ("work             openrouter key …w1x2, linear key inherits default", "client-x         openrouter key …c1c1, linear key set",
                     "default          openrouter key …r0t8, linear key set"):
            self.assertIn(line, listing)
        self.assertFalse(any(w in listing + self.path.read_text() for w in ("-test-", "api_key")))  # no key printed, none in config.json
        ws("remove", "client-x")
        self.assertFalse({"client-x"} & {*json.loads(self.auth.read_text())["workspaces"], *fc.fc_config.read_config()["workspaces"]})

    def test_an_empty_key_exits_instead_of_billing_default_and_names_are_checked(self):
        ws("add", "later"); ws("later")
        with self.assertRaises(SystemExit):
            fc.fc_config.apply_config()
        for bad in (("nope",), ("add", "default"), ("add", "work"), ("remove", "default"), ("add", "a b"), ("add", None)):
            self.assertRaises(SystemExit, ws, *bad)

    def test_pi_turn_reports_the_providers_error_not_stderr(self):
        err = json.dumps({"message": 'Preset "glm-5-3-flash-fast" not found for this user.', "code": 404,
                          "metadata": {"presetErrorCode": "preset_not_found", "presetSlug": "glm-5-3-flash-fast"}})
        end = json.dumps({"type": "message_end", "message": {"role": "assistant", "content": [], "stopReason": "error", "errorMessage": f"404: {err}"}})
        run = mock.Mock(return_value=mock.Mock(stdout=end + "\n", stderr="Warning: No project session found with id 'x'; creating a new session\n", returncode=0))
        with mock.patch.object(fc.fc_proc, "run", run), mock.patch.object(subprocess, "run", side_effect=AssertionError("went around fc_proc.run")), \
                mock.patch.object(fc.fc_config, "WORKSPACE", "work"), self.assertRaises(RuntimeError) as cm:
            fc.fc_models.pi_turn(tempfile.mkdtemp(), "x/y", "hi")
        self.assertIn("404", str(cm.exception))
        self.assertIn("preset 'glm-5-3-flash-fast' not found in workspace 'work'", str(cm.exception))
        self.assertNotIn("No project session", str(cm.exception))

    def test_a_429_before_any_token_is_a_rate_limit(self):
        err = json.dumps({"message": "Provider returned error", "code": 429, "metadata": {"raw": "z-ai/glm-5.3-flash is temporarily rate-limited upstream."}})
        end = json.dumps({"type": "message_end", "message": {"role": "assistant", "content": [], "stopReason": "error", "errorMessage": f"429: {err}"}})
        run = mock.Mock(return_value=mock.Mock(stdout=end + "\n", stderr="", returncode=0))
        with mock.patch.object(fc.fc_proc, "run", run), self.assertRaises(fc.fc_models.RateLimited):
            fc.fc_models.pi_turn(tempfile.mkdtemp(), "x/y", "hi")


class KeepOldKeys(unittest.TestCase):
    setUp, same = Workspaces.setUp, Workspaces.same

    def old(self):
        """Old keys in config.json and .env that apply_config() moves: personal has no auth.json entry, .env's equals default's."""
        cfg = json.loads(self.path.read_text())
        cfg["parallel"], cfg["env"] = 4, {"KEEP_X": "1"}
        cfg["workspaces"]["personal"]["openrouter_api_key"] = "sk-or-test-p3p3"
        self.path.write_text(json.dumps(cfg))
        self.env = fc.fc_config.ENV_FILE
        self.env.write_text("OTHER=1\nTEXT_MODEL_API_KEY=sk-or-test-d0d0\n")
        return [p.read_bytes() for p in (self.path, self.env, self.auth)]

    def apply(self, **kw):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            ws = fc.fc_config.apply_config(**kw)
        c = fc.fc_config
        got = (ws, c.OPENROUTER_KEY, c.LINEAR_KEY, os.environ.get("OPENROUTER_API_KEY"), os.environ.get("TYPESAFE_API_KEY"), os.environ.get("KEEP_X"),
               c.WORKSPACE, c.DEFAULT_MODEL, c.FALLBACK_MODEL, c.FALLBACK_AFTER, c.TEST_READER, c.PARALLEL)
        return got, out.getvalue() + err.getvalue()

    def test_move_false_keeps_every_file_and_prints_nothing_but_applies_the_same_settings(self):
        before = self.old()
        dry, printed = self.apply(move=False)
        self.same([p.read_bytes() for p in (self.path, self.env, self.auth)], before)
        self.assertEqual(printed, "")
        self.assertEqual(len(fc.fc_config.fc_auth.old_keys(self.path, self.env)), 2)
        self.same(dry[:6], ("work", "sk-or-test-w1x2", "lin-test-def", "sk-or-test-w1x2", "ts-test", "1"))
        self.assertEqual(dry[6:], ("work", "pi:a/b", "pi:g/h", 3, "claude:claude-haiku-x", 4))
        real, printed = self.apply()  # today's move still runs: both old keys leave, one stderr line each
        self.same(real, dry)
        self.assertEqual((fc.fc_config.fc_auth.old_keys(self.path, self.env), len(printed.splitlines())), ([], 2))
        self.assertEqual(self.env.read_text(), "OTHER=1\n")

    def main(self, *argv):
        out = io.StringIO()
        with mock.patch.object(fc.fc_config, "apply_config", return_value="default") as applied, mock.patch.object(sys, "argv", ["compose", *argv]), \
             mock.patch.object(fc.fc_setup, "cmd_setup"), mock.patch.object(fc.fc_init, "cmd_doctor"), \
             mock.patch.dict(os.environ, {"COLUMNS": "500", "NO_COLOR": "1"}), redirect_stdout(out), redirect_stderr(out):
            try:
                fc.main()
            except SystemExit as e:
                self.assertEqual(e.code, 0, out.getvalue())
        moves = [c.kwargs.get("move", c.args[0] if c.args else True) for c in applied.call_args_list]
        return moves, " ".join(out.getvalue().split())

    def test_only_setup_dry_run_passes_move_false_and_help_names_it(self):
        for argv, want in ((["setup", "--dry-run"], [False]), (["setup", "--yes", "--dry-run"], [False]), (["setup"], [True]),
                           (["setup", "--yes"], [True]), (["doctor"], [True])):
            self.assertEqual(self.main(*argv)[0], want, argv)
        sub, top = self.main("setup", "--help")[1], self.main("--help")[1]
        self.assertIn("--dry-run walk the whole setup and change nothing: every change prints as a would line", sub)
        self.assertIn("setup install and configure everything compose needs, one question at a time on a terminal; --yes takes every default and never prompts", top)
        self.assertNotIn("guided", sub + top)


class PiKeyFromEnv(unittest.TestCase):
    """pi gets the OpenRouter key from its environment only: never in argv, never from .env."""
    KEY, MODELS = "sk-or-test", ("pi:openrouter-fast/z-ai/glm@preset/p", "pi:openrouter/x/y", "pi:x/y")

    def setUp(self):
        env = Path(tempfile.mkdtemp()) / ".env"
        env.write_text('TEXT_MODEL_API_KEY="sk-or-dotenv"\n')
        for p in (mock.patch.object(fc.fc_config, "ENV_FILE", env), mock.patch.object(fc.fc_config, "OPENROUTER_KEY", self.KEY)):
            p.start(); self.addCleanup(p.stop)

    def keyless(self, argv):
        self.assertFalse([x for x in argv if x == "--api-key" or "sk-or" in str(x)], argv)

    def pi_turn(self, environ):
        run = mock.Mock(return_value=mock.Mock(stdout='{"type":"tool_execution_start"}', stderr="", returncode=0))
        with mock.patch.object(fc.fc_proc, "run", run), mock.patch.object(subprocess, "run", side_effect=AssertionError("went around fc_proc.run")), mock.patch.dict(os.environ, environ, clear=True):
            fc.fc_models.pi_turn(tempfile.mkdtemp(), "openrouter/x/y", "hi")
        return run.call_args[0][0], run.call_args[1]["env"]

    def test_pi_turn_passes_the_process_key_unchanged_and_none_in_argv(self):
        for workspace_key in (self.KEY, None):
            with self.subTest(workspace_key=workspace_key), mock.patch.object(fc.fc_config, "OPENROUTER_KEY", workspace_key):
                argv, env = self.pi_turn({"PATH": os.environ["PATH"], "OPENROUTER_API_KEY": "sk-or-env"})
                self.assertEqual(env["OPENROUTER_API_KEY"], "sk-or-env")
                self.keyless(argv)

    def test_pi_turn_never_reads_dotenv_for_the_key(self):
        argv, env = self.pi_turn({"PATH": os.environ["PATH"]})
        self.assertFalse("OPENROUTER_API_KEY" in env)
        self.keyless(argv)

    def test_probe_carries_no_key_and_pi_key_args_is_gone(self):
        for model in self.MODELS:
            self.keyless(fc.fc_models.probe_command(model))
        self.assertFalse(hasattr(fc.fc_models, "pi_key_args"))

    def test_pi_teammate_start_carries_no_key(self):
        for model in self.MODELS:
            proj, calls = Path(tempfile.mkdtemp()) / ".compose" / "shop", []
            proj.mkdir(parents=True)
            replies = {("agent", "list"): {"agents": []}, ("tab", "create"): {"tab": {"tab_id": "w9:t3"}, "root_pane": {"pane_id": "w9:p7"}},
                       ("agent", "get"): {"agent": {"agent_status": "working"}}}
            herdr = lambda *args, **kw: calls.append(args) or replies.get(args[:2], {})
            a = type("A", (), {"action": "start", "role": "wayfinder", "title": "t", "brief": "b", "model": model})
            with self.subTest(model=model), mock.patch.object(fc.fc_core, "project_dir", return_value=proj), mock.patch.object(fc.fc_herdr, "herdr", herdr), \
                    mock.patch.object(time, "sleep"), mock.patch.object(fc.fc_herdr, "herdr_env", return_value=True), \
                    mock.patch.object(fc.fc_herdr, "herdr_space", return_value="w9"), mock.patch.object(fc.fc_herdr, "herdr_find_space", return_value="w9"), \
                    mock.patch.object(fc.fc_mcp, "installed_servers", return_value=[]), mock.patch.object(fc.fc_models, "model_available", return_value=(True, "")), \
                    mock.patch("builtins.print"):
                fc.fc_crew.cmd_crew(a)
                start = next(c for c in calls if c[:2] == ("agent", "start"))
                self.assertEqual(start[start.index("--model") + 1], model[3:])
                self.keyless(start)


class ProbeKey(unittest.TestCase):
    """A pi probe gets the process's OpenRouter key in its env, the way pi_turn does; a claude probe keeps headless_env()."""
    KEY, PI, CLAUDE = "sk-or-test-probe", ("pi:openrouter-fast/z-ai/glm@preset/p", "pi:openrouter/x/y", "pi:x/y"), "claude:opus"
    OTHERS = {"TEXT_MODEL_API_KEY": "sk-tm-test", "TYPESAFE_API_KEY": "ts-test", "OPENCODE_CONFIG_CONTENT": "oc-test"}

    def setUp(self):
        env = Path(tempfile.mkdtemp()) / ".env"
        env.write_text('TEXT_MODEL_API_KEY="sk-or-dotenv"\n')
        for p in (mock.patch.object(fc.fc_config, "ENV_FILE", env), mock.patch.object(fc.fc_config, "OPENROUTER_KEY", "sk-or-workspace"),
                  mock.patch.object(fc.fc_core, "scratch_config", return_value="/scratch/config.json")):
            p.start(); self.addCleanup(p.stop)

    def probe(self, model, environ):
        """Runs probe_once under exactly `environ` (plus PATH and HOME). Returns (argv, env, expected headless_env, result)."""
        out = '{"type":"message_end","message":{"role":"assistant","content":[{"type":"text","text":"ok"}]}}'
        run = mock.Mock(return_value=mock.Mock(stdout='{"is_error": false}' if model.startswith("claude:") else out, stderr="", returncode=0))
        environ = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], **environ}
        with mock.patch.object(subprocess, "run", run), mock.patch.dict(os.environ, environ, clear=True):
            result, headless = fc.fc_models.probe_once(model, 5), fc.fc_claude.headless_env()
        return run.call_args[0][0], run.call_args[1]["env"], headless, result

    def keyless(self, argv):
        self.assertFalse([x for x in argv if x == "--api-key" or "sk-" in str(x)], argv)

    def test_pi_probe_gets_the_process_key_unchanged_and_no_other_secret(self):
        for model in self.PI:
            with self.subTest(model=model):
                argv, env, headless, result = self.probe(model, {"OPENROUTER_API_KEY": self.KEY, **self.OTHERS})
                self.assertEqual(env.get("OPENROUTER_API_KEY"), self.KEY)  # not the workspace key, not .env's
                self.assertEqual(env, {**headless, "OPENROUTER_API_KEY": self.KEY})  # nothing else added or dropped
                self.assertFalse(set(self.OTHERS) & set(env))
                self.keyless(argv)
                self.assertEqual(result, (True, "answered", False))

    def test_pi_probe_without_the_process_key_has_none(self):
        for environ in ({}, self.OTHERS):
            with self.subTest(environ=list(environ)):
                argv, env, headless, _ = self.probe(self.PI[0], environ)
                self.assertFalse("OPENROUTER_API_KEY" in env)  # never print an env: it may hold keys
                self.assertFalse("sk-" in json.dumps(env))
                self.assertEqual(env, headless)
                self.keyless(argv)

    def test_claude_probe_env_is_headless_env_exactly(self):
        for environ in ({"OPENROUTER_API_KEY": self.KEY, **self.OTHERS}, {}):
            with self.subTest(with_key=bool(environ)):
                argv, env, headless, _ = self.probe(self.CLAUDE, environ)
                self.assertEqual(env, headless)
                self.assertFalse("OPENROUTER_API_KEY" in env)
                self.keyless(argv)


class HerdrPiKey(unittest.TestCase):
    """The pi implementer started in a herdr pane gets the key from the process environment only: never in argv, never from .env."""
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        (self.root / ".env").write_text('TEXT_MODEL_API_KEY="sk-env"\n')
        (self.root / "wt").mkdir()
        p = mock.patch.object(fc.fc_config, "ENV_FILE", self.root / ".env")
        p.start(); self.addCleanup(p.stop)

    def start(self, environ, workspace_key="sk-or-test"):
        """Runs herdr_pi up to the agent start. Returns (pane env, start argv)."""
        panes, starts = [], []
        def agent_start(*args):
            starts.append(args)
            self.process_key = "OPENROUTER_API_KEY" in os.environ  # read under the patched environment
            raise KeyboardInterrupt  # stop at the start; the turn is not under test
        task = {"meta": {"id": "028", "title": "t"}, "proj": self.root / "shop", "space": "w9"}
        environ = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], **environ}  # nothing from the real environment, which may hold real keys
        with mock.patch.object(fc.fc_config, "OPENROUTER_KEY", workspace_key), mock.patch.dict(os.environ, environ, clear=True), \
                mock.patch.object(fc.fc_herdr, "herdr", return_value={}), mock.patch.object(fc.fc_herdr, "herdr_agent_start", agent_start), \
                mock.patch.object(fc.fc_herdr, "herdr_implementer_pane", lambda space, cwd, env, label: panes.append(env) or "p1"), \
                self.assertRaises(KeyboardInterrupt):
            fc.fc_implement.herdr_pi(str(self.root / "wt"), "openrouter/x/y", "hi", None, task)
        return panes[0], starts[0]

    def keyless(self, argv):
        self.assertEqual(argv[argv.index("--model") + 1], "openrouter/x/y")
        self.assertFalse([x for x in argv if x == "--api-key" or "sk-" in str(x)], argv)

    def test_argv_has_no_key_with_or_without_a_workspace_key(self):
        for workspace_key in ("sk-or-test", None):
            for environ in ({"OPENROUTER_API_KEY": "sk-or-proc"}, {}):
                with self.subTest(workspace_key=workspace_key, environ=environ):
                    self.keyless(self.start(environ, workspace_key)[1])

    def test_pane_gets_the_process_key_unchanged(self):
        env, _ = self.start({"OPENROUTER_API_KEY": "sk-or-proc"})
        self.assertEqual(env.get("OPENROUTER_API_KEY"), "sk-or-proc")  # not the workspace key, not .env's

    def test_pane_gets_no_key_and_nothing_from_dotenv_without_the_variable(self):
        for environ in ({}, {"TEXT_MODEL_API_KEY": "sk-tm"}):
            with self.subTest(environ=environ):
                env, _ = self.start(environ)
                self.assertFalse("OPENROUTER_API_KEY" in env)  # never print an env: it may hold keys
                self.assertFalse("sk-" in json.dumps(env))
                self.assertFalse(self.process_key)  # the fallback did not leak into the process either


class TypeSafeKey(unittest.TestCase):
    """`compose workspace key <name> --typesafe` stores the one TypeSafe key at auth.json's top level; the other paths are unchanged."""
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.auth = self.root / "auth.json"
        (self.root / "config.json").write_text(json.dumps({"workspaces": {"work": {}}}))
        self.auth.write_text(json.dumps({"workspaces": {"default": {"openrouter": "sk-or-test-d0d0"}, "work": {"linear": "lin-test-w0"}},
                                         "typesafe": "ts-test-old"}))
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("HERDR_", "ANTHROPIC_"))} | {
            "HOME": str(self.root), "COMPOSE_CONFIG": str(self.root / "config.json"), "NO_COLOR": "1"}

    def key(self, *args, stdin):
        p = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "bin" / "compose"), "workspace", "key", *args],
                           input=stdin, capture_output=True, text=True, env=self.env, timeout=60)
        self.assertNotIn("-test-", p.stdout + p.stderr)  # never a key value, not even the old one
        return p

    def stored(self):
        return json.loads(self.auth.read_text())

    def test_stores_the_top_level_key_keeping_every_other_entry(self):
        for name in ("work", "default"):  # a named workspace still writes the one shared key, never workspaces.<name>.typesafe
            with self.subTest(name=name):
                p = self.key(name, "--typesafe", stdin=f"  ts-test-{name}\n")
                self.assertEqual(p.returncode, 0)
                self.assertIn("TypeSafe key set (every workspace uses it)", p.stdout.splitlines())
                self.assertTrue(self.stored() == {"workspaces": {"default": {"openrouter": "sk-or-test-d0d0"}, "work": {"linear": "lin-test-w0"}},
                                                  "typesafe": f"ts-test-{name}"}, "auth.json differs")
        self.assertNotIn("test", (self.root / "config.json").read_text())

    def test_an_empty_read_exits_and_names_the_command(self):
        p = self.key("work", "--typesafe", stdin="\n")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("no key read; copy it, then: pbpaste | compose workspace key work --typesafe", p.stderr)
        self.assertTrue(self.stored()["typesafe"] == "ts-test-old", "the old key changed")

    def test_typesafe_with_linear_is_not_allowed(self):
        p = self.key("work", "--typesafe", "--linear", stdin="ts-test-x\n")
        self.assertEqual(p.returncode, 2)
        self.assertRegex(p.stderr, r"argument --(typesafe|linear): not allowed with argument --(typesafe|linear)")
        self.assertTrue(self.stored()["typesafe"] == "ts-test-old", "the old key changed")

    def test_openrouter_and_linear_paths_leave_the_typesafe_key_alone(self):
        self.assertEqual(self.key("work", stdin="sk-or-test-w1\n").returncode, 0)
        self.assertEqual(self.key("work", "--linear", stdin="lin-test-w2\n").returncode, 0)
        self.assertTrue(self.stored() == {"workspaces": {"default": {"openrouter": "sk-or-test-d0d0"}, "work": {"openrouter": "sk-or-test-w1", "linear": "lin-test-w2"}},
                                          "typesafe": "ts-test-old"}, "auth.json differs")


class RetryMessage(unittest.TestCase):
    def run_three(self, summary="", backup=None, session="s", reader_cost=0.0):
        """Attempts write a, b, yes; the test prints 5,000 copies and fails until yes. Returns (result, prompts, logs seen, log path);
        the run's log lines land in self.said."""
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
            return session, "", 1, {"tokens_in": 1, "tokens_out": 1, "cost": 0.0}
        self.said = []
        with mock.patch.object(fc.fc_implement, "implementer", impl), mock.patch.object(fc.fc_implement, "trail_pack", return_value=""), \
                mock.patch.object(fc.fc_implement, "read_failure", return_value=(summary, {"cost": reader_cost, "reference_cost": 0.5} if summary else None)), \
                mock.patch.object(fc.fc_core, "say", self.said.append), \
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

    def test_reader_cost_counts_and_shows(self):
        r, _, _, _ = self.run_three(summary="case_x expected yes, got a", reader_cost=0.01)
        self.assertAlmostEqual(r["cost"], 0.02)
        fails = [l for l in self.said if " attempt " in l and " fail " in l]
        self.assertEqual(len(fails), 2)
        self.assertTrue(all("reader $0.0100" in l for l in fails), fails)

    def test_no_session_to_resume_starts_again_from_the_task(self):
        _, prompts, _, _ = self.run_three(session=None)  # Claude Code runs each turn one-shot
        self.assertTrue(prompts[1].startswith(prompts[0]))
        self.assertIn("The test still fails.", prompts[1])

    def test_no_summary_leaves_out_what_failed(self):
        _, prompts, _, _ = self.run_three(summary="")
        self.assertNotIn("What failed:", prompts[1])
        self.assertIn("Full output: ", prompts[1])

    def test_fallback_starts_from_the_task_and_ends_with_the_same_problems(self):
        r, prompts, _, _ = self.run_three(backup=BACKUP)
        self.assertEqual(r["log"][1]["fallback"]["to"], BACKUP)  # after models.fallback_after (2) misses
        self.assertTrue(prompts[2].startswith(prompts[0]))
        problems = prompts[2][prompts[2].index("The test still fails."):]
        self.assertIn("Full output: ", problems)
        self.assertLess(len(problems), 2000)  # the short tail, not the 3,000-character one


class ProcGroupTurns(unittest.TestCase):
    """Task 002 (NEB-919): pi_turn and opencode start through fc_proc.run; timeout and stop."""
    def setUp(self):
        self.addCleanup(fc.fc_proc.STOP.clear); self.addCleanup(fc.fc_proc.HOOKS.clear); self.addCleanup(fc.fc_proc.RUNNING.clear)
        self.d = Path(tempfile.mkdtemp()); (self.d / "bin").mkdir(); (self.d / "wt").mkdir(); self.wt = str(self.d / "wt"); self.addCleanup(shutil.rmtree, self.d, True)

    def fake(self, body):
        for f in (self.d / "bin" / "pi", self.d / "bin" / "opencode"): f.write_text(f"#!/bin/sh\n{body}\n"); f.chmod(0o755)
        p = mock.patch.dict(os.environ, {"PATH": f"{self.d / 'bin'}{os.pathsep}{os.environ['PATH']}"}); p.start(); self.addCleanup(p.stop)

    def test_both_turns_start_through_fc_proc_run_with_todays_argv_env_and_timeout(self):
        for name, turn, timeout, want, out, extra in (("pi", fc.fc_models.pi_turn, None, fc.fc_models.TURN_TIMEOUT, '{"type":"tool_execution_start"}', {}),
                                                      ("opencode", fc.fc_models.opencode, 7, 7, '{"type":"text","sessionID":"s","part":{"text":"ok"}}',
                                                       {"OPENCODE_DISABLE_CLAUDE_CODE_SKILLS": "1"})):
            with self.subTest(name), mock.patch.object(fc.fc_proc, "run", return_value=subprocess.CompletedProcess([], 0, out, "")) as run, \
                    mock.patch.object(subprocess, "run", side_effect=AssertionError("went around fc_proc.run")):
                turn(self.wt, "openrouter/x/y", "hi", timeout=timeout)
                (argv,), kw = run.call_args
                self.assertEqual((argv[0], argv[-3:], kw["cwd"], kw["timeout"]), (name, ["--model", "openrouter/x/y", "hi"], self.wt, want))
                self.assertEqual({k: v for k, v in kw["env"].items() if k != "COMPOSE_CONFIG"}, {k: v for k, v in {**fc.fc_core.clean_env(), **extra}.items() if k != "COMPOSE_CONFIG"})

    def test_a_turn_past_its_timeout_raises_and_its_whole_group_is_gone(self):
        n = f"31.{os.getpid()}"  # unique to this run: another suite's sleep is not ours to find or kill
        self.fake(f"sleep {n} >/dev/null 2>&1 & wait")  # a tool child that outlives the harness unless its group is killed
        left = lambda: subprocess.run(["pgrep", "-f", f"sleep {n}( |$)"], capture_output=True, text=True).stdout.split()
        self.addCleanup(lambda: [os.kill(int(p), 9) for p in left()])
        with self.assertRaises(subprocess.TimeoutExpired):
            fc.fc_models.pi_turn(self.wt, "openrouter/x/y", "hi", timeout=1)
        for _ in range(30): left() and time.sleep(0.1)  # up to 3 s for the killed group to exit
        self.assertEqual(left(), [], "the turn's tool child outlived its timeout")

    def test_after_the_stop_no_turn_starts(self):
        self.fake(f"touch {self.d / 'started'}; echo '{{\"type\":\"tool_execution_start\"}}'; echo '{{\"type\":\"text\",\"sessionID\":\"s\",\"part\":{{\"text\":\"ok\"}}}}'")
        fc.fc_proc.STOP.set()
        self.assertRaises(fc.fc_proc.Stopped, fc.fc_models.pi_turn, self.wt, "openrouter/x/y", "hi")
        self.assertRaises(fc.fc_proc.Stopped, fc.fc_models.opencode, self.wt, "openrouter/x/y", "hi")
        self.assertFalse((self.d / "started").exists(), "a turn started after the stop")


class RunnerReadGuard(unittest.TestCase):
    """Task 007 (NEB-955): pi_turn and opencode argv, env and config with and without a guard file."""

    def turn(self, runner, guard, key=None):
        wt = Path(tempfile.mkdtemp()) / "001"; wt.mkdir(); self.addCleanup(shutil.rmtree, wt.parent, True); g = wt.parent / "001.guard.json"
        if guard:
            g.write_text(json.dumps({"root": str(wt), "allow": [], "log": str(wt.parent / "001.refused")}))
        out = '{"type":"tool_execution_start"}' if runner is fc.fc_models.pi_turn else '{"type":"text","sessionID":"s","part":{"text":"ok"}}'
        with mock.patch.object(fc.fc_proc, "run", return_value=subprocess.CompletedProcess([], 0, out, "")) as run, \
                mock.patch.object(subprocess, "run", run), mock.patch.object(fc.fc_readguard, "command", lambda f: f"guard {f}"), \
                mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": key} if key else {}):
            runner(str(wt), "openrouter/x/y", "hi")
        argv, env = run.call_args.args[0], run.call_args.kwargs["env"]
        self.assertEqual(env.get("COMPOSE_READGUARD"), f"guard {g}" if guard else None)
        return argv, env

    def test_pi_turn_loads_the_extension_only_with_a_guard_file(self):
        argv, _ = self.turn(fc.fc_models.pi_turn, True)
        self.assertIn(["-e", str(fc.fc_readguard.PI_EXT)], [argv[i:i + 2] for i in range(len(argv))])
        self.assertNotIn("-e", self.turn(fc.fc_models.pi_turn, False)[0])

    def test_opencode_config_adds_the_plugin_and_deny_rules_to_the_key_block_only_with_a_guard_file(self):
        rules = {"plugin": [f"file://{fc.fc_readguard.OC_PLUGIN}"], "permission": {"external_directory": "deny",
                 "bash": {"*": "deny", "trail ask *": "allow", "trail callers *": "allow"}}}
        block = lambda: {"provider": {"openrouter": {"options": {"apiKey": f"{{file:{fc.fc_config.key_file('sk-x')}}}"}}}}
        for guard, key, want in [(True, "sk-x", {**block(), **rules}), (True, None, rules), (False, "sk-x", block()), (False, None, None)]:
            env = self.turn(fc.fc_models.opencode, guard, key)[1]
            got = env.get("OPENCODE_CONFIG_CONTENT")
            self.assertEqual(got and json.loads(got), want, (guard, key))


class ReadGuardWiring(unittest.TestCase):
    """Task 009 (NEB-946): run_task writes the guard, herdr pi loads it, refusals are counted per attempt."""
    USAGE = {"tokens_in": 1, "tokens_out": 1, "cost": 0.0}

    def run_one(self, impl, task_extra=None, attempts=3, files={"a.txt": "no\n"}, pack="", stale=0):
        root = Path(tempfile.mkdtemp()); repo, proj = root / "repo", root / "proj"; repo.mkdir(); proj.mkdir(); self.addCleanup(shutil.rmtree, root, True)
        (proj / "worktrees").mkdir(); (proj / "worktrees" / "001.refused").write_text("{}\n" * stale)  # a previous run's refusals
        git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        for f, t in files.items(): (repo / f).parent.mkdir(parents=True, exist_ok=True); (repo / f).write_text(t)
        git("add", "-A"); git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        task = {"id": "001", "title": "answer", "files": ["a.txt"], "protected": [], "test": "grep -q yes a.txt",
                "model": "pi:p/primary", "after": "", "linear": "ENG-1", "body": "## Goal\nWrite yes.", **(task_extra or {})}
        with mock.patch.object(fc.fc_implement, "implementer", impl), mock.patch.object(fc.fc_implement, "trail_pack", return_value=pack), \
                mock.patch.object(fc.fc_config, "TEST_READER", None), \
                mock.patch.dict(os.environ, {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}):
            return fc.fc_implement.run_task(repo, proj, task, attempts), repo, proj

    def test_the_guard_beside_the_clone_allows_files_protected_tests_and_the_pack_before_the_turn(self):
        files = {"a.txt": "no\n", "t.sh": "x\n", "lib/x.py": "y\n"}
        for pack, allowed in [("1. f · function\n   lib/x.py:L1-L2\n   t.sh:L3-L4", {"a.txt", "t.sh", "lib/x.py"}), ("", {"a.txt", "t.sh"})]:
            seen = []
            def impl(cwd, *a, **k):
                g = Path(cwd).parent / "001.guard.json"
                seen.append(g.exists() and json.loads(g.read_text()))
                (Path(cwd) / "a.txt").write_text("yes\n")
                return ("s", "", 1, self.USAGE)
            _, _, proj = self.run_one(impl, {"protected": ["t.sh"]}, files=files, pack=pack)
            wt = proj / "worktrees" / "001"
            self.assertTrue(seen[0], "no guard file beside the clone when the turn started")
            self.assertEqual(set(seen[0]["allow"]), {os.path.realpath(wt / f) for f in allowed}, pack)

    def test_each_attempt_counts_only_its_own_refusals_in_the_result_and_the_run_log(self):
        def impl(cwd, *a, **k):
            first = not (Path(cwd).parent / "turned").exists(); (Path(cwd).parent / "turned").touch()
            with open(Path(cwd).parent / "001.refused", "a") as f:
                f.write('{"tool": "read", "args": {}}\n' * (2 if first else 1))
            (Path(cwd) / "a.txt").write_text("no\n" if first else "yes\n")
            return ("s", "", 1, self.USAGE)
        out = io.StringIO()
        with redirect_stdout(out):
            result, _, proj = self.run_one(impl, stale=5)
        self.assertEqual(result["status"], "passed")
        self.assertEqual([e.get("refused") for e in json.loads((proj / "results" / "001.json").read_text())["log"]], [2, 1])
        self.assertRegex(out.getvalue(), r"001 attempt 1 fail .*lines=\d+\s+refused=2\b")
        self.assertRegex(out.getvalue(), r"001 attempt 2 pass .*lines=\d+\s+refused=1\b")

    def test_herdr_pi_loads_the_extension_and_the_guard_command_only_with_a_guard_file(self):
        for guard in (True, False):
            root = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, root, True); (root / "wt").mkdir(); g = root / "wt.guard.json"
            if guard:
                g.write_text(json.dumps({"root": str(root / "wt"), "allow": [], "log": str(root / "wt.refused")}))
            panes, starts = [], []
            task = {"meta": {"id": "028", "title": "t"}, "proj": root / "shop", "space": "w9"}
            with mock.patch.object(fc.fc_herdr, "herdr", return_value={}), \
                    mock.patch.object(fc.fc_herdr, "herdr_agent_start", lambda *a: starts.append(list(a)) or (_ for _ in ()).throw(KeyboardInterrupt)), \
                    mock.patch.object(fc.fc_herdr, "herdr_implementer_pane", lambda space, cwd, env, label: panes.append(env) or "p1"), \
                    mock.patch.object(fc.fc_readguard, "command", lambda f: f"guard {f}"), self.assertRaises(KeyboardInterrupt):
                fc.fc_implement.herdr_pi(str(root / "wt"), "openrouter/x/y", "hi", None, task)
            pairs = [starts[0][i:i + 2] for i in range(len(starts[0]))]
            self.assertEqual(["-e", str(fc.fc_readguard.PI_EXT)] in pairs, guard)
            self.assertEqual(panes[0].get("COMPOSE_READGUARD"), f"guard {g}" if guard else None)


class LibrarySection(unittest.TestCase):
    """Task 012 (NEB-950): the LIBRARY API section in the implementer prompt and the shared budget."""
    def run_one(self, section, pack=True):
        """run_task with fc_libapi.section answering `section` and a fake trail_pack that fills its cap (or gives nothing).
        Returns (first prompt, the caps the pack got, the section calls, the clone)."""
        root = Path(tempfile.mkdtemp()); repo, proj = root / "repo", root / "proj"; repo.mkdir(); proj.mkdir(); self.addCleanup(shutil.rmtree, root, True)
        git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        for f, t in {"a.txt": "no\n", "t.sh": "grep -q yes a.txt  # TEST TEXT\n"}.items(): (repo / f).write_text(t)
        git("add", "-A"); git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        task = {"id": "001", "title": "answer", "files": ["a.txt"], "protected": ["t.sh", "gone.sh"], "test": "sh t.sh",
                "model": "pi:p/primary", "after": "", "linear": "ENG-1", "body": "## Goal\nWrite yes.\n## Notes\nKeep it short."}
        prompts, caps = [], []
        def impl(cwd, model, prompt, session=None, task=None, timeout=None):
            prompts.append(prompt); (Path(cwd) / "a.txt").write_text("yes\n")
            return "s", "", 1, {"tokens_in": 1, "tokens_out": 1, "cost": 0.0}
        def trail_pack(wt, query, repo=None, limit=6, cap=12000):
            caps.append(cap); return "P" * cap if pack else ""
        with mock.patch.object(fc.fc_implement, "implementer", impl), mock.patch.object(fc.fc_implement, "trail_pack", trail_pack), \
                mock.patch.object(fc.fc_libapi, "section", return_value=section) as sec, mock.patch.object(fc.fc_config, "TEST_READER", None), \
                mock.patch.dict(os.environ, {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}):
            self.assertEqual(fc.fc_implement.run_task(repo, proj, task, 3)["status"], "passed")
        return prompts[0], caps, sec.call_args_list, proj / "worktrees" / "001"

    def test_the_section_sits_between_the_pack_and_the_body_and_shares_the_12000_budget(self):
        section = "LIBRARY API for the packages this task imports\nlib 1.0\nlib.f(x, y=2)"
        prompt, caps, calls, wt = self.run_one(section)
        self.assertEqual(len(calls), 1)
        (cwt, files, words), kw = calls[0]
        self.assertEqual((Path(cwt).resolve(), files, kw), (wt.resolve(), ["a.txt"], {}))
        self.assertIn("Write yes.", words); self.assertIn("TEST TEXT", words); self.assertNotIn("Keep it short.", words)
        self.assertEqual(caps, [12000 - len(section)])
        pack = "P" * caps[0]
        self.assertLess(prompt.index(pack + "\n"), prompt.index(section))
        self.assertLess(prompt.index(section) + len(section), prompt.index("## Goal\nWrite yes."))
        self.assertNotIn("P" * (caps[0] + 1), prompt)

    def test_a_section_without_a_pack_still_comes_before_the_body(self):
        prompt, caps, _, _ = self.run_one("LIBRARY API x\nlib 1.0", pack=False)
        self.assertLess(prompt.index("LIBRARY API x\nlib 1.0"), prompt.index("## Goal\nWrite yes."))
        self.assertNotIn("CONTEXT PACK", prompt)

    def test_no_section_leaves_the_prompt_as_today_with_the_full_pack(self):
        prompt, caps, calls, _ = self.run_one("")
        self.assertEqual((caps, len(calls)), ([12000], 1))
        self.assertIn("do not open unrelated files.\n" + "P" * 12000 + "\n\n## Goal\nWrite yes.", prompt)


class DeleteTasks(unittest.TestCase):
    """Task 015 (NEB-952): delete: applied in the clone, and delete-only tasks with no model turn."""
    def run_one(self, impl, task_extra=None, attempts=3, files={"a.txt": "no\n"}):
        root = Path(tempfile.mkdtemp()); repo, proj = root / "repo", root / "proj"; repo.mkdir(); proj.mkdir(); self.addCleanup(shutil.rmtree, root, True)
        git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
        git("init", "-q", "-b", "main")
        for f, t in files.items(): (repo / f).parent.mkdir(parents=True, exist_ok=True); (repo / f).write_text(t)
        git("add", "-A"); git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        task = {"id": "001", "title": "answer", "files": ["a.txt"], "protected": [], "test": "grep -q yes a.txt",
                "model": "pi:p/primary", "after": "", "linear": "ENG-1", "body": "## Goal\nWrite yes.", **(task_extra or {})}
        with mock.patch.object(fc.fc_implement, "implementer", impl), mock.patch.object(fc.fc_implement, "trail_pack", return_value=""), \
                mock.patch.object(fc.fc_config, "TEST_READER", None), \
                mock.patch.dict(os.environ, {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}):
            return fc.fc_implement.run_task(repo, proj, task, attempts), repo, proj

    def tree(self, repo):
        branch = fc.fc_worktree.task_branch(repo, repo.parent / "proj", "001")  # run_one puts proj beside repo
        out = subprocess.run(["git", "ls-tree", "-r", "--name-only", branch], cwd=repo, capture_output=True, text=True)
        return out.stdout.split() if out.returncode == 0 else None

    def edit(self, seen, extra=lambda cwd: None):
        def impl(cwd, model, prompt, session=None, task=None, timeout=None):
            seen.append(sorted(str(p.relative_to(cwd)) for p in Path(cwd).rglob("*.txt"))); (Path(cwd) / "a.txt").write_text("yes\n"); extra(Path(cwd))
            return "s", "", 1, {"tokens_in": 1, "tokens_out": 1, "cost": 0.0}
        return impl

    def test_a_delete_only_task_removes_a_400_line_directory_and_commits_with_no_turn(self):
        impl = mock.Mock(side_effect=AssertionError("no turn"))
        files = {"a.txt": "no\n", "old/a.py": "x\n" * 300, "old/sub/b.py": "y\n" * 100}
        result, repo, _ = self.run_one(impl, {"files": [], "delete": ["old/"], "test": "test ! -e old"}, files=files)
        impl.assert_not_called()
        self.assertEqual((result["status"], len(result["log"])), ("passed", 1))
        self.assertEqual(self.tree(repo), ["a.txt"])

    def test_a_delete_only_task_whose_test_fails_or_touches_other_files_fails_after_one_attempt(self):
        for test in ("grep -q yes a.txt", "test ! -e gone.txt && touch b.py"):
            impl = mock.Mock(side_effect=AssertionError("no turn"))
            result, repo, _ = self.run_one(impl, {"files": [], "delete": ["gone.txt"], "test": test}, files={"a.txt": "no\n", "gone.txt": "z\n"})
            impl.assert_not_called()
            self.assertEqual((result["status"], len(result["log"]), self.tree(repo)), ("failed", 1, None), test)

    def test_delete_paths_are_gone_before_the_turn_and_from_the_branch_beside_an_edit(self):
        seen = []
        result, repo, _ = self.run_one(self.edit(seen), {"delete": ["gone.txt"]}, files={"a.txt": "no\n", "gone.txt": "z\n", "keep.txt": "k\n"})
        self.assertEqual((result["status"], seen), ("passed", [["a.txt", "keep.txt"]]))
        self.assertEqual(self.tree(repo), ["a.txt", "keep.txt"])

    def test_a_turn_deleting_a_file_outside_files_and_delete_is_rejected_for_scope(self):
        impl = self.edit([], lambda cwd: (cwd / "keep.txt").unlink())
        result, _, _ = self.run_one(impl, {"delete": ["gone.txt"]}, attempts=1, files={"a.txt": "no\n", "gone.txt": "z\n", "keep.txt": "k\n"})
        self.assertEqual((result["status"], result["log"][0]["stray"]), ("rejected_scope", ["keep.txt"]))

    def test_a_task_without_delete_and_without_files_still_gets_a_turn_and_no_scope_check(self):
        seen = []
        result, repo, _ = self.run_one(self.edit(seen, lambda cwd: (cwd / "b.py").write_text("b\n")), {"files": []})
        self.assertEqual((result["status"], len(seen), self.tree(repo)), ("passed", 1, ["a.txt", "b.py"]))
