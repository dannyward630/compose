import os, subprocess, tempfile, unittest
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[1] / "bin" / "fast-coding"


class Launcher(unittest.TestCase):
    """bin/fast-coding finds fast_coding.py next to its real self, so the usual install (a symlink on PATH) and a link to
    that link both work exactly like calling it by its path in the repo."""
    def run_help(self, path):
        r = subprocess.run([str(path), "--help"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"^usage: fast-coding")
        return r

    def test_called_by_its_path(self):
        self.run_help(LAUNCHER)

    def test_called_through_a_symlink_and_a_chain_of_symlinks(self):
        tmp = Path(tempfile.mkdtemp())
        link = tmp / "bin" / "fast-coding"; link.parent.mkdir()
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
