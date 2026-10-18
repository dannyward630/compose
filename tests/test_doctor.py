import hermetic  # first: no test sees the real home
import io, json, os, re, stat, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock
os.environ["HERDR_ENV"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))
for _m in [m for m in sys.modules if m.startswith("fc_") and m not in ("fc_cost", "fc_mcp", "fc_sessions")]: del sys.modules[_m]
import compose as fc
import fc_steps, fc_auth

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

class DoctorNotes(unittest.TestCase):
    """Without claude, doctor names the rows that need it on one line under the Claude Code install line; keys still in
    config.json or .env get one WARNING naming each key and file, never a value."""
    setUp, fake, herdr_config = Doctor.setUp, Doctor.fake, Doctor.herdr_config
    CURL = "curl -fsSL https://claude.ai/install.sh | bash"
    ROWS = (("claude", "claude", CURL, "required", False, "manual"), ("gh", "gh", "brew install gh", "required", False, "run"),
            ("i-have-adhd skill", lambda c: (False, ""), "claude plugin install a", "required", True, "run"),
            ("superpowers", lambda c: (False, ""), "claude plugin install b", "default", True, "run"),
            ("herdr claude integration", lambda c: (True, ""), "herdr integration install claude", "default", True, "run"),
            ("uv", lambda c: (False, ""), "brew install uv", "default", False, "run"))

    def doctor(self, rows=ROWS, keys=()):
        out, code = io.StringIO(), 0
        with mock.patch.object(fc_steps, "STEPS", rows), mock.patch.object(fc_auth, "old_keys", return_value=list(keys)) as self.old:
            with mock.patch("sys.stdout", out):
                try:
                    fc.fc_init.cmd_doctor(None)
                except SystemExit as e:
                    code = e.code
            with mock.patch("sys.stdout", io.StringIO()):
                self.bad = fc.fc_init.check_deps()
        return code, out.getvalue().splitlines()

    def test_rows_waiting_on_claude_share_one_line(self):
        (self.bin / "claude").unlink()
        code, lines = self.doctor()
        missing = [l for l in lines if l.startswith("MISSING")]
        self.assertEqual((code, self.bad, len(missing)), (1, ["claude", "i-have-adhd skill"], 2))
        self.assertTrue(re.match(r"MISSING: claude\b", missing[0]) and self.CURL in missing[0] and missing[1].startswith("MISSING: uv"), missing)
        wait = [l for l in lines if l.startswith("waiting on Claude Code: ")]
        self.assertEqual(len(wait), 1, lines)
        self.assertGreater(lines.index(wait[0]), lines.index(missing[0]))
        self.assertEqual([n in wait[0] for n in ("i-have-adhd skill", "superpowers", "herdr claude integration", "uv", "gh")], [True, True, False, False, False])

    def test_with_claude_rows_report_like_any_other(self):
        code, lines = self.doctor()
        self.assertEqual((code, self.bad), (1, ["i-have-adhd skill"]))
        self.assertEqual([l.split(" (")[0] for l in lines if l.startswith(("MISSING", "waiting"))],
                         ["MISSING: i-have-adhd skill", "MISSING: superpowers", "MISSING: uv"])

    def test_old_keys_warn_once_by_name_and_file(self):
        cfg, env = self.home / "config.json", self.home / ".env"
        cfg.write_text(json.dumps({"openrouter_api_key": "sk-or-test", "workspaces": {"w": {"linear_api_key": "lin-test"}}}))
        env.write_text("TYPESAFE_API_KEY=ts-test\n")
        keys = [("openrouter_api_key", cfg), ("workspaces.w.linear_api_key", cfg), ("TYPESAFE_API_KEY", env)]
        with mock.patch.object(fc.fc_config, "CONFIG_PATH", cfg), mock.patch.object(fc.fc_config, "ENV_FILE", env):
            self.assertEqual(self.doctor(self.ROWS[:2]), (0, ["every tool compose needs is installed"]))
            code, lines = self.doctor(self.ROWS[:2], keys)
            self.assertEqual((self.old.call_args, lines[-1]), (mock.call(cfg, env), "every tool compose needs is installed"))
            warn = [l for l in lines if l.startswith("WARNING:")]
            self.assertEqual((code, len(warn)), (0, 1), lines)
            self.assertTrue(all(str(x) in warn[0] for k in keys for x in k) and "auth.json" in warn[0], warn)
            self.assertFalse({"sk-or-test", "lin-test", "ts-test"} & set(re.findall(r"[\w-]+", "\n".join(lines))))
            self.herdr_config('[ui.toast]\ndelivery = "system"\n')
            code, lines = self.doctor(self.ROWS[:2], keys)
            self.assertEqual(sorted(l.startswith("WARNING: herdr") for l in lines if l.startswith("WARNING:")), [False, True])

class DoctorWarnings(unittest.TestCase):
    """doctor prints every line (gh, old keys, herdr config) before a required miss exits 1, and ends with one summary;
    loud herdr config is an optional row; init's stop line names the tool rows that stop it."""
    setUp, fake, herdr_config = Doctor.setUp, Doctor.fake, Doctor.herdr_config
    OK = (("gh", "gh", "brew install gh", "required", False, "run"), ("claude", "claude", "curl x", "required", False, "manual"))
    MISS = (("npx", "no-such-npx", "brew install node", "required", False, "run"),
            ("gh auth", lambda c: (False, "not logged in"), "compose setup", "required", False, "interactive"),
            ("uv", lambda c: (False, "not on PATH"), "brew install uv", "default", False, "run"))
    HERDR, READY = "MISSING: herdr config: {} (install: compose setup) - optional", "every step compose needs is ready"

    def doctor(self, rows, keys=()):  # gh is logged out; a real "herdr config" row, if the table has one, stays
        self.fake("gh", "gh version 2.94.0", body='[ "$1 $2" = "auth status" ] && exit 1')
        rows += tuple(r for r in fc_steps.STEPS if r[0] == "herdr config")
        out, code = io.StringIO(), 0
        with mock.patch.object(fc_steps, "STEPS", rows), mock.patch.object(fc_auth, "old_keys", return_value=list(keys)), \
             mock.patch("sys.stdout", out):
            try:
                fc.fc_init.cmd_doctor(None)
            except SystemExit as e:
                code = e.code
        return code, out.getvalue().splitlines()

    def test_a_required_miss_still_prints_every_line_then_exits_1(self):
        self.herdr_config('[ui.toast]\ndelivery = "system"\n')
        keys = [("openrouter_api_key", self.home / "config.json"), ("TYPESAFE_API_KEY", self.home / ".env")]
        code, lines = self.doctor(self.OK + self.MISS, keys)
        self.assertEqual((code, lines[-1]), (1, "2 required steps missing: run compose setup"))
        for line in (Doctor.GH_WARNING, self.HERDR.format("ui.toast.delivery=system, ui.sound.enabled=true"),
                     "MISSING: gh auth: not logged in (install: compose setup)", "MISSING: uv: not on PATH (install: brew install uv) - optional"):
            self.assertIn(line, lines)
        self.assertEqual([l for l in lines if l.startswith("WARNING: herdr") or "every tool" in l], [])
        warn = [l for l in lines if "openrouter_api_key" in l]
        self.assertEqual(len(warn), 1, lines)
        self.assertTrue(all(str(x) in warn[0] for k in keys for x in k), warn)
        self.assertTrue("differ" in warn[0] and "auth.json" in warn[0] and "remove the one you do not want" in warn[0], warn)
        self.assertNotIn("next time", warn[0])

    def test_herdr_config_row_quiet_absent_and_sound_only(self):
        self.assertEqual(self.doctor(self.OK), (0, [Doctor.GH_WARNING, self.READY]))  # quiet: no herdr line at all
        for text, loud in ((None, "ui.sound.enabled=true"), ('[ui.toast]\ndelivery = "off"\n[ui.sound]\nenabled = true\n', "ui.sound.enabled=true"),
                           ('[ui.toast]\ndelivery = "system"\n[ui.sound]\nenabled = false\n', "ui.toast.delivery=system")):
            with self.subTest(text=text):
                (self.home / ".config" / "herdr" / "config.toml").unlink(missing_ok=True)
                text and self.herdr_config(text)
                code, lines = self.doctor(self.OK)  # optional: exit 0, and the summary still says ready
                self.assertEqual((code, lines[-1], sorted(lines[:-1])), (0, self.READY, sorted([Doctor.GH_WARNING, self.HERDR.format(loud)])))

    def test_init_stop_line_names_the_tool_rows_that_stop_it(self):
        skill = ("herdr skill", ".claude/skills/none/SKILL.md", "herdr --skill", "required", False, "run")
        (self.home / "repo").mkdir()  # not a git repository: init must stop before it touches it
        a = mock.Mock(repo=str(self.home / "repo"), project="p", branch=None, here=False, after=None)
        with mock.patch.object(fc_steps, "STEPS", self.OK + self.MISS + (skill,)), mock.patch("sys.stdout", io.StringIO()), \
             self.assertRaises(SystemExit) as e:
            fc.fc_init.cmd_init(a)
        m = re.match(r"init stopped: (.+?) missing; ", str(e.exception.code))
        self.assertTrue(m, e.exception.code)
        self.assertEqual([n in m.group(1) for n in ("npx", "herdr skill", "gh auth", "uv")], [True, True, False, False])

class InitGate(unittest.TestCase):
    """init stops only on a missing required tool row, one whose check is a command, a command list, or a file under home;
    a required row checked by a function prints its MISSING line and init goes on. doctor exits 1 on either."""
    fake = Doctor.fake
    SKILL = ".claude/skills/herdr/SKILL.md"
    TOOLS = (("npx", "npx", "brew install node", "required", False, "run"),
             ("gh stack", ["gh", "stack", "--version"], "gh extension install github/gh-stack", "required", False, "run"),
             ("herdr skill", SKILL, "herdr --skill", "required", False, "run"))
    NOT_TOOLS = tuple((n, lambda c: (False, ""), "compose setup", "required", False, m) for n, m in (
        ("gh auth", "interactive"), ("compose CLI link", "write"), ("~/.local/bin on PATH", "manual"), ("OpenRouter key", "key")))

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bin, self.home, self.repo = self.tmp / "bin", self.tmp / "home", self.tmp / "repo"
        for d in (self.bin, (self.home / self.SKILL).parent, self.repo):
            d.mkdir(parents=True)
        (self.home / self.SKILL).write_text("# skill")
        self.fake("npx", "11.19.0"), self.fake("gh", "gh version 2.94.0", body='[ "$1" = stack ] || exit 1')  # gh auth fails
        env = mock.patch.dict(os.environ, {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.home), "HERDR_ENV": "",
                                           "COMPOSE_CONFIG": str(self.home / ".compose" / "config.json"), "COMPOSE_NO_TREEHOUSE": "1", "COMPOSE_NO_TRAIL": "1"})
        env.start(), self.addCleanup(env.stop)
        [os.environ.pop(k, None) for k in ("OPENROUTER_API_KEY", "TEXT_MODEL_API_KEY", "OPENCODE_CONFIG_CONTENT", "TYPESAFE_API_KEY")]
        subprocess.run("git init -q && git -c user.name=t -c user.email=t@t commit -q --allow-empty -m i", shell=True, cwd=self.repo, check=True)

    def run_cmd(self, cmd, rows):
        out, code = io.StringIO(), 0
        a = mock.Mock(repo=str(self.repo), project="p", branch=None, here=False, after=None)
        with mock.patch.object(fc_steps, "STEPS", rows), mock.patch("sys.stdout", out):
            try:
                cmd(a)
            except SystemExit as e:
                code = e.code
        return code, out.getvalue()

    def assert_init(self, rows, stops):
        code, out = self.run_cmd(fc.fc_init.cmd_init, rows)
        created = (self.tmp / "compose-p" / ".compose" / "p" / "verify.json").exists()
        self.assertEqual(("init stopped" in str(code), created), (stops, not stops), out)
        if stops:  # before anything is created: no worktree, no branch
            self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["bin", "home", "repo"])
            self.assertEqual(subprocess.run(["git", "branch", "--list", "compose/p"], cwd=self.repo, capture_output=True, text=True).stdout, "")
        self.assertEqual(self.run_cmd(fc.fc_init.cmd_doctor, rows)[0], 1)
        return out

    def test_required_rows_checked_by_a_function_never_stop_init(self):
        out = self.assert_init(self.TOOLS + self.NOT_TOOLS, stops=False)
        self.assertEqual([n for n, *_ in self.NOT_TOOLS if f"MISSING: {n} (" not in out], [])

    def test_each_kind_of_missing_tool_row_stops_init(self):
        for i, check in enumerate(("no-such-tool", ["gh", "no-such-extension"], ".claude/skills/none/SKILL.md")):
            with self.subTest(check=check):
                self.assert_init(self.TOOLS[:i] + ((self.TOOLS[i][0], check) + self.TOOLS[i][2:],) + self.TOOLS[i + 1:] + self.NOT_TOOLS, stops=True)

    def test_the_check_kind_and_level_decide_not_the_name(self):
        uv = ("uv", "uv", "brew install uv", "required", False, "run")  # a default row in the real table, made required here
        self.assert_init(self.TOOLS + (uv,), stops=True)
        git = ("git", lambda c: (False, ""), "xcode-select --install", "required", False, "manual")
        self.assert_init(self.TOOLS + (git, uv[:3] + ("default",) + uv[4:]), stops=False)


if __name__ == "__main__":
    unittest.main()
