import hermetic  # first: no test sees the real home
import importlib.machinery, importlib.util, io, json, os, subprocess, tempfile, unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import sys
os.environ["HERDR_ENV"] = ""

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)


KEY, URL = "lin_api_SECRET_do_not_print", "https://linear.app/acme/project/my-shop-abc123"


class LinearProject(unittest.TestCase):
    def setUp(self):
        self.repo = Path(tempfile.mkdtemp()).resolve()  # resolved: macOS /var vs /private/var
        (self.repo / ".compose").mkdir()
        (self.repo / ".compose" / "linear.json").write_text(json.dumps({"project": URL, "team": "Engineering"}))
        self.calls, self.nodes, self.teams = [], None, [{"id": "t0", "name": "Design", "key": "DES"}, {"id": "t1", "name": "Engineering", "key": "ENG"}]
        for mod, name, value in ((fc.fc_config, "LINEAR_KEY", KEY), (fc.fc_config, "WORKSPACE", "work"), (fc.fc_linear, "linear_gql", self.gql)):
            p = mock.patch.object(mod, name, value); p.start(); self.addCleanup(p.stop)

    def gql(self, query, variables):
        self.calls.append((" ".join(query.split()), variables))
        return {"projects": {"nodes": [{"id": "p1", "name": "Shop", "url": URL, "teams": {"nodes": self.teams}}] if self.nodes is None else self.nodes}}

    def args(self, action, *target, **kw):
        return SimpleNamespace(**{**dict(repo=str(self.repo), project=None, action=action, target=list(target), body=False, comments=False, json=False,
                                         append=False, description=False, any_project=False, label=None, parent=None, search=None, state=None,
                                         title=None, blocked_by=None, file=None, section=None, create=None), **kw})

    def fails(self, fn, *args):
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as e:
            fn(*args)
        code = e.exception.code
        return (1 if isinstance(code, str) else code), ((code if isinstance(code, str) else "") + err.getvalue()).strip()

    def test_no_key_exits_naming_the_workspace_and_calls_no_verb(self):
        with mock.patch.object(fc.fc_config, "LINEAR_KEY", None), mock.patch.object(fc.fc_linear_cmd, "verb_project", side_effect=AssertionError("verb ran without a key")):
            self.assertEqual(self.fails(fc.fc_linear_cmd.cmd_linear, self.args("project")), (1, "compose linear needs a Linear key for workspace 'work': pbpaste | compose workspace key work --linear"))
        p = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "bin" / "compose"), "linear", "project", "--repo", str(self.repo)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 1); self.assertIn("compose linear needs a Linear key for workspace 'default': pbpaste | compose workspace key default --linear", p.stderr)

    def test_with_a_key_it_dispatches_to_the_verb_and_wraps_its_errors(self):
        for action in ("project", "get", "doc"):
            with mock.patch.object(fc.fc_linear_cmd, f"verb_{action}") as verb:
                fc.fc_linear_cmd.cmd_linear(a := self.args(action))
            verb.assert_called_once_with(a)
        for exc in (RuntimeError("boom"), OSError("boom")):
            with mock.patch.object(fc.fc_linear_cmd, "verb_list", side_effect=exc):
                self.assertEqual(self.fails(fc.fc_linear_cmd.cmd_linear, self.args("list")), (1, "linear list: boom"))

    def test_project_reads_linear_json_and_picks_the_named_team(self):
        got = fc.fc_linear_cmd.linear_project(str(self.repo))
        self.assertEqual(got, {"id": "p1", "name": "Shop", "url": URL, "team": {"id": "t1", "name": "Engineering", "key": "ENG"}})
        self.assertEqual([v for _, v in self.calls], [{"slug": "abc123"}]); self.assertIn("projects(filter: {slugId: {eq: $slug}}) { nodes { id name url teams { nodes { id name key } } } }", self.calls[0][0])
        with redirect_stdout(io.StringIO()) as out:
            fc.fc_linear_cmd.verb_project(self.args("project"))
        self.assertEqual(out.getvalue().strip(), f"Shop on team Engineering: {URL}")

    def test_project_failures(self):
        self.teams = self.teams[:1]
        self.assertEqual(self.fails(fc.fc_linear_cmd.linear_project, str(self.repo)), (1, "project Shop is not on team Engineering"))
        self.nodes = []
        self.assertEqual(self.fails(fc.fc_linear_cmd.linear_project, str(self.repo)), (1, f"Linear has no project {URL}"))
        (self.repo / ".compose" / "linear.json").unlink()
        self.assertEqual(self.fails(fc.fc_linear_cmd.linear_project, str(self.repo)), (1, f"no .compose/linear.json in {self.repo}"))


class LinearGet(unittest.TestCase):
    QUERY = "issue(id: $id) { identifier title description state { name } labels { nodes { name } } project { id name } parent { identifier } comments { nodes { body createdAt user { name } } } }"
    args, fails = LinearProject.args, LinearProject.fails

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp()).resolve()
        (self.repo / ".compose").mkdir()
        (self.repo / ".compose" / "linear.json").write_text(json.dumps({"project": URL, "team": "Engineering"}))
        self.calls = []
        self.issue = {"identifier": "ENG-7", "title": "Fix the cart", "description": "Steps here.", "state": {"name": "In Progress"},
                      "labels": {"nodes": [{"name": "bug"}, {"name": "ui"}]}, "project": {"id": "p1", "name": "Shop"}, "parent": None,
                      "comments": {"nodes": [{"body": "second", "createdAt": "2026-03-04T09:00:00.000Z", "user": {"name": "Bob"}},
                                             {"body": "first", "createdAt": "2026-01-02T23:30:00.000Z", "user": {"name": "Ann"}}]}}
        for mod, name, value in ((fc.fc_config, "LINEAR_KEY", KEY), (fc.fc_linear, "linear_gql", self.gql)):
            p = mock.patch.object(mod, name, value); p.start(); self.addCleanup(p.stop)

    def gql(self, query, variables):
        self.calls.append((" ".join(query.split()), variables))
        if "projects(" in query:
            return {"projects": {"nodes": [{"id": "p1", "name": "Shop", "url": URL, "teams": {"nodes": [{"id": "t1", "name": "Engineering", "key": "ENG"}]}}]}}
        return {"issue": self.issue}

    def get(self, *target, **kw):
        with redirect_stdout(io.StringIO()) as out:
            fc.fc_linear_cmd.verb_get(self.args("get", *target, **kw))
        return [line for line in out.getvalue().splitlines() if line.strip()]

    def test_line_shape_with_and_without_labels(self):
        self.assertEqual(fc.fc_linear_cmd.issue_line(self.issue), "ENG-7 In Progress bug Fix the cart")
        self.assertEqual(fc.fc_linear_cmd.issue_line({**self.issue, "labels": {"nodes": []}}), "ENG-7 In Progress - Fix the cart")

    def test_get_prints_only_the_line_from_the_issue_query(self):
        self.assertEqual(self.get("ENG-7"), ["ENG-7 In Progress bug Fix the cart"])
        self.assertEqual([v for q, v in self.calls if self.QUERY in q], [{"id": "ENG-7"}])
        self.assertEqual(self.fails(fc.fc_linear_cmd.verb_get, self.args("get")), (1, "get needs an issue id"))

    def test_body_then_comments_oldest_first(self):
        line, ann, bob = "ENG-7 In Progress bug Fix the cart", ["--- Ann 2026-01-02", "first"], ["--- Bob 2026-03-04", "second"]
        self.assertEqual(self.get("ENG-7", body=True, comments=True), [line, "Steps here."] + ann + bob)
        self.assertEqual(self.get("ENG-7", comments=True), [line] + ann + bob)
        self.assertEqual(self.get("ENG-7", body=True), [line, "Steps here."])

    def test_json_prints_only_the_issue(self):
        with redirect_stdout(io.StringIO()) as out:
            fc.fc_linear_cmd.verb_get(self.args("get", "ENG-7", json=True, body=True, comments=True))
        self.assertEqual(out.getvalue().strip(), json.dumps(self.issue, indent=1))

    def test_out_of_scope_refuses_unless_any_project(self):
        self.issue["project"] = {"id": "p9", "name": "Shop"}
        for kw in ({}, {"json": True}):
            with redirect_stdout(io.StringIO()) as out:
                self.assertEqual(self.fails(fc.fc_linear_cmd.verb_get, self.args("get", "ENG-7", **kw)), (1, "ENG-7 is not in project Shop; pass --any-project to use it"))
            self.assertEqual(out.getvalue(), "")
        self.assertEqual(self.get("ENG-7", any_project=True), ["ENG-7 In Progress bug Fix the cart"])
