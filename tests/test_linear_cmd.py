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


class LinearList(unittest.TestCase):
    QUERY = "issues(first: 100, after: $after, filter: $f) { pageInfo { hasNextPage endCursor } nodes { identifier title state { name } labels { nodes { name } } } }"
    args, fails = LinearProject.args, LinearProject.fails

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp()).resolve()
        (self.repo / ".compose").mkdir()
        (self.repo / ".compose" / "linear.json").write_text(json.dumps({"project": URL, "team": "Engineering"}))
        node = lambda n, state, labels: {"identifier": f"ENG-{n}", "title": f"Task {n}", "state": {"name": state}, "labels": {"nodes": [{"name": x} for x in labels]}}
        self.pages = {None: ([node(3, "Todo", ["ui"]), node(1, "Done", [])], True, "c1"), "c1": ([node(2, "In Progress", ["bug", "ui"])], True, "c2"), "c2": ([], False, "c3")}
        self.nodes = [n for page in self.pages.values() for n in page[0]]
        self.calls = []
        for mod, name, value in ((fc.fc_config, "LINEAR_KEY", KEY), (fc.fc_linear, "linear_gql", self.gql)):
            p = mock.patch.object(mod, name, value); p.start(); self.addCleanup(p.stop)

    def gql(self, query, variables):
        self.calls.append((" ".join(query.split()), variables))
        if "projects(" in query:
            return {"projects": {"nodes": [{"id": "p1", "name": "Shop", "url": URL, "teams": {"nodes": [{"id": "t1", "name": "Engineering", "key": "ENG"}]}}]}}
        nodes, more, cursor = self.pages[variables.get("after")]
        return {"issues": {"pageInfo": {"hasNextPage": more, "endCursor": cursor}, "nodes": nodes}}

    def run_list(self, **kw):
        with redirect_stdout(io.StringIO()) as out:
            fc.fc_linear_cmd.verb_list(self.args("list", **kw))
        return out.getvalue(), [v for q, v in self.calls if self.QUERY in q]

    def test_without_parent_or_search_it_refuses_and_queries_nothing(self):
        for kw in ({}, {"state": "Todo", "label": ["ui"]}):
            self.assertEqual(self.fails(fc.fc_linear_cmd.verb_list, self.args("list", **kw)), (1, 'list needs --parent <id> or --search "<terms>"'))
        self.assertFalse([q for q, _ in self.calls if "issues(" in q])

    def test_reads_every_page_and_prints_each_line_in_order(self):
        out, sent = self.run_list(parent="ENG-1")
        self.assertEqual(out.splitlines(), [fc.fc_linear_cmd.issue_line(n) for n in self.nodes])
        self.assertEqual([v.get("after") for v in sent], [None, "c1", "c2"])
        self.assertEqual([v["f"] for v in sent], [{"project": {"id": {"eq": "p1"}}, "parent": {"id": {"eq": "ENG-1"}}}] * 3)

    def test_filter_holds_each_flag_given(self):
        _, sent = self.run_list(search="cart total", state="todo", label=["bug", "ui"])
        self.assertEqual(sent[0]["f"], {"project": {"id": {"eq": "p1"}}, "searchableContent": {"contains": "cart total"},
                                        "state": {"name": {"eqIgnoreCase": "todo"}}, "labels": {"some": {"name": {"in": ["bug", "ui"]}}}})
        self.calls.clear()
        _, sent = self.run_list(parent="ENG-9", search="cart")
        self.assertEqual(sent[0]["f"], {"project": {"id": {"eq": "p1"}}, "parent": {"id": {"eq": "ENG-9"}}, "searchableContent": {"contains": "cart"}})

    def test_json_prints_only_all_nodes(self):
        out, _ = self.run_list(search="cart", json=True)
        self.assertEqual(out.strip(), json.dumps(self.nodes, indent=1))


class LinearCreate(unittest.TestCase):
    TEAM, CREATE = "team(id: $id) { name states { nodes { id name } } labels(first: 250) { nodes { id name } } }", "issueCreate(input: $in) { issue { id identifier } }"
    args, fails = LinearProject.args, LinearProject.fails

    def setUp(self):
        self.repo = Path(tempfile.mkdtemp()).resolve()
        (self.repo / ".compose").mkdir()
        (self.repo / ".compose" / "linear.json").write_text(json.dumps({"project": URL, "team": "Engineering"}))
        self.calls, self.team = [], {"name": "Engineering", "states": {"nodes": [{"id": "s1", "name": "Todo"}, {"id": "s2", "name": "In Progress"}]},
                                     "labels": {"nodes": [{"id": "l1", "name": "Bug"}, {"id": "l2", "name": "ui"}]}}
        tty = mock.Mock(**{"isatty.return_value": True, "read.side_effect": AssertionError("read stdin from a terminal")})
        for mod, name, value in ((fc.fc_config, "LINEAR_KEY", KEY), (fc.fc_linear, "linear_gql", self.gql), (sys, "stdin", tty)):
            p = mock.patch.object(mod, name, value); p.start(); self.addCleanup(p.stop)

    def gql(self, query, variables):
        self.calls.append((" ".join(query.split()), variables))
        if "projects(" in query:
            return {"projects": {"nodes": [{"id": "p1", "name": "Shop", "url": URL, "teams": {"nodes": [{"id": "t1", "name": "Engineering", "key": "ENG"}]}}]}}
        if "issueCreate" in query:
            return {"issueCreate": {"issue": {"id": "new-id", "identifier": "ENG-12"}}}
        return {"team": self.team}

    def create(self, **kw):
        with mock.patch.object(fc.fc_linear, "linear_issue", return_value={"id": "parent-id"}) as issue, mock.patch.object(fc.fc_linear, "linear_blocked_by") as blocked, redirect_stdout(io.StringIO()) as out:
            fc.fc_linear_cmd.verb_create(self.args("create", title="Fix it", **kw))
        self.assertEqual(out.getvalue().strip(), "created ENG-12")
        self.assertEqual([v for q, v in self.calls if self.TEAM in q], [{"id": "t1"}])
        return [v["in"] for q, v in self.calls if self.CREATE in q], issue, blocked

    def test_read_body_takes_the_file_then_piped_stdin_then_nothing(self):
        (body := self.repo / "body.md").write_text("from file\n")
        with mock.patch("sys.stdin", io.StringIO("from stdin")):
            self.assertEqual(fc.fc_linear_cmd.read_body(self.args("create", file=str(body))), "from file\n")
            self.assertEqual(fc.fc_linear_cmd.read_body(self.args("create")), "from stdin")
        self.assertEqual(fc.fc_linear_cmd.read_body(self.args("create")), "")

    def test_state_and_labels_match_names_case_insensitively_for_the_flags_given(self):
        sl = lambda **kw: fc.fc_linear_cmd.state_and_labels(self.team, self.args("create", **kw))
        got = sl(state="in progress", label=["bug", "UI"])
        self.assertEqual((sorted(got), got["stateId"]), (["labelIds", "stateId"], "s2")); self.assertCountEqual(got["labelIds"], ["l1", "l2"])
        self.assertEqual((sl(), sl(state="TODO"), sl(label=["Ui"])), ({}, {"stateId": "s1"}, {"labelIds": ["l2"]}))
        self.assertEqual(self.fails(lambda: sl(state="Doing")), (1, "team Engineering has no state 'Doing'"))
        self.assertEqual(self.fails(lambda: sl(label=["bug", "perf"])), (1, "team Engineering has no label 'perf'; compose linear labels --create perf makes it"))

    def test_create_sends_every_flag_then_sets_the_blockers(self):
        (body := self.repo / "body.md").write_text("Steps.")
        sent, issue, blocked = self.create(file=str(body), parent="ENG-1", state="todo", label=["BUG"], blocked_by="ENG-2,ENG-3")
        self.assertEqual(sent, [{"teamId": "t1", "projectId": "p1", "title": "Fix it", "description": "Steps.", "parentId": "parent-id", "stateId": "s1", "labelIds": ["l1"]}])
        issue.assert_any_call("ENG-1"); blocked.assert_called_once_with({"id": "new-id"}, ["ENG-2", "ENG-3"])

    def test_create_without_flags_sends_only_the_base_input(self):
        with mock.patch("sys.stdin", io.StringIO("piped body")):
            sent, issue, blocked = self.create()
        self.assertEqual(sent, [{"teamId": "t1", "projectId": "p1", "title": "Fix it", "description": "piped body"}])
        issue.assert_not_called(); blocked.assert_not_called()

    def test_refuses_without_a_title_or_with_an_unknown_name_and_creates_nothing(self):
        self.assertEqual(self.fails(fc.fc_linear_cmd.verb_create, self.args("create")), (1, "create needs --title"))
        self.assertIn("has no label 'perf'", self.fails(fc.fc_linear_cmd.verb_create, self.args("create", title="Fix it", label=["perf"]))[1])
        self.assertFalse([q for q, _ in self.calls if "issueCreate" in q])
