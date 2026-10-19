import hermetic  # first: no test sees the real home
import contextlib, inspect, io, os, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
os.environ["HERDR_ENV"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import fc_prompt, fc_steps, fc_steprun, fc_setup

CHECKOUT = Path(fc_setup.__file__).resolve().parents[1]
UV_ARGV = ["run", "--project", str(CHECKOUT / "setup"), "python", "-m", "compose_setup"]

class Exec(Exception): pass
class Out(io.StringIO): isatty = lambda self: self.tty

class Setup(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup); self.home, self.links = Path(os.path.realpath(t.name)), []
        for p in (mock.patch.dict(os.environ, {"HOME": str(self.home)}),
                  mock.patch.object(fc_setup.fc_checks, "owned_links", side_effect=lambda c: self.links)):
            p.start(); self.addCleanup(p.stop)

    def run_setup(self, yes=False, stdin=True, stdout=True, uv=True):
        out, err = Out(), io.StringIO(); out.tty = stdout
        which = lambda tool, *a, **k: "/fake/uv" if uv and tool == "uv" else None
        with mock.patch.object(sys, "stdin", SimpleNamespace(isatty=lambda: stdin)), mock.patch.object(sys, "stdout", out), \
             mock.patch.object(sys, "stderr", err), mock.patch.object(fc_setup.shutil, "which", side_effect=which), \
             mock.patch.object(fc_setup.os, "execvp", side_effect=Exec) as ex, mock.patch.object(fc_setup.os, "chdir") as cd, \
             mock.patch.object(fc_setup.fc_plain, "run_plain", return_value=3) as plain, self.assertRaises((SystemExit, Exec)) as r:
            fc_setup.cmd_setup(SimpleNamespace(yes=yes))
        return r.exception, out.getvalue() + err.getvalue(), ex, cd, plain

    def assert_leftover(self):
        e, text, ex, cd, plain = self.run_setup()  # a terminal with uv: only the leftover stops the exec
        self.assertEqual((type(e), e.code, len(text.strip().splitlines())), (SystemExit, 1, 1))
        self.assertIn(str(CHECKOUT / "bin" / "migrate-to-compose.sh"), text); ex.assert_not_called(); cd.assert_not_called(); plain.assert_not_called()

    def test_fast_coding_dir_stops_setup(self):
        (self.home / ".fast-coding").mkdir(); self.assert_leftover()

    def test_owned_link_into_fast_coding_stops_setup(self):
        old = self.home / "src" / "fast-coding"; (old / "bin").mkdir(parents=True); (old / "bin" / "compose").touch()
        link = self.home / ".local" / "bin" / "compose"; link.parent.mkdir(parents=True); link.symlink_to(old / "bin" / "compose")
        self.links = [("compose CLI link", link, CHECKOUT / "bin" / "compose")]; self.assert_leftover()

    def test_terminal_with_uv_execs_the_guided_setup_from_setup_dir(self):
        e, text, ex, cd, plain = self.run_setup()
        self.assertIsInstance(e, Exec); cd.assert_called_once(); self.assertEqual(Path(cd.call_args[0][0]), CHECKOUT / "setup")
        (tool, argv), _ = ex.call_args; plain.assert_not_called()
        self.assertEqual((Path(tool).name, Path(argv[0]).name, list(argv[1:])), ("uv", "uv", UV_ARGV))

    def test_plain_path_and_its_exit_code(self):
        for kw, yes in (({"yes": True}, True), ({"stdin": False}, False), ({"stdout": False}, False)):
            with self.subTest(**kw):
                e, text, ex, cd, plain = self.run_setup(**kw)
                self.assertEqual((type(e), e.code), (SystemExit, 3)); plain.assert_called_once_with(CHECKOUT, yes)
                ex.assert_not_called(); self.assertNotIn("uv", text)

    def test_terminal_without_uv_says_so_and_runs_plain(self):
        e, text, ex, cd, plain = self.run_setup(uv=False)
        self.assertEqual((type(e), e.code), (SystemExit, 3)); plain.assert_called_once_with(CHECKOUT, False)
        self.assertIn("uv", text); self.assertEqual(len(text.strip().splitlines()), 1); ex.assert_not_called()

def row(name, level="default", mode="run", ok=False):
    return (name, lambda c: (ok, ""), f"install {name}", level, False, mode)

ROWS = (row("gh", "required"), row("git", ok=True), row("brew", mode="interactive"), row("figma", "designer"),
        row("OpenRouter key", "required", mode="key"), row("pi"))
SIG = {f.__name__: inspect.signature(f) for f in (fc_prompt.confirm, fc_prompt.step, fc_steprun.run_step)}
arg = lambda f, a, k: SIG[f].bind(*a, **k).arguments

class Walk(unittest.TestCase):
    def walk(self, custom, yes, answers=None, states=None, claude=True):
        self.inside, self.runs = None, []
        @contextlib.contextmanager
        def spin(label):
            self.inside = label
            try: yield
            finally: self.inside = None
        def run(*a, **k):
            got = arg("run_step", a, k); self.runs.append((got["row"][0], got["checkout"], got["yes"], got["claude"], got["terminal"], self.inside))
            return (states or {}).get(got["row"][0], ("done", ""))
        with mock.patch.object(fc_steps, "STEPS", ROWS), mock.patch.object(fc_steprun, "run_step", side_effect=run), \
             mock.patch.object(fc_prompt, "confirm", side_effect=lambda *a, **k: answers[a[0] if a else k["question"]]) as ask, \
             mock.patch.object(fc_prompt, "spin", spin), mock.patch.object(fc_prompt, "step") as step, \
             mock.patch("shutil.which", lambda n, *a, **k: f"/bin/{n}" if claude else None), mock.patch("sys.stdout", io.StringIO()):
            got = fc_setup.walk_steps(CHECKOUT, custom=custom, yes=yes)
        self.asks = [(b["question"], b["default"]) for b in (arg("confirm", c.args, c.kwargs) for c in ask.call_args_list)]
        self.steps = [(a["name"], a["word"], list(a.get("lines", ()))) for a in (arg("step", c.args, c.kwargs) for c in step.call_args_list)]
        return got

    def test_custom_asks_once_per_missing_step(self):
        answers = {"Set up gh?": False, "Set up brew?": True, "Set up figma?": True, "Set up pi?": False}
        got = self.walk(True, False, answers, {"figma": ("failed", "boom\nrun by hand: install figma")})
        self.assertEqual(self.asks, [("Set up gh?", True), ("Set up brew?", True), ("Set up figma?", False), ("Set up pi?", True)])
        self.assertEqual(self.steps, [("gh", "skipped", ["compose stops working without it; by hand: install gh"]), ("git", "ok", []),
                                      ("brew", "done", []), ("figma", "failed", ["boom", "run by hand: install figma"]), ("pi", "skipped", [])])
        self.assertEqual(self.runs, [("brew", CHECKOUT, False, True, True, None), ("figma", CHECKOUT, False, True, True, "figma")])
        self.assertEqual(got, ([("gh", "skipped"), ("git", "ok"), ("brew", "done"), ("figma", "failed"), ("pi", "skipped")], True))

    def test_custom_with_the_designer_row_declined_is_no_designer(self):
        got = self.walk(True, False, {"Set up gh?": True, "Set up brew?": True, "Set up figma?": False, "Set up pi?": True})
        self.assertEqual((got[1], ("figma", "skipped", []) in self.steps, [r[0] for r in self.runs]), (False, True, ["gh", "brew", "pi"]))

    def test_quick_start_and_yes_ask_nothing_and_run_every_row_but_designer_and_keys(self):
        for yes in (False, True):
            with self.subTest(yes=yes):
                got = self.walk(False, yes, {}, {"gh": ("failed", "boom\nrun by hand: install gh"), "git": ("ok", "")}, claude=not yes)
                self.assertEqual(self.asks, [])
                self.assertEqual(self.runs, [(n, CHECKOUT, yes, not yes, not yes, None if n == "brew" and not yes else n) for n in ("gh", "git", "brew", "pi")])
                self.assertEqual(self.steps, [("gh", "failed", ["boom", "run by hand: install gh"]), ("git", "ok", []), ("brew", "done", []),
                                              ("figma", "skipped", ["designer extra, skipped"]), ("pi", "done", [])])
                self.assertEqual(got, ([("gh", "failed"), ("git", "ok"), ("brew", "done"), ("figma", "skipped"), ("pi", "done")], False))

    def test_a_claude_state_is_shown_as_waiting_on_claude_code(self):
        got = self.walk(False, True, {}, {"pi": ("claude", "")}, claude=False)
        self.assertEqual((self.steps[-1], got[0][-1]), (("pi", "waiting on Claude Code", []), ("pi", "claude")))
