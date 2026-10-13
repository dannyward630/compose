import importlib.machinery, importlib.util, io, json, os, subprocess, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
os.environ["FAST_CODING_NO_TREEHOUSE"] = "1"

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)
SETTLED = "## Not yet specified\n\nNone\n\n### Codebase brief\n\nWhere things live.\n\n## Plan\n\nThe plan."
STORY = {"id": "ENG-2", "title": "Story", "description": "## Acceptance criteria\n\n* it works", "status": "Todo", "blockedBy": []}
TASKS_TAIL = ("  003  T                                        001        ENG-5     b.go | 003_test.go | t\n\n  WARNING two tasks own the same file (they must be one task, or one must be `after:` the other):\n    a.go: 001, 002\n\n  run waves (each wave in parallel): 001, 002  then  003\n\n  WARNING SERIAL CHAIN: 3 tasks run in 2 waves, mostly one after another. Keep an `after:` (blocked-by) only where a task needs another task's code or file; stack order for review comes from ids, not from `after:`.\n")
has = lambda gaps, *kws: any(k in g for g in gaps for k in kws)
data = lambda issues, desc=SETTLED: {"feature": {"id": "ENG-1", "title": "F", "description": desc}, "issues": [STORY, *issues]}
check = lambda issues, desc=SETTLED, root=None: {i: (ok, level, gaps) for ok, i, level, gaps in fc.spec_check(data(issues, desc), root)}


def task(ident, tid, blocked_by=(), crit="- works", **kv):
    kv = {"id": tid, "files": f"{tid}.go", "protected": f"{tid}_test.go", "test": "t", **kv}
    desc = f"## Acceptance criteria\n{crit}\n\n```fast-coding\n" + "\n".join(f"{k}: {v}" for k, v in kv.items()) + "\n```\n"
    return {"id": ident, "title": "T", "description": desc, "status": "Todo", "blockedBy": list(blocked_by), "parentId": "ENG-2"}


class SpecCheck(unittest.TestCase):
    def run_cli(self, stdin):
        with mock.patch.object(fc.sys, "stdin", io.StringIO(stdin)), mock.patch("sys.stdout", io.StringIO()) as out:
            try: fc.cmd_spec_check(SimpleNamespace(repo=".", project=None, stdin=True))
            except SystemExit as e: return out.getvalue().splitlines(), e
        return out.getvalue().splitlines(), SystemExit(0)

    def test_cli_pass_fail_exit_status_and_bad_stdin(self):
        lines, e = self.run_cli(json.dumps(data([task("ENG-3", "001"), {**STORY, "id": "ENG-9", "description": "", "status": "Canceled"}])))
        self.assertEqual((e.code in (0, None), lines[0], sorted(lines[1:])), (True, "PASS ENG-1 feature", ["PASS ENG-2 story", "PASS ENG-3 task"]))
        lines, e = self.run_cli(json.dumps(data([], "## Not yet specified\n\n- which color?")))
        self.assertEqual(e.code, 1); self.assertRegex(lines[0], r"^FAIL ENG-1 feature: [^;]+; [^;]+; [^;]+$")
        self.assertIn(fc.SYNC_SHAPE, str(self.run_cli("not json")[1]))

    def test_gaps_per_level(self):
        for desc, kw in ((SETTLED.replace("None", "- which color?"), "Not yet specified"), (SETTLED.replace("### Codebase brief", ""), "Codebase brief"), (SETTLED.replace("## Plan", ""), "Plan")):
            ok, level, gaps = check([task("ENG-3", "001")], desc)["ENG-1"]; self.assertEqual((ok, level, len(gaps), has(gaps, kw)), (False, "feature", 1, True), desc)
        root = Path(tempfile.mkdtemp()); (root / "001_test.go").write_text("")
        r = check([task("ENG-3", "001"), task("ENG-4", "002", files="x.go, y.go, z.go"), task("ENG-5", "003", crit="- a\n" * 6), task("ENG-6", "004", files=""), task("ENG-7", "005", protected=""),
                   task("ENG-8", "006", protected="gone_test.go"), {**STORY, "id": "ENG-10"}, {**STORY, "id": "ENG-11", "description": "## Acceptance criteria\n\nTBD"}], root=root)
        self.assertEqual((r["ENG-1"][0], r["ENG-2"][0], r["ENG-3"][:2]), (True, True, (True, "task")))
        for i, *kws in (("ENG-4", "owns 3 files"), ("ENG-5", "Acceptance criteria"), ("ENG-6", "files"), ("ENG-7", "protected"), ("ENG-8", "gone_test.go", "protected"), ("ENG-10", "task"), ("ENG-11", "Acceptance criteria")):
            self.assertTrue(not r[i][0] and has(r[i][2], *kws), (i, r[i]))
        self.assertTrue(check([{**STORY, "id": "ENG-10"}])["ENG-10"][0])  # no issue has parentId: a story needs no task
        self.assertTrue(has(check([task("ENG-3", "001"), task("ENG-4", "002", ["ENG-3"]), task("ENG-5", "003", [{"id": "ENG-4", "title": "T"}])])["ENG-1"][2], "wave"))
        self.assertEqual(fc.file_clashes([{"id": "001", "files": ["a.go"]}, {"id": "002", "files": ["a.go", "b.go"]}, {"id": "003", "files": ["c.go"]}]), {"a.go": ["001", "002"]})

    def test_clash_shows_in_spec_check_and_tasks_and_sync_keeps_parent(self):
        clash = [task("ENG-3", "001", files="a.go"), task("ENG-4", "002", files="a.go"), task("ENG-5", "003", ["ENG-3"], files="b.go")]
        repo, out = Path(tempfile.mkdtemp()), io.StringIO()
        for a in (["init", "-q", "-b", "main"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init"]): subprocess.run(["git", *a], cwd=repo, check=True)
        proj = repo / ".fast-coding" / "p"; proj.mkdir(parents=True); (proj / "linear.json").write_text('{"feature": "ENG-1"}')
        fc.sync_tasks(proj, data(clash, ""))
        with mock.patch.object(fc, "project_dir", return_value=proj), mock.patch("sys.stdout", out): fc.cmd_tasks(SimpleNamespace(repo=str(repo), project="p"))
        self.assertTrue(out.getvalue().endswith(TASKS_TAIL), out.getvalue())
        self.assertEqual(fc.linear_cache(proj)["issues"]["ENG-3"]["parentId"], "ENG-2")
        self.assertTrue(has(check(clash)["ENG-1"][2], "a.go"))
