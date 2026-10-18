import hermetic  # first: no test sees the real home
import os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import fc_checks, fc_links


class Links(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.target, self.other = self.tmp / "target", self.tmp / "other"
        self.target.write_text("t")
        self.other.write_text("o")
        self.link = self.tmp / "deep" / "bin" / "x"

    def test_states(self):
        self.assertEqual(fc_links.ensure_link(self.link, self.target)[0], "linked")
        self.assertEqual(Path(os.readlink(self.link)), self.target)
        self.assertEqual(fc_links.ensure_link(self.link, self.target)[0], "ok")
        for start in (self.other, self.tmp / "gone"):
            self.link.unlink()
            self.link.symlink_to(start)
            self.assertEqual(fc_links.ensure_link(self.link, self.target)[0], "repointed")
            self.assertEqual(self.link.resolve(), self.target.resolve())

    def test_refuses_real_file_and_directory(self):
        self.link.parent.mkdir(parents=True)
        self.link.write_text("mine")
        state, line = fc_links.ensure_link(self.link, self.target)
        self.assertEqual((state, self.link.read_text(), self.link.is_symlink()), ("refused", "mine", False))
        for word in (str(self.link), "file"): self.assertIn(word, line)
        self.link.unlink()
        self.link.mkdir()
        state, line = fc_links.ensure_link(self.link, self.target)
        self.assertEqual((state, self.link.is_dir(), self.link.is_symlink()), ("refused", True, False))
        self.assertIn("director", line)

    def test_relink_owned(self):
        names = ("compose CLI link", "compose skill link", "bp link")
        links = [(n, self.tmp / "home" / f"l{i}", self.target) for i, n in enumerate(names)]
        (self.tmp / "home").mkdir()
        (self.tmp / "home" / "l1").symlink_to(self.other)
        with mock.patch.object(fc_checks, "owned_links", return_value=links) as owned:
            lines = fc_links.relink_owned(self.tmp)
            again = fc_links.relink_owned(self.tmp)
        owned.assert_called_with(self.tmp)
        self.assertEqual(len(lines), 3)
        for (name, link, _), line, state in zip(links, lines, ("linked", "repointed", "linked")):
            self.assertIn(name, line)
            self.assertIn(state, line)
            self.assertEqual(link.resolve(), self.target.resolve())
        self.assertTrue(all("ok" in l for l in again))

    def test_path_line(self):
        home = Path(tempfile.mkdtemp())
        for path, want in ((f"/usr/bin:{home}/bin", 'export PATH="$HOME/.local/bin:$PATH"'), (f"/usr/bin:{home}/.local/bin:/bin", None)):
            with mock.patch.dict(os.environ, {"PATH": path, "HOME": str(home)}):
                self.assertEqual(fc_links.path_line(), want)
        self.assertEqual(list(home.iterdir()), [])
