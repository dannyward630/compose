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

class TrailRow(unittest.TestCase):
    """The trail row (@trailhq/trail-code) sits right after jev; its check finds the `trail` command on PATH, never graft."""
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.bin, self.bin2, self.co = tmp / "bin", tmp / "bin2", tmp / "co"
        for d in (self.bin, self.bin2, self.co): d.mkdir()
        p = mock.patch.dict(os.environ, {"PATH": f"{self.bin}:{self.bin2}", "HOME": str(tmp / "home")}); p.start(); self.addCleanup(p.stop)
        names = [r[0] for r in fc_steps.STEPS]
        self.assertEqual(names.count("trail"), 1, names)
        self.row = fc_steps.STEPS[names.index("trail")]

    def fake(self, tool, where=None, mode=stat.S_IRWXU):
        f = (where or self.bin) / tool; f.write_text("#!/bin/sh\necho 1.0.0\n"); f.chmod(mode)

    def test_row_right_after_jev_with_its_fields(self):
        names = [r[0] for r in fc_steps.STEPS]
        self.assertEqual(names[names.index("jev") + 1:names.index("jev") + 3], ["trail", "treehouse"])
        self.assertEqual(self.row, ("trail", "trail", "npm i -g @trailhq/trail-code", "default", False, "run"))

    def test_other_rows_keep_place_level_mode_and_install(self):
        rows = [r for r in fc_steps.STEPS if r[0] != "trail"]
        self.assertEqual([(r[0], r[3], r[5], r[4]) for r in rows], [(n, l, m, bool(x)) for n, l, m, *x in ROWS])
        self.assertEqual({r[0]: r[2] for r in rows if r[0] in INSTALLS}, INSTALLS)

    def test_check_finds_trail_and_never_graft(self):
        self.assertFalse(fc_steps.check(self.row, self.co)[0])  # nothing on PATH
        self.fake("graft"); self.assertFalse(fc_steps.check(self.row, self.co)[0])  # only graft
        self.fake("trail", self.bin2); self.assertEqual(fc_steps.check(self.row, self.co), (True, ""))  # later PATH entry, beside graft
        (self.bin / "graft").unlink(); self.assertEqual(fc_steps.check(self.row, self.co), (True, ""))  # trail alone

    def test_check_not_ok_for_a_trail_that_cannot_run(self):
        self.fake("trail", mode=0o644); ok, detail = fc_steps.check(self.row, self.co)
        self.assertFalse(ok); self.assertNotIn("1.0.0", detail)

class OwnedLinks(unittest.TestCase):
    """An owned link is ok when it resolves to its place in this or any compose checkout (a directory with bin/compose.py and SKILL.md)."""
    # (row, link under HOME, its place in a checkout, a path inside a checkout that is not that place)
    LINKS = (("compose CLI link", ".local/bin/compose", "bin/compose", "bin/compose.py"), ("compose skill link", ".claude/skills/compose", "", "bin"),
             ("bp link", ".local/bin/bp", "bp/bin/bp.mjs", "bin/compose"))

    def setUp(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup); self.tmp = Path(d.name).resolve(); self.home = self.tmp / "home"
        p = mock.patch.dict(os.environ, {"HOME": str(self.home), "COMPOSE_CONFIG": str(self.home / ".compose/config.json")}); p.start(); self.addCleanup(p.stop)
        self.co, self.other = self.checkout("co"), self.checkout("other")
        self.rows = {r[0]: r for r in fc_steps.STEPS}

    def checkout(self, name, files=("bin/compose.py", "SKILL.md", "bin/compose", "bp/bin/bp.mjs")):
        for f in files: (self.tmp / name / f).parent.mkdir(parents=True, exist_ok=True); (self.tmp / name / f).write_text("")
        return self.tmp / name

    def at(self, name, link, target):
        """Point ~/<link> at target (None: no link) and check the row."""
        p = self.home / link; p.parent.mkdir(parents=True, exist_ok=True); p.unlink(missing_ok=True)
        if target is not None: p.symlink_to(target)
        return fc_steps.check(self.rows[name], self.co)

    def test_ok_into_this_or_another_checkout(self):
        (self.tmp / "alias").symlink_to(self.other)  # a checkout reached through a symlinked directory
        for name, link, rel, _ in self.LINKS:
            for c in (self.co, self.other, self.tmp / "alias"):
                self.assertEqual(self.at(name, link, c / rel), (True, ""), f"{name} -> {c / rel}")

    def test_not_ok_outside_any_checkout(self):
        no_skill = self.checkout("noskill", ("bin/compose.py", "bin/compose", "bp/bin/bp.mjs"))
        no_cli = self.checkout("nocli", ("SKILL.md", "bin/compose", "bp/bin/bp.mjs"))
        nested = self.checkout("other/nested", ("bin/compose", "bp/bin/bp.mjs"))  # inside a checkout, but not one itself
        for name, link, rel, wrong in self.LINKS:
            for target in (no_skill / rel, no_cli / rel, nested / rel, self.other / wrong):
                self.assertEqual(self.at(name, link, target), (False, f"{self.home / link} is not a link to {self.co / rel}"), f"{name} -> {target}")

    def test_dangling_absent_or_a_plain_file(self):
        for name, link, rel, _ in self.LINKS:
            raw = self.tmp / "gone" / rel
            self.assertEqual(self.at(name, link, raw), (False, f"dangling link {self.home / link} -> {raw}"), name)
            self.assertFalse(self.at(name, link, None)[0], name)
        (self.home / ".local/bin/compose").write_text("")  # a copy, not a link
        self.assertFalse(fc_steps.check(self.rows["compose CLI link"], self.co)[0])
