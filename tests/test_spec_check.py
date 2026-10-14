import importlib.machinery, importlib.util, io, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
os.environ["FAST_CODING_NO_TREEHOUSE"] = "1"

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding")))
fc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fc)

SETTLED = "## Not yet specified\n\nNone\n\n### Codebase brief\n\nWhere things live.\n\n## Plan\n\nThe plan."
STORY = {"id": "ENG-2", "title": "Story", "description": "## Acceptance criteria\n\n* it works", "status": "Todo", "blockedBy": []}
# What `fast-coding tasks` printed before file_clashes was pulled out of it.
TASKS_OUT = """project p   3 tasks   stack order (bottom first): 001 <- 002 <- 003
  id   title                                    after      linear    files | protected | test
  001  T                                        -          ENG-3     a.go | 001_test.go | t
  002  T                                        -          ENG-4     a.go | 002_test.go | t
  003  T                                        001        ENG-5     b.go | 003_test.go | t

  WARNING two tasks own the same file (they must be one task, or one must be `after:` the other):
    a.go: 001, 002

  run waves (each wave in parallel): 001, 002  then  003

  WARNING SERIAL CHAIN: 3 tasks run in 2 waves, mostly one after another. Keep an `after:` (blocked-by) only where a task needs another task's code or file; stack order for review comes from ids, not from `after:`.
"""


def task(ident, tid, blocked_by=(), crit="- works", **kv):
    kv = {"id": tid, "files": f"{tid}.go", "protected": f"{tid}_test.go", "test": "t", **kv}
    desc = f"## Acceptance criteria\n{crit}\n\n```fast-coding\n" + "\n".join(f"{k}: {v}" for k, v in kv.items()) + "\n```\n"
    return {"id": ident, "title": "T", "description": desc, "status": "Todo", "blockedBy": list(blocked_by), "parentId": "ENG-2"}


def data(issues, desc=SETTLED):
    return {"feature": {"id": "ENG-1", "title": "F", "description": desc}, "issues": [STORY, *issues]}


def check(issues, desc=SETTLED, root=None):
    return {i: (ok, level, gaps) for ok, i, level, gaps in fc.spec_check(data(issues, desc), root)}


def has(gaps, *kws):
    return any(k in g for g in gaps for k in kws)


class SpecCheck(unittest.TestCase):
    def run_cli(self, stdin=None, **kw):
        """The printed lines and the SystemExit (SystemExit(0) when it returns normally); no stdin reads the synced cache."""
        with mock.patch.object(fc.sys, "stdin", io.StringIO(stdin or "")), mock.patch("sys.stdout", io.StringIO()) as out:
            try:
                fc.cmd_spec_check(SimpleNamespace(**{"repo": ".", "project": None, **kw}, stdin=stdin is not None))
            except SystemExit as e:
                return out.getvalue().splitlines(), e
        return out.getvalue().splitlines(), SystemExit(0)

    def test_settled_feature_prints_only_pass_and_skips_canceled_issues(self):
        canceled = {**STORY, "id": "ENG-9", "description": "", "status": "Canceled"}
        lines, e = self.run_cli(json.dumps(data([task("ENG-3", "001"), canceled])))
        self.assertIn(e.code, (0, None))
        self.assertEqual(lines[0], "PASS ENG-1 feature")
        self.assertEqual(sorted(lines[1:]), ["PASS ENG-2 story", "PASS ENG-3 task"])

    def test_fail_line_exits_1_and_bad_stdin_names_the_shape(self):
        lines, e = self.run_cli(json.dumps(data([], "## Not yet specified\n\n- which color?")))
        self.assertEqual(e.code, 1)
        self.assertRegex(lines[0], r"^FAIL ENG-1 feature: [^;]+; [^;]+; [^;]+$")
        self.assertIn(fc.SYNC_SHAPE, str(self.run_cli("not json")[1]))

    def test_command_line_registers_spec_check(self):
        def cli(desc):
            return subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "bin" / "fast-coding"), "spec-check", "--stdin"],
                                  input=json.dumps(data([task("ENG-3", "001")], desc)), capture_output=True, text=True, env={**os.environ, "FAST_CODING_NO_TREEHOUSE": "1"})
        ok, bad = cli(SETTLED), cli("## Not yet specified\n\n- which color?")
        self.assertEqual((ok.returncode, ok.stdout.partition("\n")[0]), (0, "PASS ENG-1 feature"), ok.stderr)
        self.assertEqual(bad.returncode, 1, bad.stderr)
        self.assertTrue(bad.stdout.startswith("FAIL ENG-1 feature"), bad.stdout)

    def test_each_feature_gap_alone(self):
        for desc, kw in ((SETTLED.replace("None", "- which color?"), "Not yet specified"),
                         (SETTLED.replace("### Codebase brief", ""), "Codebase brief"),
                         (SETTLED.replace("## Plan", ""), "Plan")):
            ok, level, gaps = check([task("ENG-3", "001")], desc)["ENG-1"]
            self.assertEqual((ok, level, len(gaps), has(gaps, kw)), (False, "feature", 1, True), desc)

    def test_tasks_chained_by_blocked_by_may_share_a_file(self):
        issues = [task("ENG-3", "001", files="a.go"), task("ENG-4", "002", ["ENG-3"], files="a.go"), task("ENG-5", "003", ["ENG-4"], files="a.go")]
        self.assertFalse(has(check(issues)["ENG-1"][2], "a.go"))

    def test_story_and_task_gaps(self):
        root = Path(tempfile.mkdtemp())
        (root / "001_test.go").write_text("")
        r = check([task("ENG-3", "001"), task("ENG-4", "002", files="x.go, y.go, z.go"), task("ENG-5", "003", crit="- a\n" * 6),
                   task("ENG-6", "004", files=""), task("ENG-7", "005", protected=""), task("ENG-8", "006", protected="gone_test.go"),
                   {**STORY, "id": "ENG-10"}, {**STORY, "id": "ENG-11", "description": "## Acceptance criteria\n\nTBD"}], root=root)
        self.assertEqual((r["ENG-1"][0], r["ENG-2"][0], r["ENG-3"][:2]), (True, True, (True, "task")))
        for i, *kws in (("ENG-4", "owns 3 files"), ("ENG-5", "Acceptance criteria"), ("ENG-6", "files"), ("ENG-7", "protected"),
                        ("ENG-8", "gone_test.go", "protected"), ("ENG-10", "task"), ("ENG-11", "Acceptance criteria")):
            self.assertTrue(not r[i][0] and has(r[i][2], *kws), (i, r[i]))
        self.assertTrue(check([{**STORY, "id": "ENG-10"}])["ENG-10"][0])  # no issue has parentId: a story needs no task
        bare, marked = {**STORY, "id": "ENG-12"}, {**STORY, "id": "ENG-13", "description": STORY["description"] + "\n\nGroundwork: dependency bump"}
        r = check([task("ENG-3", "001"), bare, marked])
        self.assertTrue(not r["ENG-12"][0] and has(r["ENG-12"][2], "Groundwork"), r["ENG-12"])
        self.assertTrue(r["ENG-13"][0], r["ENG-13"])

    def test_criteria_fold_nested_bullets_and_continuations(self):
        parse = lambda body: fc.parse_criteria("## Acceptance criteria\n" + body)
        self.assertEqual(parse("- a\n* b\n"), ["a", "b"])
        for pad in ("  ", "    "):
            self.assertEqual(parse(f"* Sheet shows one example per role:\n{pad}* primary\n{pad}* ghost\n* other"),
                             ["Sheet shows one example per role: primary; ghost", "other"])
        self.assertEqual(parse("* wraps onto\n  a second line\n* next"), ["wraps onto a second line", "next"])
        self.assertEqual(parse("  - indented base\n  - same level\n    - child"), ["indented base", "same level; child"])

    def test_size_lint_counts_top_level_bullets_only(self):
        sub = "".join(f"  * s{n}\n" for n in range(6))
        self.assertFalse(has(check([task("ENG-3", "001", crit=f"* parent:\n{sub}* two")])["ENG-3"][2], "Acceptance criteria"))

    def test_serial_chain_and_file_clashes(self):
        chain = [task("ENG-3", "001"), task("ENG-4", "002", ["ENG-3"]), task("ENG-5", "003", [{"id": "ENG-4", "title": "T"}])]
        self.assertTrue(has(check(chain)["ENG-1"][2], "wave"))
        self.assertEqual(fc.file_clashes([]), {})
        tasks = [{"id": "001", "files": ["a.go"]}, {"id": "002", "files": ["a.go", "b.go"]}, {"id": "003", "files": ["c.go"]}]
        self.assertEqual(fc.file_clashes(tasks), {"a.go": ["001", "002"]})
        two = [task("ENG-3", "001", files="a.go"), task("ENG-4", "002", files="a.go"),
               task("ENG-5", "003", files="b.go"), task("ENG-6", "004", files="b.go")]
        g, = [g for g in check(two)["ENG-1"][2] if "a.go" in g]
        self.assertTrue("a.go: 001, 002" in g and "b.go: 003, 004" in g, g)
        self.assertEqual(g.count(g[:min(g.index("a.go"), g.index("b.go"))]), 1, g)  # the explanation leads, once

    def test_shared_file_in_spec_check_and_tasks_and_sync_keeps_parent(self):
        clash = [task("ENG-3", "001", files="a.go"), task("ENG-4", "002", files="a.go"), task("ENG-5", "003", ["ENG-3"], files="b.go")]
        repo = Path(tempfile.mkdtemp())
        for a in (["init", "-q", "-b", "main"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init"]):
            subprocess.run(["git", *a], cwd=repo, check=True)
        proj = repo / ".fast-coding" / "p"
        proj.mkdir(parents=True)
        (proj / "linear.json").write_text('{"feature": "ENG-1"}')
        fc.sync_tasks(proj, data(clash, ""))
        out = io.StringIO()
        with mock.patch.object(fc, "project_dir", return_value=proj), mock.patch("sys.stdout", out):
            fc.cmd_tasks(SimpleNamespace(repo=str(repo), project="p"))
        self.assertEqual(out.getvalue(), TASKS_OUT)
        self.assertEqual(fc.linear_cache(proj)["issues"]["ENG-3"]["parentId"], "ENG-2")
        self.assertTrue(has(check(clash)["ENG-1"][2], "a.go"))

    def test_unsynced_project_stops_with_the_sync_message(self):
        repo = Path(tempfile.mkdtemp())
        proj = repo / ".fast-coding" / "p"
        proj.mkdir(parents=True)
        with mock.patch.object(fc, "project_dir", return_value=proj), mock.patch.object(fc, "project_worktree", return_value=repo):
            lines, e = self.run_cli(repo=str(repo), project="p")
        self.assertIn("no tasks synced for p", str(e))
        self.assertIn("fast-coding sync", str(e))

    def test_synced_cache_prints_what_stdin_prints(self):
        d = data([task("ENG-3", "001"), {**STORY, "id": "ENG-11", "description": "TBD"}])
        repo = Path(tempfile.mkdtemp())
        (repo / "001_test.go").write_text("")
        proj = repo / ".fast-coding" / "p"
        proj.mkdir(parents=True)
        (proj / "linear.json").write_text('{"feature": "ENG-1"}')
        fc.sync_tasks(proj, d)
        with mock.patch.object(fc, "project_dir", return_value=proj), mock.patch.object(fc, "project_worktree", return_value=repo):
            lines, e = self.run_cli(repo=str(repo), project="p")
        want, we = self.run_cli(json.dumps(d))
        self.assertTrue(any(l.startswith("FAIL ENG-11") for l in want), want)
        self.assertEqual((lines, e.code), (want, we.code))
