import io, os, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
os.environ["HERDR_ENV"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import fc_setup

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
