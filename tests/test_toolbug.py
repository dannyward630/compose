import importlib.machinery, importlib.util, json, os, subprocess, sys, tempfile, unittest
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
                         "- claude: 2.1.302 (Claude Code)", "- herdr: herdr 0.9.1", "- graft: not installed", "- gh: gh version 2.94.0 (2026-09-01)"])
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


class FileCommand(unittest.TestCase):
    """cmd_tool_bug: post on the maintainer's machine or with --approved, else save a draft; search before every create."""


class Cli(unittest.TestCase):
    """`compose tool-bug` and `compose toolsmith` through the real entry point."""
