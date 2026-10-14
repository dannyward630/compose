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
        def impl(cwd, model, prompt, session=None, task=None, timeout=None):
            (Path(cwd) / "a.go").write_text("package a\nfunc   F( ) int {\nreturn 1}\n")
            return "s", "", 1, {"tokens_in": 1, "tokens_out": 1, "cost": 0.0}
        with mock.patch.object(fc, "implementer", impl), mock.patch.object(fc, "graft_pack", return_value=""), \
                mock.patch.object(fc, "FALLBACK_MODEL", None), \
                mock.patch.dict(os.environ, {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}):
            r = fc.run_task(repo, proj, task, 1)
        self.assertEqual(r["status"], "passed")
        self.assertEqual(git("show", "fast/proj/001:a.go").stdout, "package a\n\nfunc F() int {\n\treturn 1\n}\n")

    def test_final_newline_added_without_a_formatter_but_base_and_binary_kept(self):
        wt = Path(tempfile.mkdtemp())
        git = lambda *a: subprocess.run(["git", *a], cwd=wt, check=True, capture_output=True, text=True)
        git("init", "-q", "-b", "main")
        (wt / "bare.txt").write_bytes(b"no newline")
        (wt / "bin.dat").write_bytes(b"\0\1")
        git("add", "-A"); git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        (wt / "new.mjs").write_bytes(b"export {}")
        (wt / "bare.txt").write_bytes(b"still none")
        (wt / "bin.dat").write_bytes(b"\0\2")
        (wt / "old.mjs").write_bytes(b"a\n\n\n")
        git("add", "-A")
        fc.format_files(wt, ["new.mjs", "bare.txt", "bin.dat", "old.mjs"], "HEAD")
        self.assertEqual((wt / "new.mjs").read_bytes(), b"export {}\n")
        self.assertEqual((wt / "old.mjs").read_bytes(), b"a\n")
        self.assertEqual((wt / "bare.txt").read_bytes(), b"still none")
        self.assertEqual((wt / "bin.dat").read_bytes(), b"\0\2")


class Waves(unittest.TestCase):
    def test_independent_tasks_share_a_wave(self):
        t = lambda i, after="": {"id": i, "after": after}
        waves = fc.run_waves([t("001"), t("002", "001"), t("003"), t("004", "001"), t("005", "002,003,004"),
                              t("006"), t("007", "006"), t("009", "042")])
        # an `after:` outside the list (merged, or another wave) does not make a task wait
        self.assertEqual(waves, [["001", "003", "006", "009"], ["002", "004", "007"], ["005"]])


class E2EBesideReview(unittest.TestCase):
    def test_e2e_runs_while_review_waits_on_models(self):
        spans = {}
        def slow(name, result):
            def run(*a, **k):
                start = time.time(); time.sleep(0.5); spans[name] = (start, time.time()); return result
            return run
        # a configured browser, so the stage does not launch its own: this times the overlap, not a Chromium start
        cfg = {"e2e": [{"name": "flow"}], "e2e_env": {"BU_CDP_URL": "http://127.0.0.1:1"}, "review": True, "jev_acceptance": True}
        args = type("A", (), {"skip_e2e": False, "skip_review": False})()
        with mock.patch.object(fc, "herdr_verify_panes", return_value={}), mock.patch.object(fc, "herdr_space", return_value=None), \
                mock.patch.object(fc, "review_inputs", return_value=("", "", "", [])), \
                mock.patch.object(fc, "jev_e2e", slow("e2e", {"exit": 0, "stdout": "", "stderr": ""})), \
                mock.patch.object(fc, "llm_review", slow("review", {"pass": True, "issues": [], "confirmed": []})), \
                mock.patch.object(fc, "jev_acceptance", lambda *a, **k: {"pass": True, "criteria": [], "failed": []}):
            ok, report, _ = fc.run_stages(Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp()), cfg, args)
        self.assertTrue(ok)
        self.assertEqual(len(report["e2e"]), 1)
        (a0, a1), (b0, b1) = spans["e2e"], spans["review"]
        self.assertLess(max(a0, b0), min(a1, b1))  # the two waits overlap; wall time would depend on machine load


if __name__ == "__main__":
    unittest.main()
