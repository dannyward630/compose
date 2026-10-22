import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, io, json, os, subprocess, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import sys
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_ledger, fc_tierspend  # noqa: E402


class DoneEvidence(unittest.TestCase):
    def setUp(self):
        self.proj, self.repo = Path(tempfile.mkdtemp()) / "feat", Path(tempfile.mkdtemp())
        (self.proj / "results").mkdir(parents=True)
        git = lambda *args: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()
        git("init", "-q", "-b", "main"); (self.repo / "a.py").write_text("1\n"); git("add", "-A"); git("commit", "-q", "-m", "a")
        git("branch", "task-021"); self.tip = git("rev-parse", "task-021")
        (self.proj / "verify.json").write_text('{"task_prefix": "task-"}')
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"tasks": [{"id": "021", "title": "a", "linear": "ENG-4"}, {"id": "022", "title": "b", "linear": "ENG-5"}, {"id": "023", "title": "c"}]}))
        self.calls = mock.Mock()
        for mod, name, kw in ((fc.fc_core, "project_dir", {"return_value": self.proj}), (fc_ledger, "run_id", {"side_effect": lambda proj, tid: "run-" + tid}),
                              (fc_ledger, "criterion_ids", {"side_effect": lambda meta: [meta["id"] + ".1:x"]}), (fc_ledger, "event", {"side_effect": lambda *a: a}),
                              (fc_ledger, "record", {"return_value": True}), (fc_ledger, "record_task", {"return_value": True}), (fc.fc_linear, "linear_event", {})):
            p = mock.patch.object(mod, name, **kw); self.calls.attach_mock(p.start(), name); self.addCleanup(p.stop)

    def done(self, only):
        out = io.StringIO()
        with redirect_stdout(out):
            fc.fc_status.cmd_done(SimpleNamespace(repo=str(self.repo), only=only, note="by hand"))
        return out.getvalue()

    def recorded(self):
        """(issue, events) per write, in call order: `record(issue, events)` or `record_task(repo, proj, meta, events)`."""
        return [c[1] if c[0] == "record" else (c[1][2].get("linear"), c[1][3]) for c in self.calls.mock_calls if c[0] in ("record", "record_task")]

    def test_each_task_records_one_done_event_on_its_own_issue(self):
        (self.proj / "results" / "021.json").write_text('{"branch": "task-021"}')
        self.done("021,022,023")
        done = lambda tid, sha: [(f"run-{tid}", sha, [tid], [f"{tid}.1:x"], "done", "done", "pass", None, "hand done: by hand")]
        self.assertEqual(self.recorded(), [("ENG-4", done("021", self.tip)), ("ENG-5", done("022", "")), (None, done("023", ""))])

    def test_the_write_is_recorded_once_beside_the_hand_done_linear_event(self):
        self.done("021")
        names = [c[0] for c in self.calls.mock_calls if c[0] in ("linear_event", "record", "record_task")]
        self.assertIn(names, (["linear_event", "record"], ["record_task", "linear_event"]))

    def test_unknown_id_records_nothing_and_writes_no_result(self):
        out = self.done("999")
        self.assertEqual((out, self.recorded(), list((self.proj / "results").glob("999.json"))), ("999: no such task (run `compose sync` if it is new on Linear)\n", [], []))


class TestTiers(unittest.TestCase):
    """`status` prints the tier pins and the spend per tier right after the route cost lines."""

    def setUp(self):
        env = mock.patch.dict(os.environ, {"HERDR_ENV": "", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
        env.start(); self.addCleanup(env.stop)
        self.repo = Path(tempfile.mkdtemp())
        for a in (("init", "-q", "-b", "main"), ("commit", "-q", "--allow-empty", "-m", "init"), ("checkout", "-q", "-b", "compose/p")):
            subprocess.run(["git", *a], cwd=self.repo, check=True, capture_output=True)
        self.proj = self.repo / ".compose" / "p"
        (self.proj / "results").mkdir(parents=True)
        (self.proj / "verify.json").write_text(json.dumps({"task_prefix": "compose/p-"}))
        (self.repo / ".git" / "info" / "exclude").write_text("/.compose/\n")
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": [{"id": "001", "title": "a"}]}))

    def status(self):
        return fc.fc_status.render_status(self.repo, [self.proj]).split("\n")

    def test_pins_then_spend_close_the_project_block_after_the_route_cost_lines(self):
        (self.proj / "results" / "tier.json").write_text(json.dumps({"project": "no-frontier", "stories": {"NEB-9": "cheap"}}))
        with mock.patch.object(fc.fc_budget, "limit", return_value=40.0), mock.patch.object(fc_tierspend, "lines", return_value=["  spend header", "  spend row"]) as spend:
            lines = self.status()
        self.assertEqual(lines[-4:], ["  tier pins  project no-frontier, NEB-9 cheap", "  spend header", "  spend row", ""])
        self.assertTrue(lines[-5].startswith("  depth "), lines)
        self.assertTrue(any(l.startswith("  route cost ") for l in lines[:-5]), lines)
        spend.assert_called_once_with(self.proj, 40.0)

    def test_spend_alone_prints_without_a_pins_line(self):
        with mock.patch.object(fc_tierspend, "lines", return_value=["  spend header"]):
            lines = self.status()
        self.assertEqual(lines[-2:], ["  spend header", ""])
        self.assertFalse(any("tier pins" in l for l in lines), lines)

    def test_a_frontier_result_shows_the_header_and_the_default_limit(self):
        (self.proj / "results" / "001.json").write_text(json.dumps({"id": "001", "status": "passed", "model": "claude:claude-opus-5-5", "cost": 0.0, "reference_cost": 0.5}))
        lines = self.status()
        header = f"  {'tier spend':12} {'real $':>9} {'ref $':>9}"
        self.assertIn(header, lines)
        at = lines.index(header)
        frontier = [l for l in lines[at:] if l.startswith("  frontier")]
        self.assertEqual(len(frontier), 1, lines)
        self.assertTrue(frontier[0].endswith("  limit 25.00"), frontier)
        self.assertFalse(any("tier pins" in l for l in lines), lines)

    def test_no_pins_and_no_spend_print_neither_line(self):
        self.assertFalse(any("tier pins" in l or "tier spend" in l for l in self.status()))


class StackNote(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp()).resolve()
        self.git("init", "-q", "-b", "main"); (self.repo / "a").write_text("1\n"); self.git("add", "-A"); self.git("commit", "-qm", "a")
        self.git("checkout", "-q", "-b", "compose/p")
        self.proj = self.repo / ".compose" / "p"; (self.proj / "results").mkdir(parents=True)
        (self.repo / ".git" / "info" / "exclude").write_text("/.compose/\n")
        (self.proj / "verify.json").write_text(json.dumps({"review_base": "main"}))
        (self.proj / "results" / "verify.json").write_text(json.dumps({"passed": True}))
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": [{"id": t, "title": f"Build {t}", "after": ""} for t in ("001", "002", "003")]}))
        for t in ("001", "002", "003"):
            self.git("checkout", "-q", "-b", f"compose/p-{t}", "compose/p"); (self.repo / f"{t}.src").write_text("c\n"); self.git("add", "-A"); self.git("commit", "-qm", t); self.git("checkout", "-q", "compose/p")
            (self.proj / "results" / f"{t}.json").write_text(json.dumps({"status": "passed", "model": "pi:p/m"}))
        for n in ("01", "02", "03"):
            self.git("branch", f"compose/p-layer-{n}", "compose/p-003")
        (self.proj / "layers.json").write_text(json.dumps({"compose/p-layer-01": ["groundwork"], "compose/p-layer-02": ["001", "002"], "compose/p-layer-03": ["003"]}))
        (self.proj / "results" / "prs.json").write_text(json.dumps({"compose/p-layer-01": 1, "compose/p-layer-02": 2}))

    def git(self, *a):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def render(self):
        lines = fc.fc_status.render_status(self.repo, [self.proj]).splitlines()
        return {l.split()[0]: l for l in lines if l.startswith("  00")}, lines[0]

    def test_submitted_layers_show_their_pr_and_the_project_line_counts_them(self):
        rows, head = self.render()
        self.assertTrue(rows["001"].endswith("compose/p-001  layer 2  PR #2") and rows["002"].endswith("compose/p-002  layer 2  PR #2"))
        self.assertTrue(rows["003"].endswith("compose/p-003  layer 3"))
        self.assertRegex(head, r"verify PASS .* at \d\d:\d\d  stack 2/3 submitted")

    def test_a_submitted_task_without_a_branch_keeps_its_layer_and_pr(self):
        self.git("branch", "-D", "compose/p-002")
        self.assertTrue(self.render()[0]["002"].endswith("layer 2  PR #2"))

    def test_missing_records_leave_the_notes_and_no_layer_branches_leave_no_stack_text(self):
        for gone, stack in (("prs.json", "stack 0/3 submitted"), ("layers.json", "stack 2/3 submitted")):
            for p in (self.proj / gone, self.proj / "results" / gone):
                if p.exists(): p.rename(p.with_suffix(".bak"))
            rows, head = self.render()
            self.assertTrue(rows["001"].endswith("compose/p-001  layer 1") and rows["003"].endswith("compose/p-003  layer 3") and stack in head, gone)
            for p in list(self.proj.glob("*.bak")) + list((self.proj / "results").glob("*.bak")): p.rename(p.with_suffix(".json"))
        for n in ("01", "02", "03"): self.git("branch", "-D", f"compose/p-layer-{n}")
        self.assertNotIn("stack", self.render()[1])
