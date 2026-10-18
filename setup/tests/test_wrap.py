import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
import hermetic  # first: no test sees the real home

from textual.app import App

from compose_setup.wrap import Wrapped, break_paths

PATH = "".join(f"/segment{i:02d}" for i in range(10))  # 100 characters, no space
SENTENCE = "Linked ~/.local/bin/compose to /Users/me/workspace/tools/compose/bin/compose and ~/.compose/config.json is kept"


class BreakPaths(unittest.TestCase):
    def assert_breaks(self, text, width, cut=False):
        lines, pos = break_paths(text, width).split("\n"), 0
        for i, line in enumerate(lines):
            self.assertLessEqual(len(line), width, line)
            self.assertEqual(text[pos : pos + len(line)], line)  # words in order, nothing dropped
            pos += len(line)
            if i < len(lines) - 1 and not (text[pos] in " \n" and (pos := pos + 1)):
                self.assertTrue(line.endswith("/") or (cut and len(line) == width), (line, lines))
        self.assertEqual(pos, len(text))

    def test_breaks_at_the_last_space_or_slash_that_fits(self):
        self.assertEqual(break_paths("one two three four five", 9), "one two\nthree\nfour five")
        self.assertEqual(break_paths("/Users/me/work/tools/compose/bin/compose", 21), "/Users/me/work/tools/\ncompose/bin/compose")
        for width in range(12, 60):
            self.assert_breaks(SENTENCE, width)

    def test_text_that_fits_and_existing_newlines(self):
        self.assertEqual(break_paths("see ~/.compose/auth.json\nok", 24), "see ~/.compose/auth.json\nok")
        self.assertEqual(break_paths("aaa bbb\nccc ddd", 3), "aaa\nbbb\nccc\nddd")
        self.assertEqual([break_paths(SENTENCE, w) for w in (0, -1)], [SENTENCE, SENTENCE])

    def test_a_run_without_space_or_slash_is_cut_at_width(self):
        self.assertEqual(break_paths("x" * 25, 10), "x" * 10 + "\n" + "x" * 10 + "\n" + "x" * 5)
        self.assert_breaks("save to " + "k" * 30 + " now", 12, cut=True)


class Host(App):
    def compose(self):
        yield Wrapped(PATH, id="w")


class WrappedWidget(unittest.IsolatedAsyncioTestCase):
    async def test_breaks_after_slashes_and_again_on_resize(self):
        rows = lambda app: [s.text.rstrip() for s in app.screen._compositor.render_strips() if s.text.strip()]
        async with (app := Host()).run_test(size=(40, 24)) as pilot:
            await pilot.pause()
            self.assertEqual("".join(shown := rows(app)), PATH)
            self.assertTrue(all(r.endswith("/") and len(r) <= 40 for r in shown[:-1]), shown)
            await pilot.resize_terminal(60, 24)
            await pilot.pause()
            self.assertEqual("".join(shown := rows(app)), PATH)
            self.assertTrue(all(r.endswith("/") and len(r) <= 60 for r in shown[:-1]) and len(shown[0]) > 40, shown)
            app.query_one("#w", Wrapped).update(PATH[:70])
            await pilot.pause()
            self.assertEqual(rows(app), ["/segment00/segment01/segment02/segment03/segment04/", "segment05/segment06"])
