import hermetic  # first: no test sees the real home
import io, os, sys, unittest
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import fc_prompt

class Out(io.StringIO): isatty = lambda self: self.tty

class Frame(unittest.TestCase):
    def shown(self, fn, *args, tty=True, no_color=""):
        out = Out(); out.tty = tty
        with mock.patch("sys.stdout", out), mock.patch.dict(os.environ, {"NO_COLOR": no_color}):
            fn(*args)
        return out.getvalue()

    def test_paint_colours_only_a_terminal_without_no_color(self):
        out = Out(); out.tty = True
        with mock.patch("sys.stdout", out), mock.patch.dict(os.environ, {"NO_COLOR": ""}):
            self.assertEqual(fc_prompt.paint("hi", "32"), "\x1b[32mhi\x1b[0m")
            del os.environ["NO_COLOR"]
            self.assertEqual(fc_prompt.paint("hi", "1"), "\x1b[1mhi\x1b[0m")
            os.environ["NO_COLOR"] = "1"
            self.assertEqual(fc_prompt.paint("hi", "32"), "hi")
            out.tty = False; os.environ["NO_COLOR"] = ""
            self.assertEqual(fc_prompt.paint("hi", "32"), "hi")
        self.assertEqual(out.getvalue(), "")

    def test_plain_lines_with_no_color_and_without_a_terminal(self):
        for kw in ({"no_color": "1"}, {"tty": False}):
            with self.subTest(**kw):
                self.assertEqual(self.shown(fc_prompt.intro, "compose setup", **kw), "┌  compose setup\n│\n")
                self.assertEqual(self.shown(fc_prompt.note, "Keys", ["one", "two"], **kw), "│\n◇  Keys\n│  one\n│  two\n")
                self.assertEqual(self.shown(fc_prompt.step, "gh", "failed", **kw), "◇  gh: failed\n")
                self.assertEqual(self.shown(fc_prompt.outro, "all set", **kw), "│\n└  all set\n")

    def test_colour_codes_on_a_terminal(self):
        self.assertEqual(self.shown(fc_prompt.intro, "compose setup"), "┌  \x1b[1mcompose setup\x1b[0m\n│\n")
        for word, code in (("ok", 32), ("done", 32), ("failed", 31), ("would link", 36), ("would", 36),
                           ("skipped", 33), ("manual", 33), ("claude", 33), ("not ok", 33)):
            with self.subTest(word):
                self.assertEqual(self.shown(fc_prompt.step, "gh", word), f"◇  gh: \x1b[{code}m{word}\x1b[0m\n")

    def test_step_splits_entries_into_bar_lines_and_drops_empty_parts(self):
        lines = ["first\n  indented\n\nlast", "", "\nsecond entry\n"]
        self.assertEqual(self.shown(fc_prompt.step, "pi", "done", lines, no_color="1"),
                         "◇  pi: done\n│  first\n│    indented\n│  last\n│  second entry\n")
        self.assertEqual(self.shown(fc_prompt.step, "pi", "done", ("a",), no_color="1"), "◇  pi: done\n│  a\n")
        self.assertEqual(self.shown(fc_prompt.note, "Empty", [], no_color="1"), "│\n◇  Empty\n")

if __name__ == "__main__":
    unittest.main()
