import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, json, os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock
from pathlib import Path
os.environ.update(COMPOSE_NO_TREEHOUSE="1", HERDR_ENV="")

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_reroute  # noqa: E402  (nothing imports it into `fc` yet; compose.py put bin/ on sys.path)

FILES = ["src/keep.py", "src/new.py", "src/gone.py", "src/a.py", "src/b.py"]


class Signals(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.git("init", "-q", "-b", "main")
        self.write({"src/a.py": "1\n2\n3\n", "src/b.py": "b\n", "src/keep.py": "k\n", "src/gone.py": "p\nq\n"})
        self.commit("base")
        self.git("checkout", "-qb", "task")
        self.write({"src/a.py": "1\n3\nA\nB\n", "src/new.py": "x\ny\nz\n", "docs/outside.txt": "o\n", "assets/logo.png": b"\x00\x01"})
        (self.repo / "src/gone.py").unlink()
        self.commit("task")
        self.git("checkout", "-q", "main")
        self.write({"src/b.py": "b\nmore\n", "other.txt": "1\n2\n3\n4\n5\n"})
        self.commit("base moves on")

    def git(self, *a):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=self.repo, check=True, capture_output=True)

    def commit(self, msg):
        self.git("add", "-A"); self.git("commit", "-qm", msg)

    def write(self, files):
        for name, body in files.items():
            p = self.repo / name; p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(body if isinstance(body, bytes) else body.encode())

    def signals(self, files, branch="task"):
        return fc_reroute.diff_signals(self.repo, {"files": files}, "main", branch)

    def test_changed_lines_outside_and_untouched_come_from_the_three_dot_diff(self):
        got = self.signals(FILES)
        self.assertEqual(set(got), {"changed", "lines", "outside", "untouched"})
        self.assertEqual(got["changed"], [{"path": "assets/logo.png", "added": 0, "deleted": 0}, {"path": "docs/outside.txt", "added": 1, "deleted": 0},
                                          {"path": "src/a.py", "added": 2, "deleted": 1}, {"path": "src/gone.py", "added": 0, "deleted": 2},
                                          {"path": "src/new.py", "added": 3, "deleted": 0}])
        self.assertEqual(got["lines"], 9)
        self.assertEqual(got["outside"], ["assets/logo.png", "docs/outside.txt"])
        self.assertEqual(got["untouched"], ["src/keep.py", "src/b.py"])

    def test_without_files_every_changed_path_is_outside(self):
        got = self.signals([])
        self.assertEqual(got["outside"], [c["path"] for c in got["changed"]])
        self.assertEqual((len(got["outside"]), got["untouched"]), (5, []))

    def test_a_branch_with_no_change_has_no_signals(self):
        self.assertEqual(self.signals(FILES, "main"), {"changed": [], "lines": 0, "outside": [], "untouched": FILES})


class LayerBase(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.git("init", "-q", "-b", "main"); self.git("commit", "-q", "--allow-empty", "-m", "init")
        self.proj = self.repo / ".compose" / "p"
        (self.proj / "results").mkdir(parents=True)
        # stack, bottom to top: 005, 010, 011, 007 (007 is after 011); 020 has a branch but is no synced task, 030 has no branch
        tasks = [{"id": t, "after": after} for t, after in (("005", ""), ("007", "011"), ("010", ""), ("011", "010"), ("030", ""))]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))
        for t in ("005", "007", "010", "011", "020"):
            self.git("branch", self.branch(t), self.git("commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", t))

    def git(self, *a):
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=self.repo, check=True, capture_output=True, text=True).stdout.strip()

    def branch(self, tid):
        return fc.fc_worktree.task_branch(self.repo, self.proj, tid)

    def base(self, tid):
        return fc_reroute.layer_base(self.repo, self.proj, tid, "trunk")

    def test_a_task_gets_the_branch_right_below_it_in_the_stack_order(self):
        self.assertEqual([self.base(t) for t in ("010", "011", "007")], [self.branch(t) for t in ("005", "010", "011")])

    def test_the_bottom_layer_gets_the_trunk(self):
        self.assertEqual(self.base("005"), "trunk")

    def test_a_task_outside_the_stack_gets_the_trunk(self):
        self.assertEqual((self.base("020"), self.base("030")), ("trunk", "trunk"))

    def test_the_results_file_and_its_base_are_not_read(self):
        (self.proj / "results" / "011.json").write_text(json.dumps({"status": "passed", "base": self.branch("005")}))
        (self.proj / "results" / "005.json").write_text("not json")
        self.assertEqual((self.base("011"), self.base("005")), (self.branch("010"), "trunk"))


def _hit(path, *hits):
    return {"symbol": {"path": path}, "hits": [{"path": h} for h in hits]}


class Callers(unittest.TestCase):
    SPANS = {"src/a.py": {"f1": "L1-L3", "f2": "L4-L6", "f3": "L7-L8", "f4": "L9-L10", "f5": "L12-L12"}, "src/c.py": {"g": "L1-L1"}, "src/n.py": {"h": "L1-L1"}, "src/gone.py": {"x": "L1-L1"}}
    CALLERS = {"f1": [_hit("src/a.py", "src/z.py", "src/peer.py", "src/a.py", "src/z.py"), _hit("src/other.py", "src/intruder.py")], "f3": [_hit("src/a.py", "src/y.py", "src/z.py")],
               "g": [_hit("src/c.py", *[f"c/n{i % 25:02}.py" for i in range(50, 0, -1)])]}

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.git("init", "-q", "-b", "main")
        self.write({"src/a.py": "".join(f"l{i}\n" for i in range(1, 13)), "src/c.py": "c\n", "src/n.py": "1\n2\n3\n", "src/gone.py": "p\n"}); self.commit("base")
        self.git("checkout", "-qb", "task")
        self.write({"src/a.py": "l1\nx\n" + "".join(f"l{i}\n" for i in range(3, 9)) + "ins\nl9\nl10\n", "src/c.py": "C\n", "src/n.py": "1\n2\nthree\n"})
        (self.repo / "src/gone.py").unlink(); self.commit("task")
        self.asked = []

    def git(self, *a):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=self.repo, check=True, capture_output=True)

    def commit(self, msg):
        self.git("add", "-A"); self.git("commit", "-qm", msg)

    def write(self, files):
        for name, body in files.items():
            (self.repo / name).parent.mkdir(parents=True, exist_ok=True); (self.repo / name).write_text(body)

    def sh(self, cmd, cwd=None, *a, **kw):
        if cmd[:2] == ["trail", "skeleton"]:
            self.asked.append(cmd[2])
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"entries": [{"name": n, "span": s} for n, s in self.SPANS[cmd[2]].items()]}), "")
        if cmd[:2] == ["trail", "callers"]:
            self.asked.append(cmd[2])
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"matches": self.CALLERS.get(cmd[2], [])}), "")
        return self.real(cmd, cwd, *a, **kw)

    def test_callers_of_the_symbols_whose_span_meets_an_old_side_range(self):
        self.real = fc.fc_core.sh
        with mock.patch.object(fc.fc_core, "sh", self.sh):
            got = fc_reroute.diff_callers(self.repo, "main", "task", {"files": ["src/a.py", "src/c.py", "src/peer.py"]})
        self.assertEqual(got, {"callers": {"src/a.py": ["src/y.py", "src/z.py"], "src/c.py": [f"c/n{i:02}.py" for i in range(20)], "src/n.py": []}})
        self.assertEqual(sorted(a for a in self.asked if not a.startswith("src/")), ["f1", "f3", "f5", "g"])
        self.assertNotIn("src/gone.py", self.asked)


class Unavailable(unittest.TestCase):
    BAD = ["not json", "{}", "[]", '{"entries": [{"name": "f"}]}', '{"matches": [{"hits": []}]}']

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.git("init", "-q", "-b", "main")
        for n in "ac": (self.repo / f"{n}.py").write_text("1\n2\n3\n")
        self.git("add", "-A"); self.git("commit", "-qm", "base"); self.git("checkout", "-qb", "task")
        for n in "ac": (self.repo / f"{n}.py").write_text("1\nx\n3\n")
        self.git("add", "-A"); self.git("commit", "-qm", "task")

    def git(self, *a):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=self.repo, check=True, capture_output=True)

    def run_callers(self, fail=None, how=None):
        """diff_callers with trail faked; call number `fail` (0-based) breaks as `how`. Returns (result, trail calls made)."""
        calls, real = [], fc.fc_core.sh
        def sh(cmd, cwd=None, *a, **kw):
            if cmd[0] != "trail": return real(cmd, cwd, *a, **kw)
            calls.append(cmd)
            body = json.dumps({"entries": [{"name": "f", "span": "L1-L3"}]} if cmd[1] == "skeleton" else {"matches": [{"symbol": {"path": "a.py"}, "hits": [{"path": "z.py"}]}]})
            if len(calls) - 1 != fail: return subprocess.CompletedProcess(cmd, 0, body, "")
            if how == "missing": raise FileNotFoundError("trail")
            return subprocess.CompletedProcess(cmd, how, body, "") if isinstance(how, int) else subprocess.CompletedProcess(cmd, 0, how, "")
        with mock.patch.object(fc.fc_core, "sh", sh):
            return fc_reroute.diff_callers(self.repo, "main", "task", {"files": ["a.py", "c.py"]}), calls

    def test_the_first_failing_call_gives_its_why_and_stops_the_calls(self):
        ok, calls = self.run_callers()
        self.assertEqual(list(ok), ["callers"])
        self.assertGreater(len(calls), 1)
        for n in range(len(calls)):
            for how, why in [("missing", "trail not installed"), (1, "trail exited 1"), (127, "trail exited 127")] + [(b, "trail gave unreadable output") for b in self.BAD]:
                with self.subTest(call=n, how=how):
                    got, made = self.run_callers(n, how)
                    self.assertEqual(got, {"unavailable": why})
                    self.assertEqual(len(made), n + 1)


class Fired(unittest.TestCase):
    QUERY = "query($id: String!, $after: String) { issue(id: $id) { comments(first: 100, after: $after) { pageInfo { hasNextPage endCursor } nodes { body } } } }"

    @staticmethod
    def page(*bodies, cursor=None):
        return {"issue": {"comments": {"pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor}, "nodes": [{"body": b} for b in bodies]}}}

    def fired(self, *pages):
        with mock.patch.object(fc.fc_linear, "linear_gql", side_effect=list(pages)) as gql:
            return fc_reroute.fired("XX-2"), gql.call_args_list

    def test_every_page_is_read_with_the_previous_cursor_and_each_trigger_gives_a_pair(self):
        got, calls = self.fired(self.page("* rerouted: diff (run aaaaaaaaaaaa)", cursor="c1"), self.page("## Route\n\n* rerouted: diff, scope (run bbbbbbbbbbbb)", cursor="c2"), self.page())
        self.assertEqual(got, {("diff", "aaaaaaaaaaaa"), ("diff", "bbbbbbbbbbbb"), ("scope", "bbbbbbbbbbbb")})
        self.assertEqual([c.args for c in calls], [(self.QUERY, {"id": "XX-2", "after": a}) for a in (None, "c1", "c2")])

    def test_dash_and_star_bullets_count_on_any_stripped_line_and_other_lines_give_none(self):
        got, calls = self.fired(self.page("intro\n  - rerouted: scope (run r1)  \n\t* rerouted: diff (run r2)\n- rerouted: diff (run r2)", "no bullet\nrerouted: diff (run r3)\n* rerouted: diff\n* routed: diff (run r4)\n* rerouted: diff (run r5) extra", ""))
        self.assertEqual((got, len(calls)), ({("scope", "r1"), ("diff", "r2")}, 1))

    def test_a_null_issue_raises_and_a_linear_error_propagates(self):
        with self.assertRaisesRegex(RuntimeError, "no issue XX-2"):
            self.fired({"issue": None})
        with self.assertRaisesRegex(RuntimeError, "Linear: boom"):
            self.fired(self.page("* rerouted: diff (run r1)", cursor="c1"), RuntimeError("Linear: boom"))
