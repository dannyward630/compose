import re
import fc_config, fc_crew


# ---------- `tool-bug`: a failure of compose itself becomes a scrubbed issue on prodoxx/compose ----------
# Only a gh login with push on the repo posts without asking; anyone else's text is saved for the product owner's go first.
REPO = "prodoxx/compose"  # the issue target is this constant, never the checkout's origin remote
SECTIONS = ("Summary", "Environment", "Symptom", "Root cause", "Reproduction", "Expected", "Actual", "Workaround", "Fix")
TOKEN_RE = re.compile(r"gh[posur]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|lin_api_[A-Za-z0-9]{20,}|(?<=Bearer )\S+")

def scrub(text, login=None):
    """text with $HOME as ~, the OS user and the gh login as <user>, and token-shaped strings as <redacted>."""
    import getpass
    from pathlib import Path
    text = text.replace(str(Path.home()), "~").replace(REPO, "\x00")
    for user in dict.fromkeys([getpass.getuser(), login]):
        if user:
            text = re.sub(rf"\b{re.escape(user)}\b", "<user>", text)
    return TOKEN_RE.sub("<redacted>", text.replace("\x00", REPO))

def environment():
    """The Environment section's lines: the compose commit, the OS, Python, and the versions of the tools compose drives."""
    import platform, shutil, subprocess
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=fc_crew.CLI_REPO, capture_output=True, text=True).stdout.strip()
    lines = [f"- compose: {commit}", f"- OS: {platform.platform()}", f"- Python: {platform.python_version()}"]
    for tool in ("claude", "herdr", "graft", "gh"):
        if shutil.which(tool):
            out = subprocess.run([tool, "--version"], capture_output=True, text=True).stdout.splitlines()
            lines.append(f"- {tool}: {(out or [''])[0].strip()}")
        else:
            lines.append(f"- {tool}: not installed")
    return "\n".join(lines) + "\n"

def issue_text(raw, login=None):
    """(title, body) from a body file's text: the title from its `# ` first line, the body with its sections in input order, Environment
    filled here and Root cause "not found" when it has none, both scrubbed."""
    first, _, rest = raw.partition("\n")
    if not first.startswith("# "):
        raise ValueError("line 1 must be `# <command>: <symptom>`")
    title = first[2:].strip()
    parts = re.split(r"(?m)^## ", rest)
    preamble = parts[0].strip()
    sections = [[name.strip(), content.strip()] for name, _, content in (p.partition("\n") for p in parts[1:])]
    env = environment()
    at = next((i for i, s in enumerate(sections) if s[0] == "Environment"), None)
    if at is None:
        at = next((i + 1 for i, s in enumerate(sections) if s[0] == "Summary"), 0)
        sections.insert(at, ["Environment", env])
    sections[at][1] = env
    at = next((i for i, s in enumerate(sections) if s[0] == "Root cause"), None)
    if at is None:
        at = next((i for i, s in enumerate(sections) if s[0] == "Reproduction"), len(sections))
        sections.insert(at, ["Root cause", "not found"])
    elif not sections[at][1]:
        sections[at][1] = "not found"
    head = f"{preamble}\n\n" if preamble else ""
    body = head + "\n\n".join(f"## {name}\n\n{content}" for name, content in sections) + "\n"
    return scrub(title, login), scrub(body, login)

def gh_status():
    """(state, login): "maintainer" when the login has push on REPO, "reporter" when it does not, ("no-gh", None) when gh is
    absent or not logged in."""
    raise NotImplementedError("gh_status")

def open_matches(title):
    """The open issues on REPO a search for the title's key terms finds: [{"number", "title", "url"}], [] when gh fails."""
    raise NotImplementedError("open_matches")

def post(title, body, comment=None):
    """Open a `bug` issue on REPO, or comment on issue number `comment`; the URL gh prints, None when gh fails."""
    raise NotImplementedError("post")

def record_issue(project, url):
    """Set `issue` on the project's newest tool-bugs.jsonl entry; False when the project has none."""
    raise NotImplementedError("record_issue")

def cmd_tool_bug(a):
    """`tool-bug file --body <file> [--comment N | --new] [--approved]`: scrub, then post on the maintainer's machine or with
    --approved, else save a draft under fc_config.CONFIG_PATH.parent / "tool-bugs"; search before every create, and record the URL."""
    raise NotImplementedError("cmd_tool_bug")
