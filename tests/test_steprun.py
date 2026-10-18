import hermetic  # first: no test sees the real home
import sys, tempfile, unittest
from pathlib import Path
from unittest import mock
import os
os.environ["HERDR_ENV"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import fc_config, fc_keys, fc_links, fc_pi, fc_steps, fc_steprun


class RunStep(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.ran, self.has = self.tmp / "ran", lambda c: (self.ran.exists(), "")
        for p in (mock.patch.object(fc_steps, "check", lambda row, c: row[1](c)), mock.patch.object(fc_config, "WORKSPACE", "acme"),
                  mock.patch.object(fc_config, "apply_config", return_value="acme"), mock.patch.object(fc_config, "OPENROUTER_KEY", "sk-or-test")):
            self.enterContext(p)

    def step(self, check, install=None, level="required", claude_row=False, mode="run", yes=False, claude=True, terminal=False, name="pi"):
        state, line = fc_steprun.run_step((name, check, install or f"touch {self.ran}", level, claude_row, mode), self.tmp, yes, claude, terminal)
        self.assertNotIn("sk-or-test", line)
        return state, line

    def test_present_tool_is_reused_and_never_run(self):
        self.assertEqual((self.step(lambda c: (True, ""), claude_row=True, claude=False)[0], self.ran.exists()), ("ok", False))

    def test_claude_missing_and_designer_under_yes(self):
        state, line = self.step(self.has, claude_row=True, claude=False)
        skipped = self.step(self.has, level="designer", yes=True)[0]
        self.assertEqual((state, "waiting on Claude Code" in line, skipped, self.ran.exists()), ("claude", True, "skipped", False))

    def test_manual_and_interactive_without_terminal_show_the_command(self):
        for mode in ("manual", "interactive"):
            state, line = self.step(self.has, mode=mode)
            self.assertEqual((state in ("manual", "skipped"), f"touch {self.ran}" in line), (True, True))
        self.assertFalse(self.ran.exists())

    def test_key_row_uses_the_skipped_line_for_the_active_workspace(self):
        with mock.patch.object(fc_keys, "skipped_line", return_value="no key; run compose setup") as skipped:
            state, line = self.step(lambda c: (False, ""), mode="key", name="OpenRouter key", yes=True)
        skipped.assert_called_once_with("openrouter", "acme")
        self.assertEqual((state in ("manual", "skipped"), "no key; run compose setup" in line, self.ran.exists()), (True, True, False))

    def test_run_and_interactive_with_terminal_install_then_recheck(self):
        self.assertEqual(self.step(self.has)[0], "done")
        self.ran.unlink()  # an interactive row with a terminal runs the same way, inheriting it
        self.assertEqual(self.step(self.has, mode="interactive", terminal=True)[0], "done")

    def test_failing_install_reports_its_last_error_line(self):
        state, line = self.step(self.has, install="echo first >&2; echo boom >&2; exit 3")
        self.assertEqual((state, "boom" in line, "first" in line), ("failed", True, False))
        self.assertEqual(self.step(self.has, install="true")[0], "failed")  # the install exits 0 but the check still fails

    def test_write_rows_call_their_writers_then_recheck(self):
        with mock.patch.dict(fc_steprun.WRITERS, {"compose CLI link": lambda c: self.ran.touch() or ["linked"]}):
            self.assertEqual(self.step(self.has, install="compose setup", mode="write", name="compose CLI link")[0], "done")
        with mock.patch.object(fc_links, "relink_owned", return_value=["linked"]) as relink, mock.patch.object(fc_pi, "declare_provider", return_value="declared") as declare, \
             mock.patch.object(fc_pi, "write_text_model", return_value="written") as text:
            for name in ("bp link", "pi openrouter-fast provider", "TEXT_MODEL lines"):
                self.assertEqual(self.step(lambda c: (False, ""), install="compose setup", mode="write", name=name)[0], "failed")
        relink.assert_called_once_with(self.tmp)
        declare.assert_called_once_with(fc_pi.PI_MODELS)
        text.assert_called_once_with(fc_config.ENV_FILE)
