import io, os, stat, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
import fast_coding as fc

CLI = str(Path(__file__).resolve().parents[1] / "bin" / "fast_coding.py")
TOOLS = {"herdr": "0.9.3", "treehouse": "v3.1.2", "graft": "0.16.0", "gh": "gh version 2.94.0", "pi": "1.0.3", "claude": "2.1.301 (Claude Code)", "npx": "11.19.0", "bp": ""}
SKILLS = (".claude/skills/herdr/SKILL.md", ".claude/plugins/marketplaces/i-have-adhd/skills/i-have-adhd/SKILL.md",
          ".claude/plugins/cache/official/superpowers/7.0.0/skills/writing-plans/SKILL.md")


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
        self.env = mock.patch.dict(os.environ, {"PATH": str(self.bin), "HOME": str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def fake(self, tool, version, body=""):
        f = self.bin / tool
        f.write_text(f"#!/bin/sh\n{body}\necho '{version}'\n")
        f.chmod(stat.S_IRWXU)

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

    def test_doctor_and_init_through_the_cli(self):
        env = {**os.environ, "FAST_CODING_NO_TREEHOUSE": "1"}
        r = subprocess.run([sys.executable, CLI, "doctor"], capture_output=True, text=True, env=env)
        self.assertEqual((r.returncode, r.stdout.strip()), (0, "every tool fast-coding needs is installed"))
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
