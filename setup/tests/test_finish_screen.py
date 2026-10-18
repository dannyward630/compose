import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
import hermetic  # first: no test sees the real home
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
    async def finish(self, lines, code, press, check=lambda app: None):
        gate = threading.Event()
        fake = lambda results, yes: (gate.wait(5), (lines, code))[1]
        with mock.patch("fc_finish.finish", side_effect=fake) as finish:
            async with (app := Host()).run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                self.assertTrue(app.screen.query(LoadingIndicator) and style_at(app, "checking your model…"))
                gate.set(); await app.workers.wait_for_complete()
                await pilot.pause()
                buttons = {str(b.label): b for b in app.screen.query(Button)}
                self.assertTrue(all(b.region.area and app.screen.region.contains_region(b.region) for b in buttons.values()))
                check(app); buttons[press].press()
                await pilot.pause()
        finish.assert_called_once_with(RESULTS, yes=False)
        return app, set(buttons)

    async def test_done_exits_0_and_stays_visible_under_long_output(self):
        app, buttons = await self.finish([PRESET] + [f"step {i}" for i in range(30)] + ["compose is ready"], 0, "Done")
        self.assertEqual((buttons, app.return_value), ({"Done"}, 0))

    async def test_lines_wrap_and_are_styled_by_kind(self):
        def check(app):  # read while the app runs: Quit closes it
            styles = [style_at(app, t) for t in ("compose is ready", "setup is not finished", "Create the", "TAILWORD")]
            self.assertTrue(all(styles) and len(set(styles[:3])) == 3, styles)
        await self.finish(["compose is ready", "setup is not finished", PRESET], 1, "Quit", check)

    async def test_missing_keys_go_back_to_keys(self):
        app, buttons = await self.finish(["OpenRouter key skipped", "setup is not finished"], 1, "Back to keys")
        self.assertEqual((buttons, app.result), ({"Back to keys", "Quit"}, "keys"))

    async def test_claude_missing_quits_with_1_and_no_back_to_keys(self):
        app, buttons = await self.finish(["Claude Code is missing: install it, then run compose setup again"], 1, "Quit")
        self.assertEqual((buttons, app.return_value), ({"Quit"}, 1))


HERDR = ["/h/config.toml is a symlink or not writable, so compose left it alone; set these lines by hand:",
         "[ui.sound]", "enabled = false", "[ui.toast]", 'delivery = "off"']
PATH_LINES = ["~/.local/bin is not on your PATH; add this line to your shell profile:", 'export PATH="$HOME/.local/bin:$PATH"']
LINEAR = ("No Linear key: without it the CLI's Linear moves and sync --from-linear cannot run. Add one later:\n"
          "  pbpaste | compose workspace key default --linear\n  or connect the claude.ai Linear connector")
OUTCOME = ["failed: pi", "waiting on Claude Code: superpowers", "run by hand: git, ~/.local/bin on PATH", "skipped: uv"]
ENDING = OUTCOME + HERDR + PATH_LINES + ["implementer glm ok", "plain line", LINEAR, "setup is not finished"]


class FinishLook(unittest.IsolatedAsyncioTestCase):
    finish = FinishScreenTest.finish

    async def test_new_lines_take_a_warning_style_and_commands_keep_their_row(self):
        def check(app):
            ok, err, plain = (style_at(app, t) for t in ("implementer glm ok", "setup is not finished", "plain line"))
            self.assertEqual(style_at(app, "No Linear key"), err)
            for text in OUTCOME + HERDR + PATH_LINES:
                self.assertNotIn(style_at(app, text[:30]), (None, ok, err, plain), text)
            rows = [s.text.strip() for s in app.screen._compositor.render_strips()]
            for command in ("pbpaste | compose workspace key default --linear", "or connect the claude.ai Linear connector"):
                self.assertTrue(any(r.startswith(command) for r in rows), (command, rows))
        await self.finish(ENDING, 1, "Quit", check)

    async def test_long_ending_has_focus_a_scrollbar_and_scrolls_from_the_keyboard(self):
        app = Host()

        async def run(pilot):
            area = app.focused
            self.assertTrue(area and area.max_scroll_y > 0 and area.show_vertical_scrollbar, area)
            bar = area.vertical_scrollbar.region
            self.assertTrue(bar.area and app.screen.region.contains_region(bar), bar)
            seen = [area.scroll_y]
            for key in ("down", "pagedown", "up", "pageup"):
                await pilot.press(key); await pilot.pause()
                seen.append(area.scroll_y)
            self.assertTrue(seen[0] < seen[1] < seen[2] and seen[2] > seen[3] > seen[4] == 0, seen)
            await pilot.press("tab"); await pilot.pause()
            self.assertIsInstance(app.focused, Button)
            self.assertTrue(app.screen.region.contains_region(app.focused.region))

        with mock.patch("fc_finish.finish", return_value=(ENDING + [f"step {i}" for i in range(30)], 1)):
            async with app.run_test(size=(80, 24)) as pilot:
                await app.workers.wait_for_complete(); await pilot.pause()
                await run(pilot)


NODE = "/Users/reggie/.nvm/versions/node/v22/lib/node_modules/@earendil-works/pi-coding-agent/dist/index.js"
LONG = f"failed: pi: npm cannot link {NODE} into ~/.local/bin, run it again."
SLASHES = "/opt/homebrew/Cellar/herdr/0.9.3/libexec/share/herdr/integrations/claude-code/" * 2 + "hooks.json"


def wrapped_rows(app, line):
    """The rows the line renders as in #lines, each with what of the line is left after it."""
    region = app.screen.query_one("#lines").scrollable_content_region
    strips = app.screen._compositor.render_strips()
    rows = [strips[y].text[region.x:region.right].strip() for y in range(region.y, region.bottom)]
    start = next(i for i, row in enumerate(rows) if len(row) > 9 and line.startswith(row))
    out, rest = [], line
    for row in rows[start:]:
        if not rest.startswith(row):
            break
        rest = rest[len(row):]
        out.append((row, rest))
        rest = rest.lstrip(" ")
        if not rest:
            break
    return out, rest


class FinishWrap(unittest.IsolatedAsyncioTestCase):
    finish = FinishScreenTest.finish

    def assert_breaks_clean(self, app, line):
        rows, rest = wrapped_rows(app, line)
        self.assertEqual(rest, "", (line, rows))
        self.assertGreater(len(rows), 1, rows)
        for row, after in rows[:-1]:
            self.assertTrue(row.endswith("/") or after.startswith(" "), (row, after))

    async def test_long_path_lines_show_in_full_and_break_at_a_space_or_after_a_slash(self):
        def check(app):
            self.assertEqual(len(LONG), 160)
            self.assert_breaks_clean(app, LONG)
            self.assert_breaks_clean(app, SLASHES)  # no space at all: only slashes to break after
            head, tail, plain = (style_at(app, t) for t in ("failed: pi", "run it again", "plain line"))
            self.assertEqual(head, tail)  # every row of the line keeps its kind's style
            self.assertNotEqual(head, plain)
            self.assertEqual(style_at(app, "hooks.json"), style_at(app, "/opt/homebrew"))
        app, buttons = await self.finish([LONG, SLASHES, "plain line", "setup is not finished"], 1, "Quit", check)
        self.assertEqual((buttons, app.return_value), ({"Back to keys", "Quit"}, 1))

    async def test_a_long_ending_with_long_paths_still_scrolls_and_ends_with_done(self):
        app, buttons = await self.finish([LONG] * 3 + [SLASHES] + [f"step {i}" for i in range(30)] + ["compose is ready"],
                                         0, "Done", lambda app: self.assert_breaks_clean(app, LONG))
        self.assertEqual((buttons, app.return_value), ({"Done"}, 0))

    test_long_ending_keeps_focus_a_scrollbar_and_keyboard_scrolling = FinishLook.test_long_ending_has_focus_a_scrollbar_and_scrolls_from_the_keyboard


LOGIN = "Use /login to log into a provider via OAuth or API key."
SENTENCE = "pi says: set retries = 3 in settings.json before the next run"


class LineKinds(unittest.IsolatedAsyncioTestCase):
    maxDiff = None
    finish = FinishScreenTest.finish

    def test_kind_follows_what_the_line_says(self):
        kinds = {
            LOGIN: "", SENTENCE: "", "Set your API key in pi, then run it again": "",
            "  pbpaste | compose workspace key default --linear": "", "Now pi is linked": "",
            "a = b is what the docs say": "",
            "No OpenRouter key: the implementer cannot run": "error", "No TypeSafe key: x": "error",
            "setup is not finished: add the keys": "error", "pi is missing": "error",
            "enabled = false": "warning", 'delivery = "off"': "warning", "  openrouter-fast.model = glm": "warning",
            "[ui.sound]": "warning", 'export PATH="$HOME/.local/bin:$PATH"': "warning",
            "waiting on Claude Code: superpowers": "warning", "failed: pi": "failed",
            "compose is ready": "success", "implementer glm ok": "success",
        }
        self.assertEqual({line: FinishScreen._kind(line) for line in kinds}, kinds)

    async def test_rendered_styles_follow_the_kind(self):
        def check(app):
            plain, err, warn = (style_at(app, t) for t in ("plain line", "setup is not finished", "enabled = false"))
            self.assertEqual([style_at(app, t[:30]) for t in (LOGIN, SENTENCE)], [plain, plain])
            self.assertEqual([style_at(app, t) for t in ("No OpenRouter key", "pi is missing")], [err, err])
            self.assertEqual(style_at(app, 'delivery = "off"'), warn)
            self.assertNotIn(warn, (plain, err))
            self.assertNotEqual(plain, err)
        lines = [LOGIN, SENTENCE, "plain line", "No OpenRouter key: add one later", "pi is missing",
                 "enabled = false", 'delivery = "off"', "setup is not finished"]
        await self.finish(lines, 1, "Quit", check)
