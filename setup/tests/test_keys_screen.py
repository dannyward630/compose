import re
import unittest
from unittest import mock

from textual.app import App
from textual.widgets import Button, Input, Static

from compose_setup.keys import KeysScreen
import fc_auth, fc_keys

KINDS = ["openrouter", "typesafe", "linear", "figma"]
REQUIRED = {"openrouter", "typesafe", "linear"}


class Host(App):
    def __init__(self, workspace):
        super().__init__()
        self.workspace, self.result = workspace, None

    def on_mount(self): self.push_screen(KeysScreen(self.workspace), self.done)
    def done(self, result): self.result = result


class KeysScreenTest(unittest.IsolatedAsyncioTestCase):
    async def keys(self, status, connected, typed=(), workspace="default", presses=1):
        saved = []
        def save(kind, value, workspace, framelink_env): saved.append((kind, value, workspace)); return f"saved {kind}"
        state = "key" if status[2] else "connector" if connected else "missing"
        with mock.patch.object(fc_auth, "read_auth", return_value={}), mock.patch.object(fc_keys, "key_status", return_value=dict(zip(KINDS, status))), \
             mock.patch.object(fc_keys, "linear_connected", return_value=connected), mock.patch.object(fc_keys, "linear_state", return_value=state), \
             mock.patch.object(fc_keys, "save_key", side_effect=save), mock.patch.object(fc_keys, "skipped_line", side_effect=lambda k, w: f"skip-{k}-{w}"):
            app = Host(workspace)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                inputs = list(app.screen.query(Input))
                self.assertEqual([i.password for i in inputs], [True] * 4)
                self.assertTrue(all(i.region.right <= 80 and i.region.bottom <= 24 for i in inputs))
                for i, value in zip(inputs, typed):
                    i.focus(); await pilot.press(*value)
                for _ in range(presses):
                    await pilot.click(next(b for b in app.screen.query(Button) if "Continue" in str(b.label))); await pilot.pause()
                text = "" if app.result else "\n".join(str(w.render()) for w in app.screen.query(Static))
                self.assertFalse(any(v and v in text for v in typed))
        return app.result, saved, text

    async def test_statuses_never_show_values(self):
        _, _, text = await self.keys((True, False, False, False), True, presses=0)
        self.assertIn("connector connected", text)
        self.assertEqual((text.count("not set"), len(re.findall(r"(?<!not )\bset\b", text))), (2, 1))

    async def test_continue_saves_non_empty_inputs_only(self):
        result, saved, _ = await self.keys((False, True, False, True), False, ["sk-or-test", "", "lin-test", ""], "work")
        self.assertEqual(saved, [("openrouter", "sk-or-test", "work"), ("linear", "lin-test", "work")])
        self.assertEqual((sorted(result[0]), {"typesafe", "figma"} & set(result[1])), (["linear", "openrouter"], set()))

    async def test_missing_keys_warn_then_second_continue_skips(self):
        result, _, text = await self.keys((False,) * 4, False)
        self.assertEqual((result, [k for k in KINDS if f"skip-{k}-default" in text]), (None, ["openrouter", "typesafe", "linear"]))
        result, saved, _ = await self.keys((False,) * 4, False, presses=2)
        self.assertEqual((result[0], saved, REQUIRED <= set(result[1])), ([], [], True))

    async def test_set_keys_and_linear_connector_continue_at_once(self):
        result, saved, _ = await self.keys((True, True, False, False), True)
        self.assertEqual((result[0], saved, REQUIRED & set(result[1])), ([], [], set()))
