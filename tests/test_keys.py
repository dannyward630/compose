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
