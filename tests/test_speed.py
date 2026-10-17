import importlib.machinery, importlib.util, os, shutil, subprocess, tempfile, time, unittest
from pathlib import Path
from unittest import mock
import sys
os.environ["FAST_CODING_NO_TREEHOUSE"] = "1"  # these cover the plain-worktree path; test_treehouse covers the pool
os.environ["FAST_CODING_E2E_HEADLESS"] = "1"  # testing the tool itself never opens a browser window; real projects keep theirs

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast_coding.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
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
                mock.patch.object(fc.fc_config, "FALLBACK_MODEL", None), \
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


def task_issue(ident, tid, crits, **kv):
    body = "## Goal\nDo it.\n\n## Acceptance criteria\n" + "".join(f"- {c}\n" for c in crits)
    block = "\n```fast-coding\n" + "\n".join(f"{k}: {v}" for k, v in {"id": tid, **kv, "test": "t"}.items()) + "\n```\n"
    return {"id": ident, "title": tid, "description": body + block, "status": "Todo", "blockedBy": []}


def hunk(path, body):
    return f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -0,0 +1 @@\n+{body}\n"


class AcceptanceJudge(unittest.TestCase):
    """The judge reads each task's own diff hunks, and confirm calls share one 60,000-character budget per task."""
    def test_state_is_the_tasks_hunks_and_confirm_shares_one_budget_per_task(self):
        repo, proj = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp()) / "p"
        (repo / "tests").mkdir()
        for f, n in (("a.py", 21000), ("tests/test_a.py", 21000), ("b.py", 31000)):
            (repo / f).write_text("R" * n)  # whole files, which only confirm reads
        proj.mkdir()
        (proj / "linear.json").write_text('{"feature": "ENG-1"}')
        fc.fc_tasks.sync_tasks(proj, {"feature": {"id": "ENG-1", "title": "F", "description": ""}, "issues": [
            task_issue("ENG-2", "002", ["a1", "a2", "a3"], files="a.py", protected="tests/test_a.py"),
            task_issue("ENG-3", "003", ["b1", "b2", "b3"], files="b.py"),
            task_issue("ENG-4", "004", ["c1"], files="c.py")]})
        diff = (hunk("a.py", "A_OWN") + hunk("lib/a.py", "NOT_MINE") + hunk("tests/test_a.py", "T_OWN") + hunk("b.py", "B" * 40000))
        reply = {"model": "m", "answers": {f"c{i}": {"choice": "NOT_MET", "probabilities": {"NOT_MET": 0.9}} for i in range(3)}}
        sent = []
        def confirm_call(env, system, user, max_tokens=500):
            crit, code = user.split("\n\nCODE:\n", 1)
            sent.append((crit[len("CRITERION: "):], code))
            return True, "x"
        with mock.patch.object(fc.fc_config, "ENV_FILE", proj / "none.env"), mock.patch.object(fc.fc_models, "jev_ask", return_value=reply) as ask, \
                mock.patch.object(fc.fc_models, "confirm_call", side_effect=confirm_call):
            res = fc.jev_acceptance({}, proj, diff, repo=repo)
        states = {c.args[2]["task"]: c.args[2] for c in ask.call_args_list if c.args[4] == "Jev acceptance"}
        a, b, c = states["002"], states["003"], states["004"]
        self.assertEqual(a["files"], ["a.py", "tests/test_a.py"])
        self.assertLess(a["code"].index("A_OWN"), a["code"].index("T_OWN"))
        self.assertNotIn("NOT_MINE", a["code"])  # lib/a.py is another path, not a.py
        self.assertNotIn("B" * 10, a["code"])
        self.assertNotIn("R" * 10, a["code"] + b["code"])  # the state never reads the repo
        self.assertTrue(b["code"].startswith("diff --git a/b.py b/b.py"))
        self.assertEqual(len(b["code"]), fc.JEV_CODE_CAP)
        self.assertEqual(c["code"], diff[:fc.JEV_CODE_CAP])  # no hunk of its own: the whole diff, capped
        for prefix in ("a", "b"):
            calls = [code for crit, code in sent if crit.startswith(prefix)]
            self.assertEqual(len(calls), 2, prefix)  # the second call gets the rest of the budget, the third none
            self.assertLessEqual(sum(map(len, calls)), 60000, prefix)
            spent = [r for r in res["suspects"] if r["criterion"].startswith(prefix) and r.get("evidence") == "confirm budget spent"]
            self.assertEqual([r["confirmed"] for r in spent], [False], prefix)
            self.assertNotIn(spent[0]["criterion"], [crit for crit, _ in sent])

    def test_confirm_reads_only_regular_files_and_budgets_what_it_sends(self):
        repo, proj = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp()) / "p"
        for d in ("sections", "docs", "tests/fixtures"):
            (repo / d).mkdir(parents=True)
            (repo / d / "inner.md").write_text("INNER")
        (repo / "a.py").write_text("A" * 50000)
        proj.mkdir()
        (proj / "linear.json").write_text('{"feature": "ENG-1"}')
        fc.fc_tasks.sync_tasks(proj, {"feature": {"id": "ENG-1", "title": "F", "description": ""}, "issues": [
            task_issue("ENG-2", "002", ["a1", "a2", "a3"], files="sections, a.py", protected="tests/fixtures, gone.py"),
            task_issue("ENG-3", "003", ["b1"], files="docs")]})
        reply = {"model": "m", "answers": {f"c{i}": {"choice": "NOT_MET", "probabilities": {"NOT_MET": 0.9}} for i in range(3)}}
        sent = []
        def confirm_call(env, system, user, max_tokens=500):
            crit, code = user.split("\n\nCODE:\n", 1)
            sent.append((crit[len("CRITERION: "):], code))
            return True, "x"
        with mock.patch.object(fc.fc_config, "ENV_FILE", proj / "none.env"), mock.patch.object(fc.fc_models, "jev_ask", return_value=reply), \
                mock.patch.object(fc.fc_models, "confirm_call", side_effect=confirm_call):
            res = fc.jev_acceptance({}, proj, hunk("a.py", "x"), repo=repo)  # raises IsADirectoryError if a directory is read
        whole = "==== a.py ====\n" + "A" * 50000
        a = sorted((code for crit, code in sent if crit.startswith("a")), key=len)
        self.assertEqual(a, [whole[:60000 - len(whole)], whole])  # the directories cost nothing; the second call gets the rest
        self.assertNotIn("INNER", "".join(code for _, code in sent))
        self.assertEqual([code for crit, code in sent if crit == "b1"], [""])  # only directories: still sent, with budget left
        self.assertEqual([r["evidence"] for r in res["suspects"] if not r["confirmed"]], ["confirm budget spent"])
        self.assertEqual(len(res["failed"]), 3)  # suspects are judged as before


if __name__ == "__main__":
    unittest.main()
