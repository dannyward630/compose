import io, json, os, stat, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
import fast_coding as fc

CLI = str(Path(__file__).resolve().parents[1] / "bin" / "fast_coding.py")
TOOLS = {"herdr": "0.9.3", "treehouse": "v3.1.2", "graft": "0.16.0", "gh": "gh version 2.94.0", "pi": "1.0.3", "claude": "2.1.301 (Claude Code)", "npx": "11.19.0", "bp": ""}
SKILLS = (".claude/skills/herdr/SKILL.md", ".claude/plugins/marketplaces/i-have-adhd/skills/i-have-adhd/SKILL.md",
          ".claude/plugins/cache/official/superpowers/7.0.0/skills/writing-plans/SKILL.md", ".config/figma-context-mcp/.env")


class Doctor(unittest.TestCase):
    """check_deps looks only at PATH and the skill files under HOME: one MISSING line per absent or too-old entry, and only the
    required ones come back (those stop init)."""
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

    def deps(self):
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            bad = fc.check_deps()
        return bad, [l for l in out.getvalue().splitlines() if l.startswith("MISSING")]

    def test_all_present(self):
        self.assertEqual(self.deps(), ([], []))

    def test_missing_required_tool_and_skill_file(self):
        (self.bin / "herdr").unlink()
        (self.home / SKILLS[0]).unlink()
        bad, lines = self.deps()
        self.assertEqual(bad, ["herdr", "herdr skill"])
        self.assertEqual(lines[0], "MISSING: herdr (install: see https://herdr.dev)")
        self.assertIn("MISSING: herdr skill (install: mkdir -p ~/.claude/skills/herdr && herdr --skill > ~/.claude/skills/herdr/SKILL.md)", lines)

    def test_gh_without_the_stack_extension(self):
        self.fake("gh", "gh version 2.94.0", body='[ "$1" = stack ] && exit 1')  # `gh stack --version` fails: no extension
        bad, lines = self.deps()
        self.assertEqual(bad, ["gh stack"])
        self.assertEqual(lines, ["MISSING: gh stack (install: gh extension install github/gh-stack)"])

    def test_old_version_counts_as_missing(self):
        self.fake("herdr", "herdr 0.8.0")
        self.fake("treehouse", "v2.0.1")
        bad, lines = self.deps()
        self.assertEqual(bad, ["herdr"])
        self.assertEqual(lines, ["MISSING: herdr 0.8.0 is older than 0.9.3 (install: see https://herdr.dev)",
                                 f"MISSING: treehouse 2.0.1 is older than 3.1.2 (install: {fc.TREEHOUSE_INSTALL}) - optional"])

    def test_optional_tools_only_warn(self):
        for t in ("pi", "bp", "treehouse", "graft"):
            (self.bin / t).unlink()
        bad, lines = self.deps()
        self.assertEqual(bad, [])
        self.assertEqual([l.split(" (")[0] for l in lines], ["MISSING: treehouse", "MISSING: graft", "MISSING: pi", "MISSING: bp"])
        self.assertTrue(all(l.endswith(" - optional") for l in lines))

    def test_framelink_is_required_only_for_the_designer(self):
        (self.home / ".claude.json").write_text(json.dumps({"mcpServers": {"frame0": {}}}))
        (self.home / SKILLS[-1]).unlink()
        bad, lines = self.deps()
        self.assertEqual(bad, [])  # doctor and init only warn
        self.assertEqual(lines, [f"MISSING: framelink-figma (install: {fc.FRAMELINK_ADD}) - needed for the designer",
                                 "MISSING: framelink-figma token (install: put a Figma personal access token in "
                                 "~/.config/figma-context-mcp/.env as one line FIGMA_API_KEY=<token>, chmod 600) - needed for the designer"])
        out = io.StringIO()
        with mock.patch("sys.stdout", out):
            self.assertEqual(fc.check_deps("designer"), ["framelink-figma", "framelink-figma token"])
        self.assertEqual(len(out.getvalue().splitlines()), 2)  # only what the designer needs, nothing else
        (self.home / ".claude.json").unlink()  # no Claude Code config at all counts as not registered
        with mock.patch("sys.stdout", io.StringIO()):
            self.assertIn("framelink-figma", fc.check_deps("designer"))

    def test_designer_start_stops_without_framelink(self):
        (self.home / SKILLS[-1]).unlink()
        repo = Path(tempfile.mkdtemp())
        r = subprocess.run([sys.executable, CLI, "designer", "--project", "p", "--repo", str(repo)], capture_output=True, text=True,
                           env={**os.environ})
        self.assertEqual(r.returncode, 1)
        self.assertIn("MISSING: framelink-figma token", r.stdout)
        self.assertIn("designer stopped", r.stderr)

    def test_herdr_toasts_and_sounds_warn_when_not_off(self):
        """herdr's own toast and sound fire for every agent that finishes or needs input, so doctor names the two keys to set
        when either is on; delivery defaults to off, sound to on, so a missing key counts as its default."""
        self.assertIsNone(fc.herdr_toast_warning())
        self.herdr_config('onboarding = false\n[ui]\nagent_panel_sort = "spaces"  # a comment\n\n[ui.toast]\ndelivery = "system"\n')
        w = fc.herdr_toast_warning()
        self.assertTrue(w.startswith("WARNING: herdr alerts the product owner for every agent, not only the engineering manager (ui.toast.delivery=system, ui.sound.enabled=true)"), w)
        self.assertIn('set [ui.toast] delivery = "off" and [ui.sound] enabled = false in ~/.config/herdr/config.toml', w)
        self.assertEqual(len(w.splitlines()), 1)
        self.herdr_config('[ui.sound]\nenabled = false\n')  # no [ui.toast] at all: herdr's default delivery is off
        self.assertIsNone(fc.herdr_toast_warning())
        (self.home / ".config" / "herdr" / "config.toml").unlink()  # no config: sounds are on by default
        self.assertIn("(ui.sound.enabled=true)", fc.herdr_toast_warning())

    def test_doctor_and_init_through_the_cli(self):
        env = {**os.environ, "FAST_CODING_NO_TREEHOUSE": "1"}
        r = subprocess.run([sys.executable, CLI, "doctor"], capture_output=True, text=True, env=env)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "every tool fast-coding needs is installed"))
        self.herdr_config('[ui.toast]\ndelivery = "system"\n')
        r = subprocess.run([sys.executable, CLI, "doctor"], capture_output=True, text=True, env=env)  # a warning, never a stop
        self.assertEqual(r.returncode, 0)
        self.assertEqual([l.split(" ")[0] for l in r.stdout.strip().splitlines()], ["WARNING:", "every"])
        self.herdr_config('[ui.toast]\ndelivery = "off"\n\n[ui.sound]\nenabled = false\n')
        (self.bin / "claude").unlink()
        r = subprocess.run([sys.executable, CLI, "doctor"], capture_output=True, text=True, env=env)
        self.assertEqual((r.returncode, r.stdout.strip()), (1, "MISSING: claude (install: curl -fsSL https://claude.ai/install.sh | bash)"))
        repo = Path(tempfile.mkdtemp())  # not even a git repository: init must stop before it touches anything
        r = subprocess.run([sys.executable, CLI, "init", "--project", "p", "--repo", str(repo)], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("MISSING: claude", r.stdout)
        self.assertIn("init stopped", r.stderr)
        self.assertEqual(list(repo.iterdir()), [])
        self.assertFalse((repo.parent / "fast-coding-p").exists())


if __name__ == "__main__":
    unittest.main()
