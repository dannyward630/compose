import importlib.machinery, importlib.util, io, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_spec = importlib.util.spec_from_loader("fc", importlib.machinery.SourceFileLoader("fc", str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")))
fc = importlib.util.module_from_spec(_spec)
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
_spec.loader.exec_module(fc)


class Text(unittest.TestCase):
    """scrub, environment, issue_text: what reaches GitHub."""

    def setUp(self):
        p = mock.patch.dict(os.environ, {"HOME": "/Users/alice9", "USER": "alice9", "LOGNAME": "alice9"}); p.start(); self.addCleanup(p.stop)

    def test_scrub_replaces_home_users_and_tokens_and_keeps_the_rest(self):
        keep = "shop-tests at 1a2b3c4 / " + "0123456789abcdef" * 2 + "01234567, alice9x, bob7s, ghp_short"
        tokens = ["ghp_" + "A1" * 18, "gho_" + "b" * 20, "ghu_" + "c" * 24, "ghs_" + "D" * 30, "ghr_" + "e5" * 15,
                  "github_pat_11AB_" + "x9" * 20, "sk-or-v1-" + "f0" * 32, "sk-ant-api03-" + "Ab_-" * 6, "lin_api_" + "Z" * 40]
        raw = "/Users/alice9/code/x by alice9 and bob7: " + " ".join(tokens) + " Authorization: Bearer eyJ.abc-1 " + keep
        want = "~/code/x by <user> and <user>: " + " ".join(["<redacted>"] * len(tokens)) + " Authorization: Bearer <redacted> " + keep
        self.assertEqual(fc.fc_toolbug.scrub(raw, login="bob7"), want)
        self.assertEqual(fc.fc_toolbug.scrub("bob7 alice9"), "bob7 <user>")
        self.assertEqual(fc.fc_toolbug.scrub("prodoxx filed prodoxx/compose#1", login="prodoxx"), "<user> filed prodoxx/compose#1")

    def test_environment_lists_the_commit_platform_and_first_version_lines(self):
        import platform
        d = Path(tempfile.mkdtemp()).resolve()
        for name, out in (("claude", "2.1.302 (Claude Code)"), ("herdr", "herdr 0.9.1\nbuilt today"), ("gh", "gh version 2.94.0 (2026-09-01)")):
            (d / name).write_text(f"#!/bin/sh\necho '{out}'\n"); (d / name).chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": f"{d}:/usr/bin:/bin"}):
            env = fc.fc_toolbug.environment()
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=fc.fc_crew.CLI_REPO, capture_output=True, text=True).stdout.strip()
        self.assertEqual(env.strip().splitlines(), [f"- compose: {commit}", f"- OS: {platform.platform()}", f"- Python: {platform.python_version()}",
                         "- claude: 2.1.302 (Claude Code)", "- herdr: herdr 0.9.1", "- trail: not installed", "- gh: gh version 2.94.0 (2026-09-01)"])
        self.assertNotIn("/", env)

    def test_issue_text_splits_the_title_fills_environment_and_root_cause_and_is_stable(self):
        tb, env = fc.fc_toolbug, "- compose: abc1234\n- OS: at /Users/alice9/x"
        with mock.patch.object(tb, "environment", return_value=env):
            title, body = tb.issue_text("# crew start: hangs for alice9\n## Summary\n\n It hangs. \n\n## Symptom\nstuck\n\n## Root cause\n\n## Reproduction\nrun it\n")
            self.assertEqual(title, "crew start: hangs for <user>")
            self.assertEqual(body, "## Summary\n\nIt hangs.\n\n## Environment\n\n- compose: abc1234\n- OS: at ~/x\n\n## Symptom\n\nstuck\n\n"
                                   "## Root cause\n\nnot found\n\n## Reproduction\n\nrun it\n")
            self.assertEqual(tb.issue_text("# " + title + "\n" + body), (title, body))
            # no Summary: Environment goes first; a missing Root cause goes before Reproduction, else last; login scrubbed
            self.assertEqual(tb.issue_text("# x: y\n## Symptom\nbob7 saw it\n## Reproduction\nrun\n", login="bob7")[1],
                             "## Environment\n\n- compose: abc1234\n- OS: at ~/x\n\n## Symptom\n\n<user> saw it\n\n## Root cause\n\nnot found\n\n## Reproduction\n\nrun\n")
            self.assertEqual(tb.issue_text("# x: y\n## Symptom\nz\n## Environment\nold /opt/stuff\n## Fix\npatch\n")[1],
                             "## Symptom\n\nz\n\n## Environment\n\n- compose: abc1234\n- OS: at ~/x\n\n## Fix\n\npatch\n\n## Root cause\n\nnot found\n")
            for bad in ("crew start: hangs\n## Summary\nx\n", "#crew: hangs\n"):
                with self.assertRaises(ValueError):
                    tb.issue_text(bad)


class Gh(unittest.TestCase):
    """gh_status, open_matches, post, record_issue against a fake gh on PATH."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp()).resolve()
        self.log = self.home / ".compose" / "tool-bugs.jsonl"
        for p in (mock.patch.object(fc.fc_crew, "TOOL_BUGS", self.log),
                  mock.patch.object(fc.fc_config, "CONFIG_PATH", self.home / ".compose" / "config.json")):
            p.start(); self.addCleanup(p.stop)

    def fake_gh(self, replies):
        d = Path(tempfile.mkdtemp()).resolve(); (d / "replies.json").write_text(json.dumps(replies))
        (d / "gh").write_text(f'''#!{sys.executable}
import json, sys
d = {str(d)!r}
open(d + "/calls.jsonl", "a").write(json.dumps(sys.argv[1:]) + "\\n")
code, out = json.load(open(d + "/replies.json")).get(" ".join(sys.argv[1:3]), [1, ""])
print(out, end="")
sys.exit(code)
''')
        (d / "gh").chmod(0o755)
        p = mock.patch.dict(os.environ, {"PATH": f"{d}:/usr/bin:/bin"}); p.start(); self.addCleanup(p.stop)
        return lambda: [json.loads(l) for l in (d / "calls.jsonl").read_text().splitlines()]

    def test_gh_status_is_no_gh_maintainer_or_reporter(self):
        with mock.patch.dict(os.environ, {"PATH": tempfile.mkdtemp()}): self.assertEqual(fc.fc_toolbug.gh_status(), ("no-gh", None))
        self.fake_gh({"api user": [1, "alice9\n"], "api repos/prodoxx/compose": [0, "true\n"]})
        self.assertEqual(fc.fc_toolbug.gh_status(), ("no-gh", None))
        for perm, state in (([0, "true\n"], "maintainer"), ([0, "false\n"], "reporter"), ([1, "true\n"], "reporter")):
            calls = self.fake_gh({"api user": [0, "alice9\n"], "api repos/prodoxx/compose": perm})
            self.assertEqual(fc.fc_toolbug.gh_status(), (state, "alice9"))
            self.assertEqual(calls(), [["api", "user", "--jq", ".login"], ["api", "repos/prodoxx/compose", "--jq", ".permissions.push"]])

    def test_open_matches_searches_the_symptom(self):
        hit = [{"number": 1, "title": "crew start: hangs", "url": "https://github.com/prodoxx/compose/issues/1"}]
        calls = self.fake_gh({"issue list": [0, json.dumps(hit)]})
        self.assertEqual(fc.fc_toolbug.open_matches("crew start: hangs: at trust"), hit)
        self.assertEqual(fc.fc_toolbug.open_matches("hangs at trust"), hit)
        args, tail = ["issue", "list", "--repo", "prodoxx/compose", "--state", "open", "--search"], ["--json", "number,title,url", "--limit", "5"]
        self.assertEqual(calls(), [args + ["hangs: at trust"] + tail, args + ["hangs at trust"] + tail])
        self.fake_gh({"issue list": [1, "[]"]})
        self.assertEqual(fc.fc_toolbug.open_matches("x: y"), [])

    def test_post_creates_or_comments_and_returns_the_url(self):
        calls = self.fake_gh({"issue create": [0, "Creating issue\nhttps://github.com/prodoxx/compose/issues/2\n\n"],
                              "issue comment": [0, "https://github.com/prodoxx/compose/issues/1#c-9\n"]})
        self.assertEqual(fc.fc_toolbug.post("crew: t", "## Summary\n"), "https://github.com/prodoxx/compose/issues/2")
        self.assertEqual(fc.fc_toolbug.post("crew: t", "b", comment=1), "https://github.com/prodoxx/compose/issues/1#c-9")
        self.assertEqual(calls(), [["issue", "create", "--repo", "prodoxx/compose", "--label", "bug", "--title", "crew: t", "--body", "## Summary\n"],
                                   ["issue", "comment", "1", "--repo", "prodoxx/compose", "--body", "b"]])
        self.fake_gh({"issue create": [1, "https://github.com/prodoxx/compose/issues/3\n"]})
        self.assertIsNone(fc.fc_toolbug.post("t", "b"))

    def test_record_issue_marks_the_projects_newest_entry(self):
        self.assertFalse(fc.fc_toolbug.record_issue("shop", "u"))
        self.log.parent.mkdir(parents=True); lines = ['{"project": "shop", "message": "old"}\n', '{"project":"shop","message":"new"}\n', '{"project": "blog",  "message": "x"}\n']
        self.log.write_text("".join(lines))
        self.assertTrue(fc.fc_toolbug.record_issue("shop", "https://github.com/prodoxx/compose/issues/2"))
        got = self.log.read_text().splitlines(keepends=True)
        self.assertEqual((got[0], got[2]), (lines[0], lines[2]))
        self.assertEqual(json.loads(got[1]), {"project": "shop", "message": "new", "issue": "https://github.com/prodoxx/compose/issues/2"})
        self.assertFalse(fc.fc_toolbug.record_issue("cafe", "u"))


class FileCommand(unittest.TestCase):
    """cmd_tool_bug: post on the maintainer's machine or with --approved, else save a draft; search before every create."""
    RAW, URL = "# crew start: hangs at alice9 prompt\n## Summary\n\nIt hangs. token ghp_abcdefghijklmnopqrstuvwx\n", "https://github.com/prodoxx/compose/issues/2"

    def setUp(self):
        self.home = Path(tempfile.mkdtemp()).resolve()
        self.drafts = self.home / ".compose" / "tool-bugs"
        for p in (mock.patch.object(fc.fc_crew, "TOOL_BUGS", self.home / ".compose" / "tool-bugs.jsonl"),
                  mock.patch.object(fc.fc_config, "CONFIG_PATH", self.home / ".compose" / "config.json"),
                  mock.patch.object(fc.fc_toolbug, "environment", return_value="- OS: test")):
            p.start(); self.addCleanup(p.stop)

    def run_cmd(self, state, raw=RAW, matches=(), url=URL, **kw):
        (self.home / "b.md").write_text(raw)
        a = SimpleNamespace(**{**dict(repo=".", project="shop", action="file", body=str(self.home / "b.md"), comment=None, new=False, approved=False), **kw})
        self.m = {n: mock.patch.object(fc.fc_toolbug, n, return_value=v).start() for n, v in dict(
            gh_status=(state, None if state == "no-gh" else "alice9"), open_matches=list(matches), post=url, record_issue=True).items()}
        self.addCleanup(mock.patch.stopall)
        status = 0
        with mock.patch("sys.stdout", io.StringIO()) as out:
            try: fc.fc_toolbug.cmd_tool_bug(a)
            except SystemExit as e: status = 1 if isinstance(e.code, str) else e.code
        return status, out.getvalue()

    def draft(self, out, login="alice9"):
        [path] = list(self.drafts.glob("*.md"))
        self.assertRegex(path.name, r"^\d{8}-\d{6}\.md$"); self.assertIn(str(path), out)
        title, body = fc.fc_toolbug.issue_text(self.RAW, login)
        self.assertEqual(path.read_text(), "# " + title + "\n\n" + body); self.assertNotIn("ghp_abc", path.read_text())
        return path

    def test_a_reporter_or_no_gh_saves_a_scrubbed_draft_and_posts_nothing(self):
        for state, kw in (("reporter", {}), ("no-gh", {}), ("no-gh", {"approved": True})):
            with self.subTest(state, **kw):
                for f in self.drafts.glob("*.md"): f.unlink()
                status, out = self.run_cmd(state, **kw)
                self.assertEqual(status, 0); self.m["post"].assert_not_called()
                path = self.draft(out, None if state == "no-gh" else "alice9")
                self.assertIn(f"--body {path} --approved", out); self.assertEqual("gh auth login" in out, state == "no-gh")

    def test_matches_are_listed_and_exit_2_without_posting(self):
        status, out = self.run_cmd("maintainer", matches=[{"number": 7, "title": "crew start hangs", "url": "https://x/7"}])
        self.assertEqual(status, 2); self.m["post"].assert_not_called()
        self.assertIn("#7 crew start hangs https://x/7", out); self.assertIn("--comment", out); self.assertIn("--new", out)

    def test_post_prints_and_records_the_url(self):
        for state, kw, comment in (("maintainer", {}, None), ("maintainer", {"new": True}, None), ("reporter", {"approved": True, "comment": 3}, 3)):
            with self.subTest(**kw):
                status, out = self.run_cmd(state, matches=[{"number": 7, "title": "t", "url": "u"}] if kw else [], **kw)
                self.assertEqual(status, 0); self.assertIn(self.URL, out)
                title, body = fc.fc_toolbug.issue_text(self.RAW, "alice9")
                self.assertEqual((self.m["post"].call_args.args[:2], self.m["post"].call_args.kwargs.get("comment")), ((title, body), comment))
                self.m["record_issue"].assert_called_once_with("shop", self.URL)
                if comment: self.m["open_matches"].assert_not_called()

    def test_a_failed_post_saves_the_draft_and_exits_1(self):
        status, out = self.run_cmd("maintainer", url=None)
        self.assertEqual(status, 1); self.draft(out); self.m["record_issue"].assert_not_called()

    def test_a_body_without_a_title_line_exits_1(self):
        self.assertEqual(self.run_cmd("maintainer", raw="no title\n")[0], 1); self.m["post"].assert_not_called()


class Cli(unittest.TestCase):
    """`compose tool-bug` and `compose toolsmith` through the real entry point."""

    def run_main(self, *args):
        with mock.patch.object(sys, "argv", ["compose", *args]), mock.patch.object(fc.fc_config, "apply_config", return_value="default"), \
                mock.patch.object(fc.fc_toolbug, "cmd_tool_bug") as bug, mock.patch.object(fc.fc_briefs, "cmd_toolsmith") as smith, \
                mock.patch("sys.stderr", io.StringIO()):
            fc.main()
        return bug, smith

    def test_tool_bug_passes_its_arguments(self):
        bug, smith = self.run_main("tool-bug", "file", "--project", "shop", "--body", "b.md", "--comment", "3")
        a = bug.call_args.args[0]
        self.assertEqual((a.action, a.project, a.body, a.comment, a.new, a.approved), ("file", "shop", "b.md", 3, False, False))
        smith.assert_not_called()
        a = self.run_main("tool-bug", "file", "--project", "shop", "--body", "b.md", "--new", "--approved")[0].call_args.args[0]
        self.assertEqual((a.comment, a.new, a.approved), (None, True, True))

    def test_tool_bug_usage_errors(self):
        self.run_main("tool-bug", "file", "--project", "shop", "--body", "b.md")[0].assert_called_once()
        for args in (["file", "--body", "b.md", "--comment", "3", "--new"], ["file"], ["post", "--body", "b.md"], ["file", "--body", "b.md", "--comment", "x"]):
            with self.subTest(args), self.assertRaises(SystemExit) as cm:
                self.run_main("tool-bug", "--project", "shop", *args)
            self.assertEqual(cm.exception.code, 2)

    def test_toolsmith_takes_only_repo_and_project(self):
        bug, smith = self.run_main("toolsmith", "--repo", ".", "--project", "shop")
        self.assertEqual((smith.call_args.args[0].repo, smith.call_args.args[0].project), (".", "shop"))
        bug.assert_not_called()
        with self.assertRaises(SystemExit) as cm:
            self.run_main("toolsmith", "--project", "shop", "--body", "b.md")
        self.assertEqual(cm.exception.code, 2)

    def test_help_gives_each_a_one_line_summary(self):
        with mock.patch("sys.stdout", io.StringIO()) as out, self.assertRaises(SystemExit):
            self.run_main("--help")
        lines = {l.split()[0]: l.split()[1:] for l in out.getvalue().splitlines() if l.startswith("    ") and l.split()}
        for name in ("tool-bug", "toolsmith"):
            with self.subTest(name):
                self.assertTrue(lines.get(name))
