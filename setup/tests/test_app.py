import html, re, unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from textual.app import App

from compose_setup import app as setup_app
from compose_setup.finish import FinishScreen
from compose_setup.keys import KeysScreen
import fc_finish, fc_herdrconf, fc_keys, fc_steprun, fc_steps

ROOT = Path(__file__).resolve().parents[2]
ROWS = tuple((name, lambda c: (False, ""), "true", level, False, mode) for name, level, mode in (
    ("gh", "required", "run"), ("figma", "designer", "run"), ("brew", "default", "interactive"),
    ("pi", "required", "run"), ("token", "designer", "run")))  # token stays unchosen
STATES = {"figma": ("done", ""), "brew": ("ok", ""), "pi": ("failed", "boom line")}


async def until(pilot, cond):
    for _ in range(100):
        if cond(): return
        await pilot.pause(0.05)

def key(app, word):  # the footer key whose description names the action
    return next(k for k, b in app.active_bindings.items() if word in (b.binding.description or "").lower())


class GuidedSetup(unittest.IsolatedAsyncioTestCase):
    async def test_steps_then_herdr_keys_and_finish(self):
        log, suspended = [], []
        def run_step(row, checkout, yes, claude, terminal):
            log.append((row[0], terminal, bool(suspended))); return STATES[row[0]]
        @contextmanager
        def suspend(app):
            suspended.append(1); yield; suspended.pop()
        with mock.patch.object(fc_steps, "STEPS", ROWS), mock.patch.object(App, "suspend", suspend), mock.patch.object(fc_steprun, "run_step", run_step), \
                mock.patch.object(fc_herdrconf, "apply_herdr_config", side_effect=lambda *a: log.append("herdr") or ("ok", [])), \
                mock.patch.object(fc_keys, "key_status", return_value=dict.fromkeys(("openrouter", "typesafe", "linear", "figma"), False)), \
                mock.patch.object(fc_keys, "linear_connected", return_value=None), mock.patch.object(fc_finish, "finish", return_value=(["all set"], 0)):
            app = setup_app.SetupApp(ROOT)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                text = html.unescape("".join(re.findall(r">([^<>]*)</text>", app.export_screenshot()))).replace("\xa0", " ")
                for name, _, _, level, _, _ in ROWS: self.assertRegex(text, rf"\b{name}\b.*\b{level}\b")
                await pilot.press(key(app, "skip"), "down", key(app, "choose"), key(app, "start"))
                await until(pilot, lambda: isinstance(app.screen, KeysScreen))
                self.assertEqual(log, [("figma", False, False), ("brew", True, True), ("pi", False, False), "herdr"])
                for _ in range(2):  # Back to keys returns to KeysScreen, then finishes again without rerunning anything
                    app.screen.dismiss(([], ["openrouter"])); await until(pilot, lambda: isinstance(app.screen, FinishScreen))
                    self.assertEqual([r for r in app.screen.results if r[0] != "token"], [("gh", "skipped"), ("figma", "done"), ("brew", "ok"), ("pi", "failed")])
                    app.screen.dismiss("keys"); await until(pilot, lambda: isinstance(app.screen, KeysScreen))
                self.assertEqual(log[-1], "herdr"); self.assertEqual(log.count("herdr"), 1)
                app.exit(4)
            self.assertEqual(app.return_value, 4)

    def test_main_runs_this_checkout_and_exits_with_its_code(self):
        with mock.patch.object(setup_app.SetupApp, "run", autospec=True, return_value=4) as run, self.assertRaises(SystemExit) as cm:
            setup_app.main()
        self.assertEqual(cm.exception.code, 4); self.assertEqual(Path(run.call_args.args[0].checkout).resolve(), ROOT)
