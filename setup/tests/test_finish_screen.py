import threading, unittest
from unittest import mock

from textual.app import App
from textual.widgets import Button, LoadingIndicator

from compose_setup.finish import FinishScreen

RESULTS = [("pi", "done"), ("OpenRouter key", "skipped")]
PRESET = "Create the preset glm-5-3-flash-fast at https://openrouter.ai/settings/presets " * 2 + "TAILWORD"


class Host(App[int]):
    def on_mount(self):
        self.push_screen(FinishScreen(RESULTS), lambda r: setattr(self, "result", r))


def style_at(app, text):
    for strip in app.screen._compositor.render_strips():
        col = strip.text.find(text)
        for seg in strip if col >= 0 else ():
            if col < len(seg.text):
                return seg.style.color, seg.style.bgcolor, seg.style.bold
            col -= len(seg.text)


class FinishScreenTest(unittest.IsolatedAsyncioTestCase):
    async def finish(self, lines, code, press):
        gate = threading.Event()
        fake = lambda results, yes: (gate.wait(5), (lines, code))[1]
        with mock.patch("fc_finish.finish", side_effect=fake) as finish:
            async with (app := Host()).run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                self.assertTrue(app.screen.query(LoadingIndicator) and style_at(app, "checking your model…"))
                gate.set()
                await app.workers.wait_for_complete()
                await pilot.pause()
                buttons = {str(b.label): b for b in app.screen.query(Button)}
                self.assertTrue(all(b.region.area and app.screen.region.contains_region(b.region) for b in buttons.values()))
                buttons[press].press()
                await pilot.pause()
        finish.assert_called_once_with(RESULTS, yes=False)
        return app, set(buttons)

    async def test_done_exits_0_and_stays_visible_under_long_output(self):
        app, buttons = await self.finish([PRESET] + [f"step {i}" for i in range(30)] + ["compose is ready"], 0, "Done")
        self.assertEqual((buttons, app.return_value), ({"Done"}, 0))

    async def test_lines_wrap_and_are_styled_by_kind(self):
        app, _ = await self.finish(["compose is ready", "setup is not finished", PRESET], 1, "Quit")
        styles = [style_at(app, t) for t in ("compose is ready", "setup is not finished", "Create the", "TAILWORD")]
        self.assertTrue(all(styles) and len(set(styles[:3])) == 3, styles)

    async def test_missing_keys_go_back_to_keys(self):
        app, buttons = await self.finish(["OpenRouter key skipped", "setup is not finished"], 1, "Back to keys")
        self.assertEqual((buttons, app.result), ({"Back to keys", "Quit"}, "keys"))

    async def test_claude_missing_quits_with_1_and_no_back_to_keys(self):
        app, buttons = await self.finish(["Claude Code is missing: install it, then run compose setup again"], 1, "Quit")
        self.assertEqual((buttons, app.return_value), ({"Quit"}, 1))
