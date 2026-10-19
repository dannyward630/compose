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

class Ask(unittest.TestCase):
    def ask(self, fn, *args, answers=(), getpass=None):
        out = Out(); out.tty = False
        with mock.patch("builtins.input", side_effect=list(answers)) as ask, \
             mock.patch("getpass.getpass", side_effect=getpass) as gp, \
             mock.patch("sys.stdout", out), mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
            got = fn(*args)
        return got, [c.args[0] for c in (gp if getpass else ask).call_args_list], out.getvalue()

    def test_select_numbers_options_and_returns_the_index(self):
        got, prompts, shown = self.ask(fc_prompt.select, "How?", ["a", "b", "c"], answers=["3"])
        self.assertEqual((got, prompts, shown), (2, ["│  number [1]: "], "◆  How?\n│  1) a\n│  2) b\n│  3) c\n"))
        for answer in ("", EOFError):
            with self.subTest(answer=answer):
                got, prompts, _ = self.ask(fc_prompt.select, "How?", ["a", "b", "c"], 1, answers=[answer])
                self.assertEqual((got, prompts), (1, ["│  number [2]: "]))

    def test_select_reads_again_until_a_number_in_range(self):
        bad = ["0", "4", "two", "-1", "1.5"]
        got, prompts, shown = self.ask(fc_prompt.select, "How?", ["a", "b", "c"], answers=[*bad, "2"])
        self.assertEqual((got, prompts), (1, ["│  number [1]: "] * 6))
        self.assertEqual(shown, "◆  How?\n│  1) a\n│  2) b\n│  3) c\n" + "│  type a number from 1 to 3\n" * 5)

    def test_confirm_reads_yes_or_no_in_any_case_and_spacing(self):
        for answer, want in (("y", True), (" YES ", True), ("Yes", True), ("n", False), (" No ", False), ("nO", False)):
            for default in (True, False):
                with self.subTest(answer=answer, default=default):
                    self.assertEqual(self.ask(fc_prompt.confirm, "Go?", default, answers=[answer])[0], want)

    def test_confirm_defaults_on_enter_and_end_of_input(self):
        for default, prompt in ((True, "◆  Go? (Y/n) "), (False, "◆  Go? (y/N) ")):
            for answer in ("", EOFError):
                with self.subTest(default=default, answer=answer):
                    self.assertEqual(self.ask(fc_prompt.confirm, "Go?", default, answers=[answer])[:2],
                                     (default, [prompt]))

    def test_confirm_reads_again_on_anything_else(self):
        got, prompts, _ = self.ask(fc_prompt.confirm, "Go?", False, answers=["maybe", "ye", "yess", "y"])
        self.assertEqual((got, prompts), (True, ["◆  Go? (y/N) "] * 4))

    def test_password_is_hidden_stripped_and_empty_at_end_of_input(self):
        got, prompts, shown = self.ask(fc_prompt.password, "OpenRouter key", getpass=[" sk-or-test-x \n"])
        self.assertEqual((got, prompts), ("sk-or-test-x", ["◆  OpenRouter key: "]))
        self.assertNotIn("sk-or-test-x", shown)
        self.assertEqual(self.ask(fc_prompt.password, "Linear key", getpass=EOFError)[:2], ("", ["◆  Linear key: "]))

if __name__ == "__main__":
    unittest.main()
