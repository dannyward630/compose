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


class JevState(unittest.TestCase):
    ROUTE = "## Route\n\n* workflow: implement-then-test\n* depth: STANDARD\n* verification requirements: make lint, make e2e\n\n"
    CALLERS = {"callers": {"src/greet.py": ["src/app.py"]}}
    ANS = {"depth": {"choice": "FAST", "probabilities": {"FAST": 0.9}, "confidence": 0.9}, "policy0": {"choice": "DOES_NOT_APPLY", "probabilities": {"DOES_NOT_APPLY": 0.9}, "confidence": 0.9}}
    DOCS = {"name": "Docs", "statement": "Docs stay true.", "globs": ["docs/*"], "checks": ["make docs"]}
    PLAIN = {"name": "Keys", "statement": "Keys are checked.", "globs": [], "checks": ["make keys"]}

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.proj = self.repo / ".compose" / "p"
        (self.proj / "results").mkdir(parents=True)
        (self.proj / "linear.json").write_text('{"feature": "ENG-1"}')
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=self.repo, check=True, capture_output=True)
        git("init", "-q", "-b", "main"); git("commit", "-q", "--allow-empty", "-m", "base"); git("checkout", "-qb", "task")
        for f in ("docs/note.md", "src/greet.py"): (self.repo / f).parent.mkdir(exist_ok=True); (self.repo / f).write_text("n\n")
        git("add", "-A"); git("commit", "-qm", "task")

    def reassess(self, route=ROUTE, jev=None, policies=()):
        """Reassess the synced task whose recorded route is `route`; Jev replies `jev` (raised when an exception), `policies` is what read_policies gives."""
        desc = f"## Goal\nGreet.\n\n## Acceptance criteria\n* greets\n\n{route}```compose\nid: 001\ntest: t\nfiles: src/greet.py\n```\n"
        tasks = fc.fc_tasks.sync_tasks(self.proj, {"feature": {"id": "ENG-1"}, "issues": [{"id": "ENG-2", "title": "Greet", "description": desc, "status": "Todo"}]})
        kv = lambda v, d: {"side_effect" if isinstance(v, Exception) else "return_value": v or d}
        with mock.patch.object(fc.fc_models, "jev_ask", **kv(jev, {"model": "jev-test", "answers": self.ANS})) as self.ask, \
                mock.patch.object(importlib.import_module("fc_policy"), "read_policies", **kv(policies, ([], ""))), mock.patch.object(fc_reroute, "diff_callers", return_value=self.CALLERS):
            return fc_reroute.reassess(self.repo, self.proj, tasks[0], tasks, ("diff", "scope"), "r1", "main", "task")

    def test_jev_sees_the_diff_callers_recorded_route_and_triggers_and_is_not_asked_for_the_workflow(self):
        route = self.reassess(policies=([self.DOCS, self.PLAIN], ""))
        state, questions = self.ask.call_args.args[2:4]
        signals = fc_reroute.diff_signals(self.repo, {"files": ["src/greet.py"]}, "main", "task")
        self.assertEqual(signals["outside"], ["docs/note.md"])
        self.assertEqual(state["diff"], {**signals, **self.CALLERS})
        self.assertEqual(state["recorded"], {"workflow": "implement-then-test", "depth": "STANDARD", "checks": ["make lint", "make e2e"]})
        self.assertEqual((state["triggers"], state["pin"], state["task"]), (["diff", "scope"], "implement-then-test", "Greet"))
        self.assertEqual(("workflow" in questions, "Keys are checked." in json.dumps(questions), "Docs stay true." in json.dumps(questions)), (False, True, False))
        self.assertEqual((self.ask.call_count, route["workflow"]), (1, "implement-then-test"))

    def test_a_policy_matching_a_changed_path_outside_files_floors_deep_with_its_checks(self):
        route = self.reassess(policies=([self.DOCS, self.PLAIN, {**self.DOCS, "name": "Bin", "globs": ["bin/*"], "checks": ["make bin"]}], ""))
        self.assertEqual((route["depth"], route["checks"]), ("DEEP", ["make docs"]))
        self.assertEqual(self.reassess(policies=([self.PLAIN], ""))["depth"], "FAST")

    def test_without_a_recorded_workflow_the_pin_is_test_first_and_none_means_no_checks(self):
        route = self.reassess("## Route\n\n* depth: FAST\n* verification requirements: none\n\n")
        state, questions = self.ask.call_args.args[2:4]
        self.assertEqual((state["recorded"], state["pin"], route["workflow"], "workflow" in questions), ({"workflow": None, "depth": "FAST", "checks": []}, "test-first", "test-first", False))
        self.reassess("")
        self.assertEqual(self.ask.call_args.args[2]["recorded"], {"workflow": None, "depth": None, "checks": []})

    def test_jev_unavailable_is_the_standard_fallback_on_the_recorded_workflow(self):
        route = self.reassess(jev=RuntimeError("no key"))
        self.assertEqual((route["depth"], route["workflow"], route["confidence"]), ("STANDARD", "implement-then-test", None))

    def test_unreadable_policies_stop_before_jev_and_payment_required_propagates(self):
        with self.assertRaisesRegex(RuntimeError, "policies unreadable: boom"):
            self.reassess(policies=RuntimeError("policies unreadable: boom"))
        self.assertEqual(self.ask.call_count, 0)
        with self.assertRaises(fc.fc_models.PaymentRequired):
            self.reassess(jev=fc.fc_models.PaymentRequired("typesafe", "top up"))


class Floor(unittest.TestCase):
    DOCS = {"name": "Docs", "statement": "Docs stay true.", "globs": ["docs/*"], "checks": ["make e2e", "make docs"]}
    KEPT = "; depth DEEP kept from the recorded route"

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.proj = self.repo / ".compose" / "p"
        (self.proj / "results").mkdir(parents=True)
        (self.proj / "linear.json").write_text('{"feature": "ENG-1"}')
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=self.repo, check=True, capture_output=True)
        git("init", "-q", "-b", "main"); git("commit", "-q", "--allow-empty", "-m", "base"); git("checkout", "-qb", "task")
        for f in ("docs/note.md", "src/greet.py"): (self.repo / f).parent.mkdir(exist_ok=True); (self.repo / f).write_text("n\n")
        git("add", "-A"); git("commit", "-qm", "task")

    def route(self, recorded="DEEP", jev="FAST", checks="make lint, make e2e", policies=(), triggers=("diff",)):
        """The route reassess returns for a recorded `recorded` depth and checks, Jev answering depth `jev` (or raising) and `policies`."""
        bullet = f"* depth: {recorded}\n" if recorded else ""
        desc = f"## Goal\nGreet.\n\n## Acceptance criteria\n* greets\n\n## Route\n\n* workflow: implement-then-test\n{bullet}* verification requirements: {checks}\n\n```compose\nid: 001\ntest: t\nfiles: src/greet.py\n```\n"
        tasks = fc.fc_tasks.sync_tasks(self.proj, {"feature": {"id": "ENG-1"}, "issues": [{"id": "ENG-2", "title": "Greet", "description": desc, "status": "Todo"}]})
        reply = jev if isinstance(jev, Exception) else {"model": "jev-test", "answers": {"depth": {"choice": jev, "probabilities": {jev: 0.9}, "confidence": 0.9}}}
        with mock.patch.object(fc.fc_models, "jev_ask", **{"side_effect" if isinstance(jev, Exception) else "return_value": reply}), mock.patch.object(fc_reroute, "diff_callers", return_value={"callers": {}}), \
                mock.patch.object(importlib.import_module("fc_policy"), "read_policies", return_value=(list(policies), "")), mock.patch.object(importlib.import_module("fc_route"), "record_route"), \
                mock.patch.object(fc.fc_linear, "linear_gql", return_value={}):
            return fc_reroute.reassess(self.repo, self.proj, tasks[0], tasks, list(triggers), "3f9a0c1b2d4e", "main", "task")

    def test_the_depth_is_the_higher_of_jevs_and_the_recorded_and_the_note_says_when_the_recorded_won(self):
        for recorded, jev, depth, kept in [("DEEP", "FAST", "DEEP", True), ("DEEP", "STANDARD", "DEEP", True), ("STANDARD", "FAST", "STANDARD", True), ("STANDARD", "DEEP", "DEEP", False),
                                           ("FAST", "STANDARD", "STANDARD", False), ("STANDARD", "STANDARD", "STANDARD", False), ("DEEP", "DEEP", "DEEP", False)]:
            with self.subTest(recorded=recorded, jev=jev):
                got = self.route(recorded, jev, triggers=("diff", "scope"))
                self.assertEqual(got["depth"], depth)
                self.assertEqual(got["note"], "rerouted after diff, scope (run 3f9a0c1b2d4e)" + (f"; depth {recorded} kept from the recorded route" if kept else ""))

    def test_a_missing_or_unknown_recorded_depth_is_ignored(self):
        for recorded in ("", "ULTRA"):
            got = self.route(recorded, "FAST")
            self.assertEqual((got["depth"], got["note"]), ("FAST", "rerouted after diff (run 3f9a0c1b2d4e)"))

    def test_with_jev_unavailable_the_depth_is_standard_unless_the_recorded_is_higher(self):
        got = [self.route(r, RuntimeError("no key")) for r in ("FAST", "STANDARD", "DEEP")]
        self.assertEqual([g["depth"] for g in got], ["STANDARD"] * 2 + ["DEEP"])
        self.assertEqual([g["note"].endswith(self.KEPT) for g in got], [False, False, True])

    def test_checks_keep_the_recorded_first_then_add_new_ones_once_each(self):
        self.assertEqual(self.route(policies=[self.DOCS])["checks"], ["make lint", "make e2e", "make docs"])
        self.assertEqual(self.route(checks="none", policies=[self.DOCS])["checks"], ["make e2e", "make docs"])
        self.assertEqual(self.route(jev=RuntimeError("no key"))["checks"], ["make lint", "make e2e"])


class Record(unittest.TestCase):
    HASH = "0123456789abcdef"

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.proj = self.repo / ".compose" / "p"
        (self.proj / "results").mkdir(parents=True)
        (self.proj / "linear.json").write_text('{"feature": "ENG-1"}')
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=self.repo, check=True, capture_output=True)
        git("init", "-q", "-b", "main"); git("commit", "-q", "--allow-empty", "-m", "base"); git("checkout", "-qb", "task")
        (self.repo / "a.py").write_text("n\n"); git("add", "-A"); git("commit", "-qm", "task")

    def reassess(self, triggers=("diff",), **record):
        """Reassess a synced task with a recorded route; returns (route, record_route mock, context_hash mock, the policies read_policies gave)."""
        desc = "## Goal\nGreet.\n\n## Acceptance criteria\n* greets\n\n## Route\n\n* workflow: implement-then-test\n* depth: STANDARD\n* verification requirements: make lint\n\n```compose\nid: 001\ntest: t\nfiles: a.py\n```\n"
        tasks = fc.fc_tasks.sync_tasks(self.proj, {"feature": {"id": "ENG-1"}, "issues": [{"id": "ENG-2", "title": "Greet", "description": desc, "status": "Todo"}]})
        self.meta, policies = tasks[0], [{"name": "Keys", "statement": "Keys are checked.", "globs": [], "checks": ["make keys"]}]
        reply = {"model": "jev-test", "answers": {"depth": {"choice": "DEEP", "probabilities": {"DEEP": 0.9}, "confidence": 0.9}}}
        with mock.patch.object(fc.fc_models, "jev_ask", return_value=reply), mock.patch.object(fc_reroute, "diff_callers", return_value={"callers": {}}), \
                mock.patch.object(importlib.import_module("fc_policy"), "read_policies", return_value=(policies, "")), mock.patch.object(fc.fc_linear, "linear_gql", return_value={}), \
                mock.patch.object(importlib.import_module("fc_routectx"), "context_hash", return_value=self.HASH) as ctx, mock.patch.object(importlib.import_module("fc_route"), "record_route", **record) as rec:
            return fc_reroute.reassess(self.repo, self.proj, self.meta, tasks, list(triggers), "3f9a0c1b2d4e", "main", "task"), rec, ctx, policies

    def test_the_route_is_hashed_with_the_policies_and_its_reason_ends_with_the_note(self):
        route, rec, ctx, policies = self.reassess()
        self.assertEqual((route["hash"], ctx.call_args.args), (self.HASH, (self.repo, self.meta, policies)))
        self.assertTrue(route["note"].startswith("rerouted after diff") and route["reason"].endswith(route["note"]))

    def test_the_section_is_the_route_section_then_the_rerouted_bullet_with_every_trigger_and_the_run_id(self):
        route, rec, _, _ = self.reassess(("diff", "scope"))
        proj, meta, section = rec.call_args.args
        self.assertEqual((rec.call_count, proj, meta), (1, self.proj, self.meta))
        self.assertEqual(section, importlib.import_module("fc_routerec").route_section(route) + "\n* rerouted: diff, scope (run 3f9a0c1b2d4e)")
        self.assertTrue(section.endswith(f"\n* context hash: {self.HASH}\n* rerouted: diff, scope (run 3f9a0c1b2d4e)"))

    def test_a_record_that_fails_raises(self):
        with self.assertRaisesRegex(RuntimeError, "Linear: down"):
            self.reassess(side_effect=RuntimeError("Linear: down"))


class Sweep(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.proj = self.repo / ".compose" / "p"
        (self.proj / "results").mkdir(parents=True)
        # 001, 005 and 006 passed with an issue; 002 failed, 003 has no result file, 004 has no issue
        self.tasks = [{"id": t, **({} if t == "004" else {"linear": f"XX-{t}"})} for t in ("001", "002", "003", "004", "005", "006")]
        for t, status in (("001", "passed"), ("002", "failed"), ("004", "passed"), ("005", "passed"), ("006", "passed")):
            (self.proj / "results" / f"{t}.json").write_text(json.dumps({"id": t, "status": status}))

    def sweep(self, ids=("001", "002", "003", "004", "005", "006"), key="lin_test", kinds=("diff",), reassess=None, run_id=lambda proj, t: f"run-{t}"):
        """catch_up with `reassess` mocked; returns (its return value, the mock)."""
        with mock.patch.object(fc.fc_config, "LINEAR_KEY", key), mock.patch.object(fc_reroute, "reassess", **reassess or {}) as re, mock.patch.object(fc_reroute, "fired", return_value=set()), \
                mock.patch.object(fc_reroute, "layer_base", side_effect=lambda repo, proj, t, trunk: f"{trunk}/below-{t}"), mock.patch.object(importlib.import_module("fc_ledger"), "run_id", side_effect=run_id):
            return fc_reroute.catch_up(self.repo, self.proj, self.tasks, list(ids), "main", kinds), re

    def test_each_passed_task_with_an_issue_is_reassessed_for_diff_in_order_with_its_run_id_layer_base_and_branch(self):
        got, re = self.sweep(("006", "001", "005"))
        self.assertEqual(got, {})
        self.assertEqual([c.args for c in re.call_args_list], [(self.repo, self.proj, next(m for m in self.tasks if m["id"] == t), self.tasks, ["diff"], f"run-{t}", f"main/below-{t}",
                                                                  fc.fc_worktree.task_branch(self.repo, self.proj, t)) for t in ("006", "001", "005")])

    def test_tasks_not_passed_without_a_result_file_or_without_an_issue_are_skipped(self):
        (self.proj / "results" / "006.json").write_text(json.dumps({"id": "006", "status": "already_green"}))
        got, re = self.sweep()
        self.assertEqual((got, [c.args[2]["id"] for c in re.call_args_list]), ({}, ["001", "005"]))

    def test_without_a_linear_key_or_without_the_diff_kind_nothing_is_reassessed(self):
        for key, kinds in (("", ("diff",)), (None, ("diff",)), ("lin_test", ())):
            with self.subTest(key=key, kinds=kinds):
                got, re = self.sweep(key=key, kinds=kinds)
                self.assertEqual((got, re.call_count), ({}, 0))

    def test_a_failure_is_returned_under_its_id_and_the_other_tasks_go_on(self):
        def boom(repo, proj, meta, *a):
            if meta["id"] == "001": raise RuntimeError("Linear: down")
        got, re = self.sweep(reassess={"side_effect": boom})
        self.assertEqual((got, re.call_count), ({"001": "Linear: down"}, 3))
        got, re = self.sweep(run_id=lambda proj, t: [][0] if t == "005" else "r")
        self.assertEqual((list(got), re.call_count), (["005"], 2))

    def test_payment_required_propagates_and_stops_the_sweep(self):
        seen = []
        def broke(repo, proj, meta, *a): seen.append(meta["id"]); raise fc.fc_models.PaymentRequired("typesafe", "top up")
        with self.assertRaises(fc.fc_models.PaymentRequired):
            self.sweep(reassess={"side_effect": broke})
        self.assertEqual(seen, ["001"])


class Once(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.proj = self.repo / ".compose" / "p"
        (self.proj / "results").mkdir(parents=True)
        self.tasks = [{"id": t, "linear": f"XX-{t}"} for t in ("001", "002", "003")]
        for t in ("001", "002", "003"):
            (self.proj / "results" / f"{t}.json").write_text(json.dumps({"id": t, "status": "passed"}))

    def once(self, fired, ids=("001", "002", "003")):
        """catch_up with `fired(issue)` and `reassess` mocked; returns (its return value, fired mock, reassess mock)."""
        with mock.patch.object(fc.fc_config, "LINEAR_KEY", "lin_test"), mock.patch.object(fc_reroute, "fired", side_effect=fired) as fi, mock.patch.object(fc_reroute, "reassess") as re, \
                mock.patch.object(fc_reroute, "layer_base", return_value="main"), mock.patch.object(importlib.import_module("fc_ledger"), "run_id", side_effect=lambda proj, t: f"run-{t}"):
            return fc_reroute.catch_up(self.repo, self.proj, self.tasks, list(ids), "main", ("diff",)), fi, re

    def test_a_trigger_fired_for_the_run_id_calls_no_reassess_and_each_task_reads_its_own_issue(self):
        got, fi, re = self.once(lambda issue: {("diff", "run-001"), ("diff", "run-003")})
        self.assertEqual((got, [c.args[0] for c in fi.call_args_list]), ({}, ["XX-001", "XX-002", "XX-003"]))
        self.assertEqual([(c.args[2]["id"], c.args[4], c.args[5]) for c in re.call_args_list], [("002", ["diff"], "run-002")])

    def test_the_trigger_fired_only_under_another_run_id_is_reassessed(self):
        got, fi, re = self.once(lambda issue: {("diff", "old-run"), ("scope", "run-001")}, ids=("001",))
        self.assertEqual((got, [(c.args[2]["id"], c.args[4], c.args[5]) for c in re.call_args_list]), ({}, [("001", ["diff"], "run-001")]))

    def test_a_fired_error_is_returned_under_its_id_and_the_other_tasks_go_on(self):
        def fired(issue):
            if issue == "XX-002": raise RuntimeError("Linear: boom")
            return set()
        got, fi, re = self.once(fired)
        self.assertEqual((got, [c.args[2]["id"] for c in re.call_args_list]), ({"002": "Linear: boom"}, ["001", "003"]))


class AfterRun(unittest.TestCase):
    TASKS = [{"id": t, "linear": f"XX-{t}"} for t in ("001", "002", "003", "004")]

    def run_after(self, statuses, **catch_up):
        """after_run over results with these statuses, catch_up mocked; returns (its return value, catch_up mock, say mock)."""
        results = [{"id": t, "status": s} for t, s in statuses]
        with mock.patch.object(fc_reroute, "catch_up", **catch_up) as cu, mock.patch.object(fc.fc_core, "say") as say:
            return fc_reroute.after_run("repo", "proj", results, self.TASKS, "main"), cu, say

    def test_catch_up_gets_the_passed_ids_only_in_order_with_diff(self):
        got, cu, say = self.run_after([("004", "passed"), ("002", "failed"), ("001", "passed"), ("003", "already_green")], return_value={})
        self.assertEqual((got, cu.call_args_list, say.call_count), (None, [mock.call("repo", "proj", self.TASKS, ["004", "001"], "main", ("diff",))], 0))

    def test_each_route_not_recorded_is_said_with_its_issue_and_why(self):
        got, cu, say = self.run_after([("001", "passed"), ("002", "passed"), ("003", "passed")], return_value={"003": "Linear: down", "001": "policies unreadable: boom"})
        self.assertEqual((got, [c.args[0] for c in say.call_args_list]), (None, ["linear XX-003: route not recorded (Linear: down)", "linear XX-001: route not recorded (policies unreadable: boom)"]))

    def test_a_payment_required_is_returned_not_raised_and_nothing_is_said(self):
        err = fc.fc_models.PaymentRequired("typesafe", "top up")
        got, cu, say = self.run_after([("001", "passed")], side_effect=err)
        self.assertEqual((got, say.call_count), (err, 0))

    def test_with_no_passed_task_nothing_is_called_and_it_returns_none(self):
        for statuses in ([], [("001", "failed"), ("002", "already_green")]):
            with self.subTest(statuses=statuses):
                got, cu, say = self.run_after(statuses)
                self.assertEqual((got, cu.call_count, say.call_count), (None, 0, 0))


class RunHook(unittest.TestCase):
    def run_tasks(self, ids=("001", "002"), status=None, hook=None):
        """run_tasks over fake tasks with after_run, triage and payment_halt recorded on one mock; returns (exit code, order, repo, proj, tasks)."""
        repo = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, repo, True); proj = repo / ".compose" / "p"; proj.mkdir(parents=True)
        tasks = [{"id": t, "title": t, "after": "", "files": [], "protected": [], "test": "true", "model": "m", "body": ""} for t in ids]
        pay = [{"payment_required": {"provider": "glm", "message": "pay"}}]
        run_task = lambda r, p, meta, n: {"id": meta["id"], "title": meta["id"], "status": (status or {}).get(meta["id"], "passed"), "attempts": 1, "seconds": 1.0, "cost": 0.0,
                                          "branch": f"b/{meta['id']}", "log": pay if (status or {}).get(meta["id"]) == "payment_required" else []}
        order = mock.Mock(); order.after.return_value = hook
        with mock.patch.object(fc.fc_proc, "keep_awake"), mock.patch.object(fc.fc_run, "preflight"), mock.patch.object(fc.fc_herdr, "herdr_space"), mock.patch.object(fc.fc_core, "say"), \
             mock.patch.object(fc.fc_implement, "run_task", run_task), mock.patch.object(fc.fc_models, "payment_halt", order.halt), mock.patch.object(fc.fc_run, "triage", order.triage), \
             mock.patch.object(fc_reroute, "after_run", order.after), mock.patch("builtins.print", order.print), self.assertRaises(SystemExit) as e:
            fc.fc_run.run_tasks(repo, proj, tasks, mock.Mock(trunk="main", attempts=1, parallel=1, no_stack=True))
        return e.exception.code, order, repo, proj, tasks

    def test_after_run_is_called_once_with_the_results_after_the_table_and_before_triage(self):
        code, order, repo, proj, tasks = self.run_tasks()
        names = [c[0] for c in order.mock_calls]
        self.assertEqual(names.count("after"), 1)
        self.assertLess(max(i for i, n in enumerate(names) if n == "print"), names.index("after"))
        self.assertLess(names.index("after"), names.index("triage"))
        args = order.after.call_args.args
        self.assertEqual((args[0], args[1], [r["id"] for r in args[2]], args[3], args[4]), (repo, proj, ["001", "002"], tasks, "main"))
        self.assertEqual((order.halt.call_count, code), (0, 0))

    def test_a_returned_payment_required_halts_the_run_with_it_after_triage(self):
        err = fc.fc_models.PaymentRequired("typesafe", "top up")
        code, order, *_ = self.run_tasks(hook=err)
        self.assertEqual([c.args[-1] for c in order.halt.call_args_list], [err])
        self.assertEqual([c[0] for c in order.mock_calls if c[0] != "print"], ["after", "triage", "halt"])

    def test_the_hook_runs_when_no_task_passed_and_the_exit_code_stays_failed(self):
        code, order, *_ = self.run_tasks(("001",), {"001": "failed"})
        self.assertEqual((order.after.call_count, order.triage.call_count, order.halt.call_count, code), (1, 0, 0, 1))

    def test_a_providers_halt_is_kept_over_the_hooks(self):
        mine = fc.fc_models.PaymentRequired("typesafe", "top up")
        code, order, *_ = self.run_tasks(("001",), {"001": "payment_required"}, mine)
        halted = order.halt.call_args.args[-1]
        self.assertEqual((order.halt.call_count, halted.provider), (1, "glm"))


class VerifyCatchUp(unittest.TestCase):
    def verify(self, linear=("001", "002"), key=None, **catch_up):
        """cmd_verify over a two-layer stack of passed tasks with its setup and stages faked; catch_up is a mock when given, else the real one.
        Returns (exit code or None, one mock recording catch_up, rounds, say and payment_halt, the repo, the proj)."""
        repo = Path(tempfile.mkdtemp()).resolve(); self.addCleanup(shutil.rmtree, repo, True); proj = repo / ".compose" / "p"; (proj / "results").mkdir(parents=True)
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
        git("init", "-q", "-b", "main"); git("commit", "-q", "--allow-empty", "-m", "init")
        tasks = [{"id": t, "after": "", **({"linear": f"XX-{t}"} if t in linear else {})} for t in ("001", "002")]
        (proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": tasks}))
        for t in ("001", "002"):
            git("branch", fc.fc_worktree.task_branch(repo, proj, t), git("commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", t))
            (proj / "results" / f"{t}.json").write_text(json.dumps({"id": t, "status": "passed"}))
        order = mock.Mock(); order.catch_up.configure_mock(**catch_up)
        a = mock.Mock(repo=str(repo), project="p", fix=0, skip_review=True, skip_e2e=True, review_only=False)
        with mock.patch.object(fc.fc_core, "project_dir", return_value=proj), mock.patch.object(fc.fc_init, "start_checks"), mock.patch.object(fc.fc_proc, "keep_awake"), \
             mock.patch.object(fc.fc_verify, "verify_root", return_value=(repo, "main", None)), mock.patch.object(fc.fc_verify, "verify_rounds", order.rounds), \
             mock.patch.object(fc.fc_core, "say", order.say), mock.patch.object(fc.fc_models, "payment_halt", order.halt), mock.patch.object(fc.fc_config, "LINEAR_KEY", key), \
             mock.patch.object(fc_reroute, "catch_up", *([order.catch_up] if catch_up else [fc_reroute.catch_up])):
            try: fc.fc_verify.cmd_verify(a); code = None
            except SystemExit as e: code = e.code
        return code, order, repo, proj

    def test_the_stack_is_caught_up_once_with_diff_before_any_stage(self):
        code, order, repo, proj = self.verify(return_value={})
        self.assertEqual(order.catch_up.call_args_list, [mock.call(repo, proj, fc.fc_tasks.load_tasks(proj), ["001", "002"], "main", ("diff",))])
        self.assertEqual(([c[0] for c in order.mock_calls if c[0] in ("catch_up", "rounds")], code), (["catch_up", "rounds"], None))

    def test_each_route_not_recorded_is_said_exactly_and_verify_exits_1_without_a_stage(self):
        code, order, *_ = self.verify(return_value={"003": "Linear timeout", "001": "Linear: down"})
        said = [c.args[0] for c in order.say.call_args_list]
        self.assertEqual([s for s in said if "FAIL" in s], ["verify FAIL  route not recorded for 003: Linear timeout", "verify FAIL  route not recorded for 001: Linear: down"])
        self.assertEqual((code, order.rounds.call_count), (1, 0))

    def test_a_payment_required_reaches_payment_halt_without_a_stage(self):
        err = fc.fc_models.PaymentRequired("typesafe", "top up")
        code, order, *_ = self.verify(side_effect=err)
        self.assertEqual(([c.args[-1] for c in order.halt.call_args_list], order.rounds.call_count), ([err], 0))

    def test_without_a_linear_key_nothing_is_asked_or_written_and_the_stages_run(self):
        with mock.patch.object(fc.fc_models, "jev_ask") as ask, mock.patch.object(fc.fc_linear, "linear_gql") as gql, mock.patch.object(fc_reroute, "reassess") as re:
            code, order, *_ = self.verify()
        self.assertEqual((ask.call_count, gql.call_count, re.call_count, order.rounds.call_count, code), (0, 0, 0, 1, None))

    def test_a_stack_task_without_a_linear_issue_is_neither_reassessed_nor_failed(self):
        with mock.patch.object(fc_reroute, "reassess") as re, mock.patch.object(fc_reroute, "fired", return_value=set()):
            code, order, *_ = self.verify(linear=("001",), key="lin_test")
        self.assertEqual(([c.args[2]["id"] for c in re.call_args_list], order.rounds.call_count, code), (["001"], 1, None))


class PassScope(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.proj = self.repo / ".compose" / "p"
        (self.proj / "results").mkdir(parents=True)
        git = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=self.repo, check=True, capture_output=True)
        git("init", "-q", "-b", "main"); git("commit", "-q", "--allow-empty", "-m", "init")
        # 001 leaves its files (also a logo), 002 stays inside, 003 has no files: so every changed file is outside
        edits = {"001": ["src/a.py", "logo.png"], "002": ["src/b.py"], "003": ["src/c.py"]}
        self.tasks = [{"id": t, "after": "", "files": [] if t == "003" else [f"src/{'ab'[int(t) - 1]}.py"], "linear": f"XX-{t}"} for t in edits]
        (self.proj / "results" / "tasks.json").write_text(json.dumps({"feature": {}, "tasks": self.tasks}))
        for t, paths in edits.items():
            git("checkout", "-q", "-b", fc.fc_worktree.task_branch(self.repo, self.proj, t), "main")
            for p in paths: (self.repo / p).parent.mkdir(exist_ok=True); (self.repo / p).write_text(t)
            git("add", "-A"); git("commit", "-qm", t)
            (self.proj / "results" / f"{t}.json").write_text(json.dumps({"id": t, "status": "passed"}))
        git("checkout", "-q", "main")

    def run_hook(self, hook, fired=(), **kw):
        """`hook(**kw)` with the pairs `fired` on every issue; returns (its return value, {task id: reassess call args})."""
        with mock.patch.object(fc.fc_config, "LINEAR_KEY", "lin_test"), mock.patch.object(fc_reroute, "reassess") as re, mock.patch.object(fc_reroute, "fired", return_value=set(fired)), \
                mock.patch.object(importlib.import_module("fc_ledger"), "run_id", side_effect=lambda proj, t: f"run-{t}"):
            got = hook(**kw)
        return got, {c.args[2]["id"]: c.args for c in re.call_args_list}

    def catch_up(self, kinds, fired=(), ids=("001", "002", "003")):
        return self.run_hook(lambda: fc_reroute.catch_up(self.repo, self.proj, self.tasks, list(ids), "main", kinds), fired)

    def test_after_run_asks_diff_and_scope_for_a_layer_outside_its_files_and_diff_only_inside_with_the_layer_base_and_branch(self):
        got, calls = self.run_hook(lambda: fc_reroute.after_run(self.repo, self.proj, [{"id": t, "status": "passed"} for t in ("001", "002", "003")], self.tasks, "main"))
        self.assertEqual((got, {t: a[4] for t, a in calls.items()}), (None, {"001": ["diff", "scope"], "002": ["diff"], "003": ["diff", "scope"]}))
        branch = lambda t: fc.fc_worktree.task_branch(self.repo, self.proj, t)
        self.assertEqual([(a[5], a[6], a[7]) for a in calls.values()], [("run-001", "main", branch("001")), ("run-002", branch("001"), branch("002")), ("run-003", branch("002"), branch("003"))])

    def test_catch_up_with_scope_alone_asks_only_the_tasks_outside_their_files(self):
        got, calls = self.catch_up(("scope",))
        self.assertEqual((got, {t: a[4] for t, a in calls.items()}), ({}, {"001": ["scope"], "003": ["scope"]}))

    def test_a_trigger_fired_for_the_run_id_is_not_asked_again_but_one_fired_for_another_run_is(self):
        for fired, want in ([("diff", "run-001")], ["scope"]), ([("scope", "run-001")], ["diff"]), ([("diff", "run-001"), ("scope", "run-001")], None), ([("diff", "old"), ("scope", "old")], ["diff", "scope"]):
            with self.subTest(fired=fired):
                got, calls = self.catch_up(("diff", "scope"), fired, ("001",))
                self.assertEqual(calls["001"][4] if calls else None, want)

    def test_before_verify_asks_scope_for_the_stack_tasks_whose_comments_hold_diff_but_not_scope(self):
        fired = [("diff", "run-001"), ("diff", "run-002"), ("diff", "run-003"), ("scope", "run-003")]
        got, calls = self.run_hook(lambda: fc_reroute.before_verify(self.repo, self.proj, self.tasks, "main"), fired)
        self.assertEqual({t: a[4] for t, a in calls.items()}, {"001": ["scope"]})
        got, calls = self.run_hook(lambda: fc_reroute.before_verify(self.repo, self.proj, self.tasks, "main"), fired + [("scope", "run-001")])
        self.assertEqual(calls, {})

    def test_a_diff_signals_error_is_that_tasks_failure_and_the_others_go_on(self):
        real = fc_reroute.diff_signals
        def signals(repo, meta, *a):
            if meta["id"] == "001": raise RuntimeError("git diff failed")
            return real(repo, meta, *a)
        with mock.patch.object(fc_reroute, "diff_signals", signals):
            got, calls = self.catch_up(("scope",))
        self.assertEqual((got, list(calls)), ({"001": "git diff failed"}, ["003"]))
