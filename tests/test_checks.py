import os, platform, stat, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
import fc_checks as C


class Checks(unittest.TestCase):
    """Each check reads a fake HOME and PATH holding fake tools; nothing else on the machine."""
    def setUp(self):
        self.bin, self.home = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        self.enterContext(mock.patch.dict(os.environ, {"PATH": str(self.bin), "HOME": str(self.home)}))

    def fake(self, tool, body):
        (self.bin / tool).write_text(f"#!/bin/sh\n{body}\n")
        (self.bin / tool).chmod(stat.S_IRWXU)

    def test_owned_links(self):
        co, h = Path("/co"), self.home
        self.assertEqual(C.owned_links(co), [("compose CLI link", h / ".local/bin/compose", co / "bin/compose"),
                                             ("compose skill link", h / ".claude/skills/compose", co), ("bp link", h / ".local/bin/bp", co / "bp/bin/bp.mjs")])

    def test_link_state(self):
        (self.home / "real").write_text("x")
        (self.home / "hop").symlink_to(self.home / "real")
        (self.home / "via").symlink_to("hop")
        (self.home / "gone").symlink_to("nowhere/x")
        self.assertEqual(C.link_state(self.home / "via"), ("ok", str((self.home / "real").resolve())))
        self.assertEqual(C.link_state(self.home / "gone"), ("dangling", "nowhere/x"))
        self.assertEqual(C.link_state(self.home / "none"), ("missing", None))

    def test_path_and_tools(self):
        os.environ["PATH"] = f"{self.bin}:{self.home}/.local/binx"
        self.assertFalse(C.local_bin_on_path())
        os.environ["PATH"] = f"{self.bin}:{self.home}/.local/bin"
        self.assertTrue(C.local_bin_on_path())
        self.assertFalse(C.gh_authed())
        for code, want in ((1, False), (0, True)):
            self.fake("gh", f'[ "$*" = "auth status" ] || exit 9\nexit {code}')
            self.assertIs(C.gh_authed(), want)
        self.assertFalse(C.rerere_set())
        for out, want in (("false", False), ("true", True)):
            self.fake("git", f'[ "$*" = "config --global --get rerere.enabled" ] || exit 9\necho {out}')
            self.assertIs(C.rerere_set(), want)

    def test_jev_and_chromium(self):
        self.assertFalse(C.jev_synced(self.home))
        (self.home / "jev/.venv").mkdir(parents=True)
        self.assertTrue(C.jev_synced(self.home))
        cache, arch = self.home / "Library/Caches/ms-playwright", "arm64" if platform.machine() == "arm64" else "x64"
        self.assertFalse(C.chromium_installed())
        app = Path(f"chrome-mac-{arch}/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")
        for v in ("chromium-999", "chromium-1200", "chromium_headless_shell-2000"):
            (cache / v / app.parent).mkdir(parents=True)
        (cache / "chromium-999" / app).write_text("")
        self.assertFalse(C.chromium_installed())
        (cache / "chromium-1200" / app).write_text("")
        self.assertTrue(C.chromium_installed())
