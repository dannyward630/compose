import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
import hermetic  # first: no test sees the real home
import html, json, os, re, threading, unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from textual.app import App
from textual.widgets import Button

from compose_setup import app as setup_app
from compose_setup.finish import FinishScreen
from compose_setup.keys import KeysScreen
import fc_config, fc_finish, fc_herdrconf, fc_keys, fc_steprun, fc_steps

ROOT = Path(__file__).resolve().parents[2]
ROWS = tuple((name, lambda c: (False, ""), "true", level, False, mode) for name, level, mode in (
    ("gh", "required", "run"), ("figma", "designer", "run"), ("brew", "default", "interactive"),
    ("pi", "required", "run"), ("token", "designer", "run")))  # token stays unchosen
STATES = {"figma": ("done", ""), "brew": ("ok", ""), "pi": ("failed", "boom line")}


async def until(pilot, cond):
    for _ in range(100):
        if cond(): return
        await pilot.pause(0.05)

def lines(app):  # the screen's text, one string per line
    out = {}
    for n, t in re.findall(r'clip-path="url\(#[^"]*-line-(\d+)\)"[^>]*>([^<]*)</text>', app.export_screenshot()):
        out[int(n)] = out.get(int(n), "") + html.unescape(t).replace("\xa0", " ")
    return [out[n].rstrip() for n in sorted(out)]

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


class AppFixes(unittest.IsolatedAsyncioTestCase):
    def setUp(self):  # hermetic gave this test a temp HOME and COMPOSE_CONFIG; a second workspace is active there
        cfg = Path(os.environ["COMPOSE_CONFIG"])
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps({"workspace": "work", "workspaces": {"work": {}}}))
        rows = tuple((n, lambda c: (False, ""), "true", level, False, "run") for n, level in (("gh", "required"), ("figma", "designer"), ("uv", "default")))
        self.status, self.herdr = mock.Mock(return_value=dict.fromkeys(("openrouter", "typesafe", "linear", "figma"), False)), mock.Mock(return_value=("ok", []))
        self.finish = mock.Mock(return_value=(["not finished"], 3))
        for p in (mock.patch.object(fc_config, "CONFIG_PATH", cfg), mock.patch.object(fc_config, "AUTH_PATH", cfg.parent / "auth.json"),
                  mock.patch.object(fc_steps, "STEPS", rows), mock.patch.object(fc_steprun, "run_step", return_value=("ok", "")),
                  mock.patch.object(fc_herdrconf, "apply_herdr_config", self.herdr), mock.patch.object(fc_keys, "key_status", self.status),
                  mock.patch.object(fc_keys, "linear_connected", return_value=None), mock.patch.object(fc_finish, "finish", self.finish)):
            p.start(); self.addCleanup(p.stop)

    async def start(self, app, pilot):
        await pilot.press(key(app, "start")); await until(pilot, lambda: isinstance(app.screen, KeysScreen))

    async def test_keys_get_the_active_workspace_and_herdr_is_left_to_finish(self):
        app = setup_app.SetupApp(ROOT)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause(); await self.start(app, pilot)
            app.screen.dismiss(([], [])); await until(pilot, lambda: isinstance(app.screen, FinishScreen) and app.screen.query(Button))
            app.screen.dismiss("keys"); await until(pilot, lambda: isinstance(app.screen, KeysScreen))
            self.assertGreaterEqual(self.status.call_count, 2); self.assertEqual({c.args[1] for c in self.status.call_args_list}, {"work"})
            self.herdr.assert_not_called()

    async def test_ctrl_q_exits_1_until_finish_shows_a_code(self):
        for stage, code, want in (("steps", 3, 1), ("keys", 3, 1), ("loading", 3, 1), ("finish", 3, 3), ("finish", 0, 0)):
            with self.subTest(stage, code=code):
                self.finish.return_value, gate = (["done"], code), threading.Event()  # "loading": finish holds until the app has quit
                self.finish.side_effect = (lambda *a, g=gate, c=code, **k: g.wait(5) and (["done"], c)) if stage == "loading" else None
                app = setup_app.SetupApp(ROOT)
                async with app.run_test(size=(80, 24)) as pilot:
                    await pilot.pause()
                    if stage != "steps": await self.start(app, pilot)
                    if stage in ("loading", "finish"): app.screen.dismiss(([], [])); await until(pilot, lambda a=app, s=stage: isinstance(a.screen, FinishScreen) and (s == "loading" or a.screen.query(Button)))
                    self.assertIn("quit", (app.active_bindings["ctrl+q"].binding.description or "").lower())
                    await pilot.press("ctrl+q"); gate.set()
                self.assertEqual(app.return_value, want)

    async def test_s_undoes_a_skip_and_the_reason_line_survives_start(self):
        app = setup_app.SetupApp(ROOT)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause(); before = lines(app)
            await pilot.press(key(app, "skip")); skipped = lines(app)
            reason = [l for l in skipped if l not in before]
            self.assertGreaterEqual(len(reason), 2)  # the gh row's state and its reason line
            await pilot.press(key(app, "skip")); self.assertEqual(lines(app), before)
            await pilot.press("down", key(app, "skip"), key(app, "skip")); self.assertEqual(lines(app), before)  # figma: unchosen again
            await pilot.press("up", key(app, "skip")); self.assertEqual(lines(app), skipped)
            await self.start(app, pilot); app.pop_screen(); await pilot.pause()
            for l in reason: self.assertIn(l, lines(app))
