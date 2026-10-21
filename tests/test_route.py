import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, io, os, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
os.environ["COMPOSE_NO_TREEHOUSE"] = "1"
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)
import fc_routectx, fc_routejev, fc_routerec  # noqa: E402

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
