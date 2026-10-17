import io, os, stat, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import fc_auth, fc_keys

HEADER = "Checking MCP server health…\n\n"
FIGMA = "claude.ai Figma: https://mcp.figma.com/mcp - ✔ Connected\n"


class KeyStatus(unittest.TestCase):
    """Which keys are set (never their values), whether claude.ai Linear is connected, and the Linear rule."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.env = self.tmp / "framelink.env"
        patcher = mock.patch.dict(os.environ, {"PATH": str(self.bin), "HOME": str(self.tmp)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def status(self, keys, env_text=None):
        if env_text is not None: self.env.write_text(env_text)
        calls, out = [], io.StringIO()
        def lookup(auth, workspace, kind):
            calls.append((auth, workspace, kind))
            return keys.get(kind)
        with mock.patch.object(fc_auth, "workspace_key", lookup), redirect_stdout(out):
            got = fc_keys.key_status({"a": 1}, "acme", self.env)
        self.assertNotIn("sk-", out.getvalue() + repr(got))
        self.assertEqual({c[2] for c in calls}, {"openrouter", "typesafe", "linear"})
        self.assertTrue(all(c[:2] == ({"a": 1}, "acme") for c in calls))
        return got

    def test_presence(self):
        keys = {"openrouter": "sk-or-test", "typesafe": "sk-ts-test", "linear": "sk-lin-test"}
        self.assertEqual(self.status(keys, "# x\nFIGMA_API_KEY=sk-fig-test\n"), dict.fromkeys(["openrouter", "typesafe", "linear", "figma"], True))
        self.assertEqual(self.status({"openrouter": "", "linear": "sk-lin-test"}, "OTHER=sk-x\nFIGMA_API_KEY=\n"),
                         {"openrouter": False, "typesafe": False, "linear": True, "figma": False})
        self.assertFalse(self.status({})["figma"])  # no Framelink env file

    def mcp(self, text):
        f = self.bin / "claude"
        f.write_text(f'#!/bin/sh\n[ "$1 $2" = "mcp list" ] && printf \'%s\' "{text}"\n')
        f.chmod(stat.S_IRWXU)
        return fc_keys.linear_connected()

    def test_linear_connected(self):
        self.assertIsNone(fc_keys.linear_connected())
        self.assertIs(self.mcp(HEADER + "claude.ai Linear: https://mcp.linear.app/mcp - ✔ Connected\n" + FIGMA), True)
        self.assertIs(self.mcp(HEADER + FIGMA), False)
        self.assertIs(self.mcp(HEADER + "claude.ai Linear: https://mcp.linear.app/mcp - ! Needs authentication\n" + FIGMA), False)
        self.assertIs(self.mcp(HEADER + "claude.ai Linear: https://x.invalid/Connected - ✘ Failed to connect\n" + FIGMA), False)

    def test_linear_state(self):
        for linear, connected, want in [(True, False, "key"), (True, None, "key"), (False, True, "connector"),
                                        (False, None, "unknown"), (False, False, "missing")]:
            self.assertEqual(fc_keys.linear_state({"openrouter": True, "typesafe": True, "linear": linear, "figma": False}, connected), want)


class KeySave(unittest.TestCase):
    """Saving an entered key to auth.json or the Framelink env file, and the line for a skipped key; never a value."""
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp, self.calls = Path(tmp.name), []
        self.auth, self.env = self.tmp / "auth.json", self.tmp / "framelink" / "deep" / ".env"
        def set_key(path, workspace, kind, value): self.calls.append((Path(path), workspace, kind, value))
        for p in (mock.patch.object(fc_keys.fc_config, "AUTH_PATH", self.auth), mock.patch.object(fc_auth, "set_key", set_key)):
            p.start()
            self.addCleanup(p.stop)

    def save(self, kind, value):
        out = io.StringIO()
        with redirect_stdout(out): line = fc_keys.save_key(kind, value, "acme", self.env)
        if value: self.assertNotIn(value, line + out.getvalue())
        return line

    def test_auth_kinds(self):
        for kind, value in [("openrouter", "sk-or-test"), ("linear", "lin-test"), ("typesafe", "ts-test")]:
            self.calls.clear()
            self.assertIn(kind, self.save(kind, value).lower())
            self.assertEqual(self.calls, [(self.auth, "acme", kind, value)])
        self.assertFalse(self.env.parent.exists())

    def test_figma(self):
        self.assertIn("figma", self.save("figma", "fig-test").lower())
        self.assertEqual(self.env.read_text().splitlines(), ["FIGMA_API_KEY=fig-test"])
        self.assertEqual(stat.S_IMODE(self.env.stat().st_mode), 0o600)
        self.env.write_text("# framelink\nOTHER=1\nFIGMA_API_KEY=fig-old\n")
        self.env.chmod(0o644)
        self.save("figma", "fig-new")
        self.assertEqual(sorted(self.env.read_text().splitlines()), ["# framelink", "FIGMA_API_KEY=fig-new", "OTHER=1"])
        self.assertEqual(stat.S_IMODE(self.env.stat().st_mode), 0o600)
        self.assertEqual(self.calls, [])

    def test_empty_saves_nothing(self):
        self.env.parent.mkdir(parents=True)
        self.env.write_text("FIGMA_API_KEY=fig-old\n")
        for kind in ("openrouter", "linear", "typesafe", "figma"):
            self.assertEqual(self.save(kind, ""), fc_keys.skipped_line(kind, "acme"))
        self.assertEqual((self.calls, self.env.read_text()), ([], "FIGMA_API_KEY=fig-old\n"))
        self.assertFalse(self.auth.exists())

    def test_skipped_lines(self):
        fix = "pbpaste | compose workspace key acme"
        for kind, words in [("openrouter", ["run", "verify", fix]), ("typesafe", ["verify", "change", "compose setup"]),
                            ("linear", ["linear", "sync --from-linear", fix + " --linear", "claude.ai", "connector"]),
                            ("figma", ["designer", "compose setup"])]:
            line = fc_keys.skipped_line(kind, "acme")
            for word in words: self.assertIn(word, line if " " in word else line.lower())
        self.assertNotIn("--linear", fc_keys.skipped_line("openrouter", "acme"))
        self.assertNotIn("connector", fc_keys.skipped_line("openrouter", "acme").lower())
        for kind in ("typesafe", "figma"): self.assertNotIn("workspace key", fc_keys.skipped_line(kind, "acme"))
