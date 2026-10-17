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
    import subprocess
    def gh(*args):
        try:
            return subprocess.run(["gh", *args], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        except FileNotFoundError:
            return None
    p = gh("api", "user", "--jq", ".login")
    if p is None or p.returncode:
        return "no-gh", None
    login = p.stdout.strip()
    q = gh("api", f"repos/{REPO}", "--jq", ".permissions.push")
    return ("maintainer" if q is not None and q.returncode == 0 and q.stdout.strip() == "true" else "reporter", login)

def open_matches(title):
    """The open issues on REPO a search for the title's key terms finds: [{"number", "title", "url"}], [] when gh fails."""
    import json, subprocess
    symptom = title.partition(": ")[2] or title
    try:
        p = subprocess.run(["gh", "issue", "list", "--repo", REPO, "--state", "open", "--search", symptom,
                            "--json", "number,title,url", "--limit", "5"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return []
    return json.loads(p.stdout) if p.returncode == 0 else []

def post(title, body, comment=None):
    """Open a `bug` issue on REPO, or comment on issue number `comment`; the URL gh prints, None when gh fails."""
    import subprocess
    args = (["issue", "comment", str(comment), "--repo", REPO, "--body", body] if comment is not None
            else ["issue", "create", "--repo", REPO, "--label", "bug", "--title", title, "--body", body])
    try:
        p = subprocess.run(["gh", *args], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        return None
    if p.returncode:
        return None
    out = [l.strip() for l in p.stdout.splitlines() if l.strip()]
    return out[-1] if out else None

def record_issue(project, url):
    """Set `issue` on the project's newest tool-bugs.jsonl entry; False when the project has none."""
    import json
    from pathlib import Path
    path = Path(fc_crew.TOOL_BUGS)
    if not path.exists():
        return False
    lines = path.read_text().splitlines(keepends=True)
    def project_of(line):
        try:
            d = json.loads(line)
        except ValueError:
            return None
        return d.get("project") if isinstance(d, dict) else None
    hits = [i for i, l in enumerate(lines) if project_of(l) == project]
    if not hits:
        return False
    entry = json.loads(lines[hits[-1]])
    entry["issue"] = url
    lines[hits[-1]] = json.dumps(entry) + "\n"
    path.write_text("".join(lines))
    return True

def cmd_tool_bug(a):
    """`tool-bug file --body <file> [--comment N | --new] [--approved]`: scrub, then post on the maintainer's machine or with
    --approved, else save a draft under fc_config.CONFIG_PATH.parent / "tool-bugs"; search before every create, and record the URL."""
    import sys, time
    from pathlib import Path

    raw = Path(a.body).read_text()
    state, login = gh_status()
    try:
        title, body = issue_text(raw, login)
    except ValueError as e:
        sys.exit(str(e))

    def save_draft():
        d = fc_config.CONFIG_PATH.parent / "tool-bugs"
        d.mkdir(parents=True, exist_ok=True)
        p = d / (time.strftime("%Y%m%d-%H%M%S") + ".md")
        p.write_text(f"# {title}\n\n{body}")
        return p

    if state == "no-gh" or (state == "reporter" and not a.approved):
        p = save_draft()
        print(f"saved {p}\nto post it: compose tool-bug file --project {a.project} --body {p} --approved"
              + (", after `gh auth login`" if state == "no-gh" else ""))
        return
    if a.comment is not None:
        url = post(title, body, comment=a.comment)
    elif a.new:
        url = post(title, body)
    else:
        matches = open_matches(title)
        if matches:
            for m in matches:
                print(f"#{m['number']} {m['title']} {m['url']}")
            print("an open issue may already cover this: comment on it with --comment <n>, or file a new one with --new")
            sys.exit(2)
        url = post(title, body)
    if url is None:
        p = save_draft()
        print(f"saved {p}\ngh could not post it; retry with: compose tool-bug file --project {a.project} --body {p} --approved")
        sys.exit(1)
    print(url)
    record_issue(a.project, url)
