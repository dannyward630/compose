import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, io, json, os, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_policy, fc_routectx, fc_routejev, fc_routerec  # noqa: E402

NOTE = "policies unavailable: no Linear key"


def task(ident, tid, **kv):
    desc = "## Acceptance criteria\n- works\n\n```compose\n" + "\n".join(f"{k}: {v}" for k, v in {"id": tid, "files": f"{tid}.py", "protected": f"test_{tid}.py", "test": "t", **kv}.items()) + "\n```\n"
    return {"id": ident, "title": "T", "description": desc, "status": "Todo", "blockedBy": []}


class Keyless(unittest.TestCase):
    def setUp(self):
        self.raw = Path(tempfile.mkdtemp())
        self.repo, self.proj = self.raw.resolve(), self.raw.resolve() / ".compose" / "p"
        self.proj.mkdir(parents=True)
        for name, text in (("linear.json", '{"feature": "ENG-1"}'), ("verify.json", '{"route_threshold": 0.7}')): (self.proj / name).write_text(text)
        issues = [task("ENG-3", "001", route="implement-then-test"), task("ENG-4", "002"), task("ENG-5", "003", kind="design")]
        fc.fc_tasks.sync_tasks(self.proj, {"feature": {"id": "ENG-1", "title": "F", "description": ""}, "issues": issues})
        self.files = {p: p.read_bytes() for p in self.proj.rglob("*") if p.is_file()}
        route = {"001": {"depth": "DEEP", "workflow": "implement-then-test"}, "002": {"depth": "STANDARD", "workflow": "test-first"}}
        for target, name, kw in [(fc.fc_core, "project_dir", {"return_value": self.proj}), (fc.fc_linear, "_linear_warned", {"new": []}), (fc.fc_linear, "linear_gql", {}),
                                 (fc_routectx, "dependency_context", {"return_value": {"callers": {}}}), (fc_routerec, "route_reason", {"side_effect": lambda r, s: f"why {s['tid']}; {r['note']}"}),
                                 (fc_routectx, "route_context", {"side_effect": lambda repo, proj, m, tasks, issues: {"tid": m["id"]}}),
                                 (fc_routejev, "decide", {"side_effect": lambda env, cfg, s, m, p, more: {**route[s["tid"]]}})]:
            setattr(self, name, mock.patch.object(target, name, **kw).start())
        self.addCleanup(mock.patch.stopall)

    def route(self, only=None):
        with mock.patch("sys.stdout", io.StringIO()) as out:
            fc.fc_route.cmd_route(SimpleNamespace(repo=str(self.raw), project="p", only=only, recalculate=False))
        return out.getvalue().splitlines()

    def test_prints_one_line_per_code_task_and_writes_nothing(self):
        self.assertIn("linear skipped:", (lines := self.route())[0])
        self.assertEqual(lines[1:], ["001 DEEP implement-then-test  why 001; " + NOTE, "002 STANDARD test-first  why 002; " + NOTE])
        tasks, issues = fc.fc_tasks.code_tasks(fc.fc_tasks.load_tasks(self.proj)), fc.fc_tasks.linear_cache(self.proj)["issues"]
        self.assertEqual([c.args for c in self.route_context.call_args_list], [(self.repo, self.proj, m, tasks, issues) for m in tasks])
        env, cfg, state, matched, plain, more = self.decide.call_args.args
        self.assertEqual((env["HOME"], cfg, state, matched, plain), (os.environ["HOME"], {"route_threshold": 0.7}, {"tid": "002"}, [], []))
        self.assertEqual((more(), self.dependency_context.call_args.args), ({"callers": {}}, (self.repo, tasks[1])))
        self.assertEqual((self.linear_gql.called, {p: p.read_bytes() for p in self.proj.rglob("*") if p.is_file()}), (False, self.files))

    def test_only_routes_the_named_tasks_and_returns_the_routes(self):
        self.assertEqual(self.route("002")[1:], ["002 STANDARD test-first  why 002; " + NOTE])
        routes, held = fc.fc_route.route_tasks(self.repo, self.proj, fc.fc_tasks.load_tasks(self.proj)[:1])
        self.assertEqual((list(routes), held, routes["001"]["note"], routes["001"]["reason"]), (["001"], {}, NOTE, "why 001; " + NOTE))
        with self.assertRaisesRegex(SystemExit, "^no tasks on Linear under this feature carry a compose block with ids 003,009$"):
            self.route("003,009")


class Policies(unittest.TestCase):
    def setUp(self):
        self.raw = Path(tempfile.mkdtemp())
        self.repo, self.proj = self.raw.resolve(), self.raw.resolve() / ".compose" / "p"
        self.proj.mkdir(parents=True)
        (self.proj / "linear.json").write_text('{"feature": "ENG-1"}')
        issues = [task("ENG-3", "001", files="bin/x.py"), task("ENG-4", "002", files="docs/y.md")]
        fc.fc_tasks.sync_tasks(self.proj, {"feature": {"id": "ENG-1", "title": "F", "description": ""}, "issues": issues})
        self.tasks = fc.fc_tasks.load_tasks(self.proj)
        self.pols = [{"name": n, "globs": g, "checks": []} for n, g in (("A", ["bin/*"]), ("B", []), ("C", ["docs/*"]), ("D", []))]
        for target, name, kw in [(fc.fc_core, "project_dir", {"return_value": self.proj}), (fc.fc_linear, "_linear_warned", {"new": []}),
                                 (fc_routectx, "route_context", {"return_value": {}}), (fc_routerec, "route_reason", {"side_effect": lambda r, s: "why; " + r["note"]}),
                                 (fc_routejev, "decide", {"side_effect": lambda *a: {"depth": "DEEP", "workflow": "test-first"}}),
                                 (fc_policy, "glob_matches", {"side_effect": lambda ps, files: [ps[0]] if files == ["bin/x.py"] else []}),
                                 (fc_policy, "read_policies", {"return_value": (self.pols, "a note")})]:
            setattr(self, name, mock.patch.object(target, name, **kw).start())
        self.addCleanup(mock.patch.stopall)

    def test_each_task_gets_its_matched_policies_and_every_plain_one_from_a_single_read(self):
        with mock.patch("sys.stdout", io.StringIO()):
            routes, held = fc.fc_route.route_tasks(self.repo, self.proj, self.tasks)
        self.assertEqual((self.read_policies.call_args_list, held), ([mock.call(self.repo)], {}))
        self.assertEqual([c.args for c in self.glob_matches.call_args_list], [(self.pols, ["bin/x.py"]), (self.pols, ["docs/y.md"])])
        self.assertEqual([c.args[3:5] for c in self.decide.call_args_list], [([self.pols[0]], [self.pols[1], self.pols[3]]), ([], [self.pols[1], self.pols[3]])])
        self.assertEqual((sorted(routes), routes["002"]["reason"]), (["001", "002"], "why; a note"))

    def test_unreadable_policies_hold_every_task_and_route_nothing(self):
        self.read_policies.side_effect = RuntimeError("policies unreadable: boom")
        with mock.patch("sys.stdout", io.StringIO()) as out, mock.patch.object(fc.fc_linear, "linear_ready", return_value=True):
            result = fc.fc_route.route_tasks(self.repo, self.proj, self.tasks)
        self.assertEqual((result, self.decide.called, out.getvalue()), (({}, {"001": "policies unreadable: boom", "002": "policies unreadable: boom"}), False, ""))

    def test_compose_route_stops_on_unreadable_policies(self):
        self.read_policies.side_effect = RuntimeError("2 documents titled Verification policies: D1, D2")
        with mock.patch("sys.stdout", io.StringIO()), self.assertRaises(SystemExit) as stop:
            fc.fc_route.cmd_route(SimpleNamespace(repo=str(self.raw), project="p", only=None, recalculate=False))
        self.assertEqual((stop.exception.code, self.decide.called), ("route stopped: 2 documents titled Verification policies: D1, D2; nothing recorded", False))

    def test_only_reads_the_policies_once_for_the_named_task(self):
        with mock.patch("sys.stdout", io.StringIO()):
            fc.fc_route.cmd_route(SimpleNamespace(repo=str(self.raw), project="p", only="002", recalculate=False))
        self.assertEqual((self.read_policies.call_count, self.decide.call_count), (1, 1))


class Record(unittest.TestCase):
    READ = "query($id: String!) { issue(id: $id) { id description } }"
    UPDATE = "mutation($id: String!, $in: IssueUpdateInput!) { issueUpdate(id: $id, input: $in) { success } }"
    SECTION = "R test-first STANDARD h1 why"

    def setUp(self):
        self.repo, self.proj = (r := Path(tempfile.mkdtemp()).resolve()), r / ".compose" / "p"
        self.proj.mkdir(parents=True)
        (self.proj / "linear.json").write_text('{"feature": "ENG-1"}')
        fc.fc_tasks.sync_tasks(self.proj, {"feature": {"id": "ENG-1", "title": "F", "description": ""}, "issues": [task("ENG-3", "001"), task("ENG-4", "002")]})
        self.tasks, self.hash, self.calls, self.cache = fc.fc_tasks.load_tasks(self.proj), "h1", [], self.proj / "results" / "tasks.json"
        self.gql = lambda q, v: (self.calls.append((q, v)), {"issue": {"id": "U-" + v["id"], "description": "live" if v["id"] == "ENG-3" else None}} if "issue(id" in q else {})[1]
        for target, name, kw in [(fc.fc_config, "LINEAR_KEY", {"new": "lin_test"}), (fc.fc_linear, "linear_gql", {"side_effect": self.gql}), (fc_routectx, "route_context", {"return_value": {}}),
                                 (fc_routectx, "context_hash", {"side_effect": lambda repo, m, pols: self.hash}), (fc_policy, "read_policies", {"return_value": ([], "")}), (fc_policy, "glob_matches", {"return_value": []}), (fc_routerec, "route_reason", {"return_value": "why"}),
                                 (fc_routerec, "parse_route", {"side_effect": lambda d: dict(zip(("workflow", "depth", "context hash", "reason"), d.split("\n")[0][2:].split(" ", 3))) if d.startswith("R ") else None}),
                                 (fc_routerec, "route_section", {"side_effect": lambda r: f"R {r['workflow']} {r['depth']} {r['hash']} {r['reason']}"}), (fc_routerec, "with_route", {"side_effect": lambda desc, sec: sec + "\n" + desc}),
                                 (fc_routejev, "decide", {"side_effect": lambda *a: {"workflow": "test-first", "depth": "STANDARD"}})]:
            setattr(self, name, mock.patch.object(target, name, **kw).start())
        self.addCleanup(mock.patch.stopall)

    def route(self, **kw):
        self.calls.clear()
        with mock.patch("sys.stdout", io.StringIO()) as out:
            return fc.fc_route.route_tasks(self.repo, self.proj, self.tasks, **kw), out.getvalue()

    def test_a_new_route_is_written_above_the_block_commented_and_cached(self):
        want, live = json.loads(self.cache.read_text()), {"ENG-3": "live", "ENG-4": ""}
        (_, held), _ = self.route()
        for ident, desc in live.items(): want["issues"][ident]["description"] = self.SECTION + "\n" + desc
        self.assertEqual([(q if "commentCreate" not in q else None, v) for q, v in self.calls], [c for ident, desc in live.items() for c in (
            (self.READ, {"id": ident}), (self.UPDATE, {"id": ident, "in": {"description": self.SECTION + "\n" + desc}}), (None, {"id": "U-" + ident, "b": self.SECTION}))])
        self.assertEqual((json.loads(self.cache.read_text()), held), (want, {}))

    def test_the_same_hash_reuses_the_recorded_route_without_a_call_or_a_write(self):
        self.route()
        saved = self.cache.read_bytes()
        self.decide.reset_mock()
        (routes, _), out = self.route()
        self.assertEqual((self.decide.called, self.calls, self.cache.read_bytes()), (False, [], saved))
        self.assertEqual(out.splitlines(), ["001 STANDARD test-first  reused why", "002 STANDARD test-first  reused why"])
        self.assertEqual(routes["002"], {"workflow": "test-first", "depth": "STANDARD", "reason": "why", "hash": "h1"})

    def test_recalculate_or_a_changed_hash_decides_and_records_again(self):
        self.route()
        for hash_, kw in (("h1", {"recalculate": True}), ("h2", {})):
            with self.subTest(hash=hash_):
                self.decide.reset_mock()
                self.hash = hash_
                _, out = self.route(**kw)
                self.assertEqual((self.decide.call_count, len(self.calls), "reused" in out), (2, 6, False))

    def test_a_record_that_raises_is_said_and_the_tasks_stay_routed(self):
        saved = self.cache.read_bytes()
        self.linear_gql.side_effect = lambda q, v: 1 / 0 if "issueUpdate" in q else self.gql(q, v)
        (routes, _), out = self.route()
        self.assertEqual((sorted(routes), self.cache.read_bytes()), (["001", "002"], saved))
        self.assertTrue(all(f"linear {i}: route not recorded (division by zero)" in out for i in ("ENG-3", "ENG-4")))
