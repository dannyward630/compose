import hermetic  # first: no test sees the real home
import io, os, stat, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import fc_auth, fc_keys

LINEAR = ("No Linear key: without it compose linear, sync, and the CLI's Linear moves cannot run. Add one later:\n"
          "  pbpaste | compose workspace key {} --linear")


class KeyStatus(unittest.TestCase):
    """Which keys are set (never their values)."""
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

    def test_module_is_keys_only(self):
        self.assertEqual(fc_keys.__doc__, "Key presence (never values), and saving entered keys.")
        self.assertFalse(hasattr(fc_keys, "linear_connected") or hasattr(fc_keys, "linear_state"))


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
                            ("linear", ["compose linear", "sync", fix + " --linear"]),
                            ("figma", ["designer", "compose setup"])]:
            line = fc_keys.skipped_line(kind, "acme")
            for word in words: self.assertIn(word, line if " " in word else line.lower())
        self.assertNotIn("--linear", fc_keys.skipped_line("openrouter", "acme"))
        for word in ("connector", "claude.ai", "--from-linear"): self.assertNotIn(word, fc_keys.skipped_line("linear", "acme"))
        self.assertNotIn("workspace key", fc_keys.skipped_line("figma", "acme"))


class KeyLines(unittest.TestCase):
    """The fix for a skipped key sits on its own indented line, and no key line runs claude."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bin, self.home, self.rec = self.tmp / "bin", self.tmp / "home", self.tmp / "ran"
        self.bin.mkdir()
        self.home.mkdir()
        claude = self.bin / "claude"
        claude.write_text(f'#!/bin/sh\ntouch "{self.rec}"\n')
        claude.chmod(stat.S_IRWXU)
        (self.home / ".claude.json").write_text("{}")
        p = mock.patch.dict(os.environ, {"PATH": str(self.bin), "HOME": str(self.home), "OPENROUTER_API_KEY": "sk-or-test"})
        p.start()
        self.addCleanup(p.stop)

    def test_no_claude_for_linear(self):
        auth = {"workspaces": {"acme": {"openrouter": "sk-or-test"}}}
        self.assertFalse(fc_keys.key_status(auth, "acme", self.tmp / "none.env")["linear"])
        self.assertEqual(fc_keys.skipped_line("linear", "acme"), LINEAR.format("acme"))
        self.assertFalse(self.rec.exists())

    def test_lines(self):
        for ws in ("acme", "team-b"):
            fix = f"  pbpaste | compose workspace key {ws}"
            for kind, word, tail in [("openrouter", "run", [fix]),
                                     ("linear", "linear", [fix + " --linear"]),
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
        "linear": LINEAR,
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
