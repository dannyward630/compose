import hermetic  # first: no test sees the real home
import io, json, os, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import fc_init, fc_perms, fc_prompt, fc_steps

NEVER = ("push", "--force", "gh pr merge", "delete-unmerged", "abandon", "stop --force", "Bash(*)", "Bash(compose *)", "Bash(git branch *)")


class Perms(unittest.TestCase):
    """The rules setup proposes for the user's Claude Code settings: narrow, written only on a yes, never over other settings."""
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        p = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        p.start(); self.addCleanup(p.stop)
        self.file = self.home / ".claude" / "settings.json"

    def settings(self, data):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        self.file.write_text(data if isinstance(data, str) else json.dumps(data))

    def offer(self, yes=False, dry=False, answer=True):
        out = io.StringIO()
        with mock.patch.object(fc_prompt, "confirm", return_value=answer) as ask, mock.patch.object(fc_prompt, "note"), redirect_stdout(out):
            lines = fc_perms.offer(yes, dry)
        return lines, ask.call_count

    def test_the_rules_cover_the_roles_calls_and_none_that_must_keep_asking(self):
        rules = [r for r, _ in fc_perms.RULES]
        self.assertEqual(rules, ["Bash(gh pr view *)", "Bash(compose land *)", "Bash(git branch -f compose/*)"])
        self.assertEqual([r for r in rules for n in NEVER if n in r], [])

    def test_a_yes_writes_the_missing_rules_and_keeps_everything_else(self):
        keep = {"env": {"TOKEN": "sk-keep-me"}, "permissions": {"allow": ["Bash(git add:*)"], "deny": ["EnterPlanMode"]}, "model": "sonnet"}
        self.settings(keep)
        self.assertEqual(self.offer(), (["added 3 rules to ~/.claude/settings.json"], 1))
        got = json.loads(self.file.read_text())
        self.assertEqual(got["permissions"]["allow"], ["Bash(git add:*)", *[r for r, _ in fc_perms.RULES]])
        self.assertEqual({**got, "permissions": {**got["permissions"], "allow": ["Bash(git add:*)"]}}, keep)
        self.assertEqual((fc_perms.missing(), self.offer()), ([], ([], 0)))  # nothing more to add, nothing asked

    def test_no_file_gets_one_and_a_partial_set_gets_only_what_is_missing(self):
        self.offer()
        self.assertEqual(json.loads(self.file.read_text())["permissions"]["allow"], [r for r, _ in fc_perms.RULES])
        self.settings({"permissions": {"allow": ["Bash(gh pr view *)"]}})
        self.assertEqual(self.offer()[0], ["added 2 rules to ~/.claude/settings.json"])

    def test_nothing_is_written_without_the_users_yes(self):
        self.settings({"model": "sonnet"})
        before = self.file.read_text()
        for kw, line in (({"answer": False}, "compose doctor warns"), ({"yes": True}, "need your yes"), ({"dry": True}, "would add 3 permission rules to ~/.claude/settings.json")):
            with self.subTest(**kw):
                lines, asked = self.offer(**kw)
                self.assertIn(line, lines[0])
                self.assertEqual((self.file.read_text(), asked), (before, 1 if kw == {"answer": False} else 0))

    def test_a_settings_file_that_is_not_json_is_left_alone(self):
        self.settings("{not json")
        self.assertIn("left ~/.claude/settings.json alone", self.offer()[0][0])
        self.assertEqual(self.file.read_text(), "{not json")

    def test_doctor_warns_while_a_rule_is_missing_and_never_stops_init(self):
        out = io.StringIO()
        with redirect_stdout(out):
            bad = fc_init.check_deps()
        line = next(l for l in out.getvalue().splitlines() if "Claude Code permissions" in l)
        self.assertIn("Bash(gh pr view *)", line)
        self.assertTrue(line.endswith("(install: compose setup) - optional"))
        self.assertNotIn("Claude Code permissions", bad)
        fc_perms.write()
        out = io.StringIO()
        with redirect_stdout(out):
            fc_init.check_deps()
        self.assertNotIn("Claude Code permissions", out.getvalue())
        self.assertEqual([r[5] for r in fc_steps.STEPS if r[0] == fc_perms.NAME], ["perms"])
