import io, json, os, re, stat, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
import compose as fc
import fc_steps

CLI = str(Path(__file__).resolve().parents[1] / "bin" / "compose.py")
TOOLS = {"herdr": "0.9.3", "treehouse": "v3.1.2", "trail": "0.23.0", "gh": "gh version 2.94.0", "pi": "1.0.3", "claude": "2.1.301 (Claude Code)", "npx": "11.19.0", "bp": ""}
SKILLS = (".claude/skills/herdr/SKILL.md", ".claude/plugins/marketplaces/i-have-adhd/skills/i-have-adhd/SKILL.md",
          ".claude/plugins/cache/official/superpowers/7.0.0/skills/writing-plans/SKILL.md", ".config/figma-context-mcp/.env")


class Doctor(unittest.TestCase):
    """check_deps walks the setup steps table with its check: one MISSING line per row that is not ok, and only the required
    rows come back (those stop init)."""
    def setUp(self):
        self.bin = Path(tempfile.mkdtemp()) / "bin"
        self.bin.mkdir()
        self.home = Path(tempfile.mkdtemp())
        for tool, version in TOOLS.items():
            self.fake(tool, version)
        for s in SKILLS:
            (self.home / s).parent.mkdir(parents=True)
            (self.home / s).write_text("# skill")
        (self.home / ".claude.json").write_text(json.dumps({"mcpServers": {"framelink-figma": {"command": "npx"}}}))
        self.herdr_config('[ui.toast]\ndelivery = "off"\n\n[ui.sound]\nenabled = false\n')
        self.env = mock.patch.dict(os.environ, {"PATH": str(self.bin), "HOME": str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def fake(self, tool, version, body=""):
        f = self.bin / tool
        f.write_text(f"#!/bin/sh\n{body}\necho '{version}'\n")
        f.chmod(stat.S_IRWXU)

    def herdr_config(self, text):
        (self.home / ".config" / "herdr").mkdir(parents=True, exist_ok=True)
        (self.home / ".config" / "herdr" / "config.toml").write_text(text)

    def deps(self, role=None):
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            bad = fc.fc_init.check_deps(role)
        return bad, [l for l in out.getvalue().splitlines() if l.startswith("MISSING")]

    def rows(self, *names):  # the real rows by name, in table order
        return mock.patch.object(fc_steps, "STEPS", tuple(r for r in fc_steps.STEPS if r[0] in names))

    def test_rows_report_misses_floors_and_levels(self):
        fake = mock.patch.object(fc_steps, "STEPS", (
            ("herdr", "herdr", "see https://herdr.dev", "required", False, "run"),
            ("treehouse", "treehouse", "brew install treehouse", "default", False, "run"),
            ("gh stack", ["gh", "stack", "--version"], "gh extension install github/gh-stack", "required", False, "run"),
            ("herdr skill", SKILLS[0], "herdr --skill", "required", False, "run"),
            ("superpowers", ".claude/plugins/cache/*/superpowers/*/skills/writing-plans/SKILL.md", "claude plugin install superpowers", "default", True, "run"),
            ("framelink-figma", lambda c: ("framelink-figma" in fc_steps.user_mcp_servers(), ""), "claude mcp add x", "designer", True, "run")))
        with fake:
            self.assertEqual(self.deps(), ([], []))
            self.fake("herdr", "herdr 0.8.0")
            self.fake("treehouse", "v2.0.1")
            self.fake("gh", "gh version 2.94.0", body='[ "$1" = stack ] && exit 1')
            (self.home / SKILLS[0]).unlink()
            (self.home / SKILLS[2]).unlink()
            (self.home / ".claude.json").unlink()
            self.assertEqual(self.deps(), (["herdr", "gh stack", "herdr skill"], [
                "MISSING: herdr 0.8.0 is older than 0.9.3 (install: see https://herdr.dev)",
                "MISSING: treehouse 2.0.1 is older than 3.1.2 (install: brew install treehouse) - optional",
                "MISSING: gh stack (install: gh extension install github/gh-stack)",
                "MISSING: herdr skill (install: herdr --skill)",
                "MISSING: superpowers (install: claude plugin install superpowers) - optional",
                "MISSING: framelink-figma (install: claude mcp add x) - needed for the designer"]))
            self.assertEqual(self.deps("designer"), (["framelink-figma"], ["MISSING: framelink-figma (install: claude mcp add x)"]))

    def test_dangling_owned_link(self):
        self.home = self.home.resolve()
        os.environ["HOME"] = str(self.home)
        link = self.home / ".local" / "bin" / "compose"
        link.parent.mkdir(parents=True)
        link.symlink_to(self.home / "gone" / "compose")
        with self.rows("compose CLI link"):
            self.assertEqual(self.deps(), (["compose CLI link"], [
                f"MISSING: compose CLI link (dangling link {link} -> {self.home}/gone/compose; install: compose setup)"]))

    def test_key_rows_name_the_key_never_a_value(self):
        auth = self.home / ".config" / "compose" / "auth.json"
        auth.parent.mkdir(parents=True)
        auth.write_text(json.dumps({"workspaces": {"default": {"openrouter": "sk-or-test"}}}))
        (self.home / SKILLS[-1]).write_text("FIGMA_API_KEY=figd-test\n")
        out = io.StringIO()
        with mock.patch.object(fc.fc_config, "CONFIG_PATH", auth.parent / "config.json"), mock.patch.object(fc.fc_config, "AUTH_PATH", auth), \
             mock.patch.object(fc.fc_config, "ENV_FILE", auth.parent / ".env"), mock.patch.object(fc_steps, "FRAMELINK_ENV", self.home / SKILLS[-1]), \
             self.rows(*(r[0] for r in fc_steps.STEPS if r[5] == "key")), mock.patch("sys.stdout", out):
            bad = fc.fc_init.check_deps()
        self.assertEqual(("TypeSafe key" in bad, "OpenRouter key" in bad, "framelink-figma token" in out.getvalue()), (True, False, False))
        self.assertEqual(len([l for l in out.getvalue().splitlines() if l.startswith("MISSING: TypeSafe key") and "(install: " in l]), 1)
        self.assertFalse({"sk-or-test", "figd-test"} & set(re.findall(r"[\w-]+", out.getvalue())))

    def test_init_and_designer_start_stop_on_a_miss(self):
        (self.home / ".claude.json").unlink()
        repo = Path(tempfile.mkdtemp())  # not even a git repository: init must stop before it touches anything
        env = {**os.environ, "COMPOSE_NO_TREEHOUSE": "1"}
        r = subprocess.run([sys.executable, CLI, "init", "--project", "p", "--repo", str(repo)], capture_output=True, text=True, env=env)
        self.assertEqual((r.returncode, list(repo.iterdir())), (1, []))
        self.assertIn("init stopped", r.stderr)
        r = subprocess.run([sys.executable, CLI, "designer", "--project", "p", "--repo", str(repo)], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("MISSING: framelink-figma (", r.stdout)
        self.assertIn("designer stopped", r.stderr)

    def test_herdr_toasts_and_sounds_warn_when_not_off(self):
        """herdr's own toast and sound fire for every agent that finishes or needs input, so doctor names the two keys to set
        when either is on; delivery defaults to off, sound to on, so a missing key counts as its default."""
        self.assertIsNone(fc.fc_init.herdr_toast_warning())
        self.herdr_config('onboarding = false\n[ui]\nagent_panel_sort = "spaces"  # a comment\n\n[ui.toast]\ndelivery = "system"\n')
        w = fc.fc_init.herdr_toast_warning()
        self.assertTrue(w.startswith("WARNING: herdr alerts the product owner for every agent, not only the engineering manager (ui.toast.delivery=system, ui.sound.enabled=true)"), w)
        self.assertIn('set [ui.toast] delivery = "off" and [ui.sound] enabled = false in ~/.config/herdr/config.toml', w)
        self.assertEqual(len(w.splitlines()), 1)
        self.herdr_config('[ui.sound]\nenabled = false\n')  # no [ui.toast] at all: herdr's default delivery is off
        self.assertIsNone(fc.fc_init.herdr_toast_warning())
        (self.home / ".config" / "herdr" / "config.toml").unlink()  # no config: sounds are on by default
        self.assertIn("(ui.sound.enabled=true)", fc.fc_init.herdr_toast_warning())


    GH_WARNING = "WARNING: gh is not logged in: compose bug reports are saved, not filed on GitHub (run: gh auth login)"

    def doctor(self, fails=()):
        """cmd_doctor in process with a gh that logs its calls and exits 1 (chattering on both streams) for each `fails` first
        word pair, such as "auth status"; returns (exit status, stdout lines, gh calls)."""
        log = self.bin.parent / "gh-calls"
        checks = "".join(f'[ "$1 $2" = "{f}" ] && {{ echo "not logged in to github.com"; echo "token invalid" >&2; exit 1; }}\n' for f in fails)
        self.fake("gh", "gh version 2.94.0", body=f'echo "$*" >> {log}\n{checks}')
        out, status = io.StringIO(), 0
        with mock.patch("sys.stdout", out):
            try:
                fc.fc_init.cmd_doctor(None)
            except SystemExit as e:
                status = 1 if isinstance(e.code, str) else e.code
        return status, out.getvalue().splitlines(), log.read_text().splitlines() if log.exists() else []

    def test_doctor_warns_when_gh_is_logged_out(self):
        status, lines, calls = self.doctor(fails=["auth status"])
        self.assertEqual((status, lines), (0, [self.GH_WARNING, "every tool compose needs is installed"]))  # gh's own text stays out
        self.assertIn("auth status", calls)

    def test_doctor_is_quiet_when_gh_is_logged_in(self):
        status, lines, calls = self.doctor()
        self.assertEqual((status, lines), (0, ["every tool compose needs is installed"]))
        self.assertIn("auth status", calls)

    def test_doctor_shows_both_warnings_and_still_passes(self):
        self.herdr_config('[ui.toast]\ndelivery = "system"\n')
        status, lines, _ = self.doctor(fails=["auth status"])
        self.assertEqual(status, 0)
        self.assertEqual(sorted(l.split(":")[0] for l in lines[:-1]), ["WARNING", "WARNING"])
        self.assertIn(self.GH_WARNING, lines)
        self.assertEqual(lines[-1], "every tool compose needs is installed")

    def test_a_missing_tool_stops_doctor_before_the_gh_auth_check(self):
        (self.bin / "claude").unlink()
        self.assertEqual(self.doctor(fails=["auth status"]), (1, ["MISSING: claude (install: curl -fsSL https://claude.ai/install.sh | bash)"],
                                                              ["stack --version"]))
        self.fake("claude", TOOLS["claude"])  # gh itself on PATH without its stack extension stops it the same way
        status, lines, calls = self.doctor(fails=["auth status", "stack --version"])
        self.assertEqual((status, lines), (1, ["MISSING: gh stack (install: gh extension install github/gh-stack)"]))
        self.assertNotIn("auth status", calls)

if __name__ == "__main__":
    unittest.main()
