import hermetic  # first: no test sees the real home
import os, subprocess, tempfile, unittest
from pathlib import Path
os.environ["HERDR_ENV"] = ""

LAUNCHER = Path(__file__).resolve().parents[1] / "bin" / "compose"


class Launcher(unittest.TestCase):
    """bin/compose finds compose.py next to its real self, so the usual install (a symlink on PATH) and a link to
    that link both work exactly like calling it by its path in the repo."""
    def run_help(self, path):
        r = subprocess.run([str(path), "--help"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"^usage: compose")
        return r

    def test_called_by_its_path(self):
        self.run_help(LAUNCHER)

    def test_called_through_a_symlink_and_a_chain_of_symlinks(self):
        tmp = Path(tempfile.mkdtemp())
        link = tmp / "bin" / "compose"; link.parent.mkdir()
        os.symlink(LAUNCHER, link)
        chain = tmp / "other" / "fc"; chain.parent.mkdir()
        os.symlink(link, chain)
        self.run_help(link)
        self.run_help(chain)
        relative = tmp / "rel"
        os.symlink(os.path.relpath(link, tmp), relative)  # a relative link resolves against its own directory
        self.run_help(relative)


if __name__ == "__main__":
    unittest.main()
