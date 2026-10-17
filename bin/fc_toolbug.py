import re
import fc_config, fc_crew


# ---------- `tool-bug`: a failure of compose itself becomes a scrubbed issue on prodoxx/compose ----------
# Only a gh login with push on the repo posts without asking; anyone else's text is saved for the product owner's go first.
REPO = "prodoxx/compose"  # the issue target is this constant, never the checkout's origin remote
SECTIONS = ("Summary", "Environment", "Symptom", "Root cause", "Reproduction", "Expected", "Actual", "Workaround", "Fix")
TOKEN_RE = re.compile(r"(?!)")  # token-shaped strings scrub replaces; matches nothing until it is written

def scrub(text, login=None):
    """text with $HOME as ~, the OS user and the gh login as <user>, and token-shaped strings as <redacted>."""
    raise NotImplementedError("scrub")

def environment():
    """The Environment section's lines: the compose commit, the OS, Python, and the versions of the tools compose drives."""
    raise NotImplementedError("environment")

def issue_text(raw, login=None):
    """(title, body) from a body file's text: the title from its `# ` first line, the body with its sections in input order, Environment
    filled here and Root cause "not found" when it has none, both scrubbed."""
    raise NotImplementedError("issue_text")

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
