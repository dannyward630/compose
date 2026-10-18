import hermetic  # first: no test sees the real home
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
        (self.tmp / ".claude.json").write_text("{}")  # without it linear_connected never runs claude
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
        for kind, words in [("openrouter", ["run", "verify", fix]), ("typesafe", ["verify", "change", fix + " --typesafe"]),
                            ("linear", ["linear", "sync --from-linear", fix + " --linear", "claude.ai", "connector"]),
                            ("figma", ["designer", "compose setup"])]:
            line = fc_keys.skipped_line(kind, "acme")
            for word in words: self.assertIn(word, line if " " in word else line.lower())
        self.assertNotIn("--linear", fc_keys.skipped_line("openrouter", "acme"))
        self.assertNotIn("connector", fc_keys.skipped_line("openrouter", "acme").lower())
        self.assertNotIn("workspace key", fc_keys.skipped_line("figma", "acme"))


class KeyLines(unittest.TestCase):
    """The fix for a skipped key sits on its own indented line, and the connector check never runs claude in a fresh HOME."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bin, self.home, self.rec = self.tmp / "bin", self.tmp / "home", self.tmp / "ran"
        self.bin.mkdir()
        self.home.mkdir()
        claude = self.bin / "claude"  # like the real one: running it creates ~/.claude.json and ~/.claude/backups
        linear = "claude.ai Linear: https://mcp.linear.app/mcp - ✔ Connected\n"
        claude.write_text(f'#!/bin/sh\ntouch "{self.rec}"; mkdir -p "$HOME/.claude/backups"\n'
                          '[ -f "$HOME/.claude.json" ] || echo {} > "$HOME/.claude.json"\n'
                          f'[ "$1 $2" = "mcp list" ] && printf \'%s\' "{HEADER}{linear}{FIGMA}"\n')
        claude.chmod(stat.S_IRWXU)
        p = mock.patch.dict(os.environ, {"PATH": str(self.bin), "HOME": str(self.home), "OPENROUTER_API_KEY": "sk-or-test"})
        p.start()
        self.addCleanup(p.stop)

    def test_fresh_home_runs_no_claude(self):
        self.assertIs(fc_keys.linear_connected(), False)
        self.assertEqual(sorted(p.name for p in self.home.iterdir()), [])
        self.assertFalse(self.rec.exists())

    def test_with_claude_json_parses_mcp_list(self):
        (self.home / ".claude.json").write_text("{}")
        self.assertIs(fc_keys.linear_connected(), True)
        self.assertTrue(self.rec.exists())
        os.environ["PATH"] = str(self.tmp / "none")
        self.assertIsNone(fc_keys.linear_connected())

    def test_no_claude_is_none_in_fresh_home(self):
        os.environ["PATH"] = str(self.tmp / "none")
        self.assertIsNone(fc_keys.linear_connected())

    def test_lines(self):
        for ws in ("acme", "team-b"):
            fix = f"  pbpaste | compose workspace key {ws}"
            for kind, word, tail in [("openrouter", "run", [fix]),
                                     ("linear", "linear", [fix + " --linear", "  or connect the claude.ai Linear connector"]),
                                     ("typesafe", "verify", [fix + " --typesafe"]), ("figma", "designer", ["  compose setup"])]:
                lines = fc_keys.skipped_line(kind, ws).splitlines()
                self.assertEqual(lines[-len(tail):], tail, kind)
                if kind == "figma": self.assertTrue(lines[-2].endswith("Add one later, on a terminal:"), lines)
                self.assertIn(word, lines[0].lower())
                self.assertFalse(lines[0].startswith(" ") or "pbpaste" in lines[0] or "compose setup" in lines[0], lines)
                self.assertNotIn("sk-or-test", "\n".join(lines))
                self.assertNotIn("acme" if ws != "acme" else "team-b", "\n".join(lines))


class TypeSafeLine(unittest.TestCase):
    """A skipped TypeSafe key names compose workspace key --typesafe; the other kinds' lines stay as they are."""
    OTHERS = {
        "openrouter": "No OpenRouter key: without it run and verify have no model. Add one later:\n  pbpaste | compose workspace key {}",
        "linear": "No Linear key: without it the CLI's Linear moves and sync --from-linear cannot run. Add one later:\n"
                  "  pbpaste | compose workspace key {} --linear\n  or connect the claude.ai Linear connector",
        "figma": "No Figma token: without it the designer cannot build your designs. Add one later, on a terminal:\n  compose setup",
    }

    def test_typesafe(self):
        for ws in ("default", "acme", "team-b2"):
            line = fc_keys.skipped_line("typesafe", ws)
            self.assertEqual(line, "No TypeSafe key: without it verify and change cannot check your code. Add one later:\n"
                                   f"  pbpaste | compose workspace key {ws} --typesafe")
            self.assertNotIn("compose setup", line)
            self.assertNotIn("on a terminal", line)

    def test_others_unchanged(self):
        for ws in ("default", "team-b2"):
            for kind, text in self.OTHERS.items():
                self.assertEqual(fc_keys.skipped_line(kind, ws), text.format(ws), kind)
            self.assertNotIn("--typesafe", "".join(fc_keys.skipped_line(k, ws) for k in self.OTHERS))
