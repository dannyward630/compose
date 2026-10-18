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
    """run_plain walks every row without prompting, then herdr's config, the PATH line, and finish; it returns finish's code."""
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
        for line, (state, name) in zip(lines, [("done", "gh"), ("claude", "superpowers"), ("skipped", "OpenRouter key")]):
            self.assertTrue(line.startswith(state) and name in line, line)
        rest = "\n".join(lines[3:])
        self.assertLess(rest.index("herdr: set ui.toast.delivery"), rest.index(PATH_LINE))
        self.assertEqual(lines[-2:], ["ready", "next: compose init"])
        self.herdr.assert_called_once_with(self.home / ".config/herdr/config.toml", self.checkout / "setup" / "herdr.toml")
        self.finish.assert_called_once_with([("gh", "done"), ("superpowers", "claude"), ("OpenRouter key", "skipped")], False)
        self.assertEqual({s[1:] for s in self.steps}, {(self.checkout, False, False, False)})

    def test_claude_on_path_reaches_every_row(self):
        (self.tmp / "bin" / "claude").write_text("#!/bin/sh\n"), (self.tmp / "bin" / "claude").chmod(stat.S_IRWXU)
        self.run_plain(["ok"] * 3)
        self.assertEqual([s[1:] for s in self.steps], [(self.checkout, True, True, False)] * 3)

    def test_second_run_writes_nothing(self):
        for _ in range(2):
            got, lines = self.run_plain(["ok"] * 3, herdr=("ok", []), path=None, code=0)
        self.assertEqual((got, [l.split()[0] for l in lines[:3]]), (0, ["ok"] * 3))
        self.assertNotIn(PATH_LINE, "\n".join(lines))
        self.assertEqual(sorted(p.name for p in self.tmp.rglob("*")), ["bin"])
