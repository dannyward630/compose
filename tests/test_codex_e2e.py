import hermetic  # first: no test sees the real home
import os, pwd, shutil, subprocess, sys, unittest
from pathlib import Path
os.environ["HERDR_ENV"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_setup_e2e import RECORD, TOOLS, SetupE2E

CODEX = shutil.which("codex")
# The account's Codex home holds its sign-in; a scratch one would lose it, and the sign-in is never copied or linked.
SIGNED_IN = Path(os.environ.get("CODEX_HOME") or Path(pwd.getpwuid(os.getuid()).pw_dir) / ".codex")


@unittest.skipUnless(CODEX, "codex is not installed")
class CodexCommandsE2E(SetupE2E, unittest.TestCase):
    """The real codex binary runs a compose command copy that `compose setup` wrote in a scratch home."""

    def test_words_after_the_skill_name_reach_the_shell_line(self):
        r = self.run_setup("--yes", tools={**{t: RECORD for t in TOOLS}, "codex": RECORD}, CODEX_HOME="")
        copy = r.home / ".codex/skills/compose-workspace"
        self.assertTrue((copy / "SKILL.md").is_file(), "\n".join(r.lines))
        # Codex reads the account's own skills folder under SIGNED_IN, so it sees setup's copy through ~/.agents/skills
        (r.home / ".agents/skills").mkdir(parents=True)
        (r.home / ".agents/skills/compose-workspace").symlink_to(copy)
        env = {k: v for k, v in os.environ.items() if not k.startswith("HERDR_")} | {
            "HOME": str(r.home), "CODEX_HOME": str(SIGNED_IN), "PATH": f"{r.home / '.local/bin'}:{os.environ['PATH']}", "PYTHONDONTWRITEBYTECODE": "1"}
        p = subprocess.run([CODEX, "exec", "--ephemeral", "--skip-git-repo-check", "$compose-workspace --help"], cwd=r.home, env=env,
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
        self.assertIn("usage: compose workspace", p.stdout + p.stderr, p.stderr[-3000:])


if __name__ == "__main__":
    unittest.main()
