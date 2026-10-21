import re
from pathlib import Path
import fc_core, fc_config, fc_worktree, fc_crew


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
    for tool in ("claude", "herdr", "trail", "gh"):
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

def find_entry(project, at):
    """(project, at, note) of the tool-bugs.jsonl entry `at` names: the project's own entry at that time, else the one entry of any
    project at that time, else the one entry within 2 seconds of it (a `compose watch` event can show a second off), with a note
    saying which one was used. (project, at, None) when nothing matches; ValueError listing the candidates when several do."""
    import json
    from datetime import datetime
    log = Path(fc_crew.TOOL_BUGS)
    keys = []
    for line in log.read_text().splitlines() if log.exists() else []:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict) and isinstance(e.get("project"), str) and isinstance(e.get("at"), str) and (e["project"], e["at"]) not in keys:
            keys.append((e["project"], e["at"]))
    if (project, at) in keys:
        return project, at, None
    def secs(t):
        try:
            return datetime.strptime(t, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    want = secs(at)
    for found in ([k for k in keys if k[1] == at],
                  [k for k in keys if want and secs(k[1]) and abs((secs(k[1]) - want).total_seconds()) <= 2]):
        if len(found) > 1:
            raise ValueError(f"{len(found)} tool-bugs.jsonl entries match {at}, pass the exact time of one:\n"
                             + "\n".join(f"  {p} at {t}" for p, t in found))
        if found:
            return found[0][0], found[0][1], f"{at} matched the entry of {found[0][0]} at {found[0][1]}"
    return project, at, None

def record_issue(project, url, at, field="issue"):
    """Set `field` (`issue`, or `pr`) on the project's last tool-bugs.jsonl entry whose `at` is `at`, only when it has none yet; the URL
    that entry holds afterwards (the new one or the kept one), None when no entry of the project has that `at`."""
    import json
    log = fc_crew.TOOL_BUGS
    if not log.exists():
        return None
    lines = log.read_text().splitlines(keepends=True)
    for i in range(len(lines) - 1, -1, -1):
        try:
            e = json.loads(lines[i])
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        if e.get("project") == project and e.get("at") == at:
            if field in e:
                return e[field]
            e[field] = url
            lines[i] = json.dumps(e) + "\n"
            log.write_text("".join(lines))
            return url
    return None

def cmd_tool_bug_pr(a):
    """`tool-bug pr --worktree <path>`: push the toolsmith's branch from its own worktree of the compose repo and open a PR on REPO that
    fixes the entry's issue, recorded on the entry as `pr`. Refused off the maintainer's machine, for a worktree that is the installed
    copy, a main checkout, or on main or master, and for a branch with nothing to propose; never merges."""
    import json, subprocess, sys
    wt = Path(a.worktree).resolve()
    state, login = gh_status()
    if state != "maintainer":
        sys.exit(f"this gh login cannot open a pull request on {REPO}: file the issue with `compose tool-bug file` instead")
    if fc_worktree.common_dir(wt) is None or fc_worktree.common_dir(wt) != fc_worktree.common_dir(fc_crew.CLI_REPO):
        sys.exit(f"{wt} is no worktree of the compose repo {fc_crew.CLI_REPO}: the fix belongs in your own worktree of it")
    if (why := fc_worktree.shared_checkout(wt, fc_crew.CLI_REPO)):
        sys.exit(f"{why}: a toolsmith never commits there. Fix on a branch in your own worktree of the compose repo, then run this again from it")
    if fc_core.sh(["git", "status", "--porcelain"], wt, check=False).stdout.strip():
        sys.exit(f"{wt} has uncommitted changes: commit them on your branch first")
    base = fc_worktree.default_branch(wt) or "main"
    if fc_core.sh(["git", "fetch", "-q", "origin"], wt, check=False).returncode:
        sys.exit("git fetch origin failed: this machine cannot reach the compose repo's remote, so no branch can be pushed")
    subjects = fc_core.sh(["git", "log", "--reverse", "--format=%s", f"origin/{base}..HEAD"], wt, check=False).stdout.splitlines()
    if not subjects:
        sys.exit(f"{wt} has no commit past origin/{base}: commit the fix on your branch first")
    branch = fc_core.sh(["git", "branch", "--show-current"], wt).stdout.strip()
    project, at, note = a.project, a.entry, None
    if at is not None:
        try:
            project, at, note = find_entry(project, at)
        except ValueError as e:
            sys.exit(str(e))
    log, entry = Path(fc_crew.TOOL_BUGS), {}
    for line in log.read_text().splitlines() if log.exists() else []:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("project") == project and (at in (None, d.get("at"))):
            entry = d
    n = re.search(r"/issues/(\d+)$", entry.get("issue", ""))
    pushed = fc_core.sh(["git", "push", "-q", "-u", "origin", branch], wt, check=False)
    if pushed.returncode:
        sys.exit(f"git push of {branch} failed: {' '.join((pushed.stdout + pushed.stderr).split())}")
    title, body = scrub(a.title or subjects[0], login), scrub("\n".join(f"- {s}" for s in subjects) + (f"\n\nFixes #{n.group(1)}" if n else ""), login)
    p = subprocess.run(["gh", "pr", "create", "--repo", REPO, "--base", base, "--head", branch, "--title", title, "--body", body],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    out = [l.strip() for l in p.stdout.splitlines() if l.strip()]
    if p.returncode or not out:
        sys.exit(f"{branch} is pushed but gh could not open the PR: {' '.join((p.stdout + p.stderr).split())}")
    print(out[-1])
    if note:
        print(note)
    if entry and record_issue(project, out[-1], entry["at"], "pr") != out[-1]:
        print(f"{out[-1]} not recorded: {entry['at']} already links another PR")
    elif a.entry and not entry:
        print(f"{out[-1]} not recorded: no tool-bugs.jsonl entry has at {a.entry}, or within 2 seconds of it")

def cmd_tool_bug(a):
    """`tool-bug file --body <file> [--comment N | --new] [--approved]`: scrub, then post on the maintainer's machine or with
    --approved, else save a draft under fc_config.CONFIG_PATH.parent / "tool-bugs"; search before every create, and record the URL.
    `tool-bug pr --worktree <path>` opens the fix's PR (cmd_tool_bug_pr). A toolsmith's filing from a main checkout of the compose
    repo or from the installed copy is refused."""
    import os, sys, time

    if a.action == "pr":
        return cmd_tool_bug_pr(a)
    if os.environ.get("COMPOSE_ROLE") == "toolsmith" and (why := fc_worktree.shared_checkout(Path.cwd(), fc_crew.CLI_REPO)):
        sys.exit(f"{why}: a toolsmith works in its own worktree of the compose repo, never in a shared checkout. Run this from your worktree")
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
              + (f' --entry "{a.entry}"' if a.entry else "") + (", after `gh auth login`" if state == "no-gh" else ""))
        return
    project, at, note = a.project, a.entry, None
    if at is not None:
        try:
            project, at, note = find_entry(project, at)
        except ValueError as e:
            sys.exit(str(e))
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
        print(f"saved {p}\ngh could not post it; retry with: compose tool-bug file --project {a.project} --body {p} --approved"
              + (f' --entry "{a.entry}"' if a.entry else ""))
        sys.exit(1)
    print(url)
    if note:
        print(note)
    if a.entry is None:
        print(f'{url} not recorded: pass --entry "<at>" to link it to the tool-bugs.jsonl entry it fixes')
        return
    got = record_issue(project, url, at)
    if got is None:
        print(f"{url} not recorded: no tool-bugs.jsonl entry has at {a.entry}, or within 2 seconds of it")
    elif got != url:
        print(f"{url} not recorded: {a.entry} already links {got}")
