import hermetic  # first: no test sees the real home
import io, os, shutil, stat, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import fc_plain, fc_steps, fc_steprun, fc_herdrconf, fc_finish, fc_links

PATH_LINE = 'export PATH="$HOME/.local/bin:$PATH"'


class Plain(unittest.TestCase):
    """run_plain walks every row without prompting, then finish; it returns finish's code."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        (self.tmp / "bin").mkdir()
        self.checkout, self.home = self.tmp / "checkout", self.tmp / "home"
        self.rows = tuple((n, lambda c: (True, ""), f"touch {self.tmp}/ran", "required", nc, m)
                          for n, nc, m in [("gh", False, "run"), ("superpowers", True, "run"), ("OpenRouter key", False, "key")])
        env = mock.patch.dict(os.environ, {"PATH": str(self.tmp / "bin"), "HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)

    def run_plain(self, states, herdr=("edited", ["herdr: set ui.toast.delivery"]), path=PATH_LINE, code=7, yes=True):
        self.steps, it = [], iter(states)
        def run_step(row, checkout, yes, claude, terminal):
            self.steps.append((row[0], checkout, yes, claude, terminal))
            return next(it), f"{row[0]} detail"
        with mock.patch.object(fc_steps, "STEPS", self.rows), mock.patch.object(fc_steprun, "run_step", run_step), \
             mock.patch.object(fc_herdrconf, "apply_herdr_config", autospec=True, return_value=herdr) as self.herdr, \
             mock.patch.object(fc_links, "path_line", return_value=path), \
             mock.patch.object(fc_finish, "finish", autospec=True, return_value=(["ready", "next: compose init"], code)) as self.finish, \
             redirect_stdout(io.StringIO()) as out:
            got = fc_plain.run_plain(self.checkout, yes)
        return got, out.getvalue().splitlines()

    def test_order_states_and_code(self):
        got, lines = self.run_plain(["done", "claude", "skipped"], yes=False)
        self.assertEqual(got, 7)
        self.assertEqual([l for l in lines if not l.startswith(" ")][:3], ["done gh", "claude superpowers", "skipped OpenRouter key"])
        self.assertEqual(lines[-2:], ["ready", "next: compose init"])
        self.finish.assert_called_once_with([("gh", "done"), ("superpowers", "claude"), ("OpenRouter key", "skipped")], False)
        self.assertEqual({s[1:] for s in self.steps}, {(self.checkout, False, False, False)})

    def test_claude_on_path_reaches_every_row(self):
        (self.tmp / "bin" / "claude").write_text("#!/bin/sh\n"), (self.tmp / "bin" / "claude").chmod(stat.S_IRWXU)
        self.run_plain(["ok"] * 3)
        self.assertEqual([s[1:] for s in self.steps], [(self.checkout, True, True, False)] * 3)

    def test_second_run_writes_nothing(self):
        for _ in range(2):
            got, lines = self.run_plain(["ok"] * 3, herdr=("ok", []), path=None, code=0)
        self.assertEqual((got, [l.split()[0] for l in lines if not l.startswith(" ")][:3]), (0, ["ok"] * 3))
        self.assertNotIn(PATH_LINE, "\n".join(lines))
        self.assertEqual(sorted(p.name for p in self.tmp.rglob("*")), ["bin"])


class PlainSteps(unittest.TestCase):
    """Designer rows are skipped with or without yes; each step prints once; herdr and PATH come only from finish."""
    maxDiff = None
    def setUp(self):
        Plain.setUp(self)
        claude = self.tmp / "bin" / "claude"
        claude.write_text(f'#!/bin/sh\necho "$@" >> {self.tmp}/claude.calls\n'), claude.chmod(stat.S_IRWXU)
        req = lambda n, m: (n, lambda c: (False, ""), "true", "required", False, m)
        des = lambda n, m: (n, lambda c: (False, ""), f"touch {self.tmp}/ran; claude mcp add -s user x", "designer", True, m)
        self.rows = (req("gh", "run"), des("framelink-figma", "run"), req("git", "manual"), req("pi", "run"),
                     des("framelink-figma token", "key"), req("npx", "run"))
        self.details = {"gh": "gh: ok", "git": "run: xcode-select --install", "pi": "boom\nexit 3", "npx": ""}

    def run_plain(self, yes):
        self.steps, states = [], {"gh": "ok", "git": "manual", "pi": "failed", "npx": "done"}
        def run_step(row, checkout, yes, claude, terminal):
            self.steps.append(row[0])
            return states.get(row[0], "done"), self.details.get(row[0], "claude mcp add ran")
        lines = [PATH_LINE, "herdr: set ui.toast.delivery", "ready"]
        with mock.patch.object(fc_steps, "STEPS", self.rows), mock.patch.object(fc_steprun, "run_step", run_step), \
             mock.patch.object(fc_herdrconf, "apply_herdr_config", return_value=("edited", lines[1:2])) as self.herdr, \
             mock.patch.object(fc_links, "path_line", return_value=PATH_LINE) as self.path, \
             mock.patch.object(fc_finish, "finish", autospec=True, return_value=(lines, 5)) as self.finish, \
             redirect_stdout(io.StringIO()) as out:
            got = fc_plain.run_plain(self.checkout, yes)
        return got, out.getvalue().splitlines()

    def test_steps_print_once_and_designer_rows_run_nothing(self):
        for yes in (True, False):
            with self.subTest(yes=yes):
                got, lines = self.run_plain(yes)
                self.assertEqual(lines, [
                    "ok gh", "  gh: ok",
                    "skipped framelink-figma", "  designer extra, skipped",
                    "manual git", "  run: xcode-select --install",
                    "failed pi", "  boom", "  exit 3",
                    "skipped framelink-figma token", "  designer extra, skipped",
                    "done npx",
                    PATH_LINE, "herdr: set ui.toast.delivery", "ready"])
                self.assertEqual((got, self.steps), (5, ["gh", "git", "pi", "npx"]))
                self.assertFalse((self.tmp / "ran").exists() or (self.tmp / "claude.calls").exists())
                self.herdr.assert_not_called(), self.path.assert_not_called()
                self.assertIs(self.finish.call_args.args[1], yes)
