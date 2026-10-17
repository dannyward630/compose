import json, os, re, stat, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
import fc_config, fc_steps
R, D, G, c = "required", "default", "designer", True
ROWS = [("Homebrew", D, "interactive"), ("git", R, "manual"), ("npx", R, "run"), ("gh", R, "run"), ("gh auth", R, "interactive"), ("gh stack", R, "run"),
        ("claude", R, "manual"), ("herdr", R, "run"), ("herdr skill", R, "run"), ("i-have-adhd skill", R, "run", c), ("pi", R, "run"),
        ("pi openrouter-fast provider", R, "write"), ("compose CLI link", R, "write"), ("compose skill link", R, "write"), ("~/.local/bin on PATH", R, "manual"),
        ("OpenRouter key", R, "key"), ("TypeSafe key", R, "key"), ("Linear key or connector", R, "key", c), ("uv", D, "run"), ("jev", D, "run"),
        ("treehouse", D, "run"), ("bp link", D, "write"), ("Chromium", D, "run"), ("superpowers", D, "run", c), ("herdr pi integration", D, "run"),
        ("herdr claude integration", D, "run", c), ("TEXT_MODEL lines", D, "write"), ("git rerere", D, "run"), ("pi auth.json override", D, "manual"),
        ("framelink-figma", G, "run", c), ("framelink-figma token", G, "key")]
INSTALLS = {"git": "xcode-select --install", "npx": "brew install node", "gh": "brew install gh", "gh auth": "gh auth login",
            "herdr": "curl -fsSL https://herdr.dev/install.sh | sh", "pi": "npm install -g --ignore-scripts @earendil-works/pi-coding-agent",
            "uv": "curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh", "Chromium": "npx playwright install chromium",
            "herdr pi integration": "herdr integration install pi", "herdr claude integration": "herdr integration install claude"}

class StepsTable(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.bin, self.home, self.co, self.auth, self.link = tmp / "bin", tmp / "home", tmp / "co", tmp / "auth.json", tmp / "home/.local/bin/compose"
        for d in (self.bin, self.link.parent, self.co / "bin"): d.mkdir(parents=True)
        (self.co / "bin" / "compose").write_text(""); (tmp / "figma.env").write_text("FIGMA_API_KEY=figd-test\n")
        for p in (mock.patch.dict(os.environ, {"PATH": str(self.bin), "HOME": str(self.home)}), mock.patch.object(fc_config, "AUTH_PATH", self.auth),
                  mock.patch.object(fc_steps, "FRAMELINK_ENV", tmp / "figma.env")):
            p.start(); self.addCleanup(p.stop)
        self.rows = {r[0]: r for r in fc_steps.STEPS}

    def fake(self, tool, out): (self.bin / tool).write_text(f"#!/bin/sh\necho '{out}'\n"); (self.bin / tool).chmod(stat.S_IRWXU)
    def check(self, name): return fc_steps.check(self.rows[name], self.co)

    def test_rows_in_order_with_installs(self):
        rows = [r for r in fc_steps.STEPS if r[0] != "trail"]
        self.assertEqual([(r[0], r[3], r[5], r[4]) for r in rows], [(n, l, m, bool(x)) for n, l, m, *x in ROWS])
        self.assertTrue(all(isinstance(r[2], str) and r[2].strip() for r in rows))
        self.assertEqual({n: self.rows[n][2] for n in INSTALLS}, INSTALLS)
        self.assertEqual({r[2] for r in rows if r[5] == "write"}, {"compose setup"})
        self.assertIn("uv sync --locked --project", self.rows["jev"][2])

    def test_version_floors_compare_numerically(self):
        self.assertFalse(self.check("herdr")[0])  # not on PATH
        for tool, out, want in (("herdr", "0.9.2", (False, "0.9.2 is older than 0.9.3")), ("herdr", "herdr 0.10.0", (True, "")),
                                ("treehouse", "v3.1.1", (False, "3.1.1 is older than 3.1.2")), ("treehouse", "v3.1.2", (True, ""))):
            self.fake(tool, out); self.assertEqual(self.check(tool), want, out)

    def test_dangling_owned_link(self):
        self.link.symlink_to("/nowhere/compose"); ok, detail = self.check("compose CLI link")
        self.assertFalse(ok); self.assertRegex(detail, r"^dangling link \S*\.local/bin/compose -> /nowhere/compose$")
        self.link.unlink(); self.link.symlink_to(self.co / "bin" / "compose"); self.assertEqual(self.check("compose CLI link"), (True, ""))

    def test_linear_key_or_connector_and_key_rows_hide_values(self):
        for mark, key, ok in (("! Needs authentication", False, False), ("✔ Connected", False, True), ("! Needs authentication", True, True)):
            self.fake("claude", f"Checking MCP server health…\n\nclaude.ai Linear: https://mcp.linear.app/mcp - {mark}"); self.auth.unlink(missing_ok=True)
            if key: self.auth.write_text(json.dumps({"workspaces": {"default": {"openrouter": "sk-or-test", "linear": "lin-test"}}, "typesafe": "ts-test"}))
            self.assertEqual(self.check("Linear key or connector")[0], ok, mark)
        for row in [r for r in fc_steps.STEPS if r[5] == "key"]:
            ok, detail = fc_steps.check(row, self.co); self.assertTrue(ok, row[0]); self.assertFalse(re.search("sk-or|lin-test|ts-test|figd", detail), row[0])
        self.auth.unlink(); self.assertFalse(self.check("OpenRouter key")[0])
