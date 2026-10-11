import importlib.machinery, importlib.util, os, shutil, subprocess, tempfile, time, unittest
from pathlib import Path
from unittest import mock
os.environ["FAST_CODING_NO_TREEHOUSE"] = "1"  # these cover the plain-worktree path; test_treehouse covers the pool
os.environ["FAST_CODING_E2E_HEADLESS"] = "1"  # testing the tool itself never opens a browser window; real projects keep theirs

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)


class FormatOnPass(unittest.TestCase):
    @unittest.skipUnless(shutil.which("gofmt"), "gofmt not installed")
    def test_passed_task_is_committed_formatted(self):
        root = Path(tempfile.mkdtemp())
        repo, proj = root / "repo", root / "proj"
        repo.mkdir(); proj.mkdir()
        git = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, text=True)
        git("init", "-q", "-b", "main")
        (repo / "a.go").write_text("package a\n")
        git("add", "-A"); git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        task = {"id": "001", "title": "f", "files": ["a.go"], "protected": [], "test": "grep -q F a.go",
                "model": "pi:x/y", "after": "", "linear": "ENG-1", "body": "## Goal\nAdd F."}
        def impl(cwd, model, prompt, session=None, task=None):
            (Path(cwd) / "a.go").write_text("package a\nfunc   F( ) int {\nreturn 1}\n")
            return "s", "", 1, {"tokens_in": 1, "tokens_out": 1, "cost": 0.0}
        with mock.patch.object(fc, "implementer", impl), mock.patch.object(fc, "graft_pack", return_value=""), \
                mock.patch.object(fc, "FALLBACK_MODEL", None), \
                mock.patch.dict(os.environ, {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}):
            r = fc.run_task(repo, proj, task, 1)
        self.assertEqual(r["status"], "passed")
        self.assertEqual(git("show", "fast/proj/001:a.go").stdout, "package a\n\nfunc F() int {\n\treturn 1\n}\n")


class Waves(unittest.TestCase):
    def test_independent_tasks_share_a_wave(self):
        t = lambda i, after="": {"id": i, "after": after}
        waves = fc.run_waves([t("001"), t("002", "001"), t("003"), t("004", "001"), t("005", "002,003,004"),
                              t("006"), t("007", "006"), t("009", "042")])
        # an `after:` outside the list (merged, or another wave) does not make a task wait
        self.assertEqual(waves, [["001", "003", "006", "009"], ["002", "004", "007"], ["005"]])


class E2EBesideReview(unittest.TestCase):
    def test_e2e_runs_while_review_waits_on_models(self):
        slow = lambda result: (lambda *a, **k: (time.sleep(1.5), result)[1])
        # a configured browser, so the stage does not launch its own: this times the overlap, not a Chromium start
        cfg = {"e2e": [{"name": "flow"}], "e2e_env": {"BU_CDP_URL": "http://127.0.0.1:1"}, "review": True, "jev_acceptance": True}
        args = type("A", (), {"skip_e2e": False, "skip_review": False})()
        with mock.patch.object(fc, "herdr_verify_panes", return_value={}), mock.patch.object(fc, "herdr_space", return_value=None), \
                mock.patch.object(fc, "review_inputs", return_value=("", "", "", [])), \
                mock.patch.object(fc, "jev_e2e", slow({"exit": 0, "stdout": "", "stderr": ""})), \
                mock.patch.object(fc, "llm_review", slow({"pass": True, "issues": [], "confirmed": []})), \
                mock.patch.object(fc, "jev_acceptance", lambda *a, **k: {"pass": True, "criteria": [], "failed": []}):
            t0 = time.time()
            ok, report, _ = fc.run_stages(Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp()), cfg, args)
        self.assertTrue(ok)
        self.assertEqual(len(report["e2e"]), 1)
        self.assertLess(time.time() - t0, 2.6)  # in sequence, 1.5s of e2e plus 1.5s of review is 3s; overlap plus stage setup stays under


if __name__ == "__main__":
    unittest.main()
