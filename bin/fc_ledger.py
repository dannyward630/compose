"""The evidence ledger: evidence events kept as JSON lines in fenced blocks of Linear comments on the task and feature
issues, and the `## Evidence` table derived from them in the issue description. Stages hand it events and never write
Linear themselves."""

KEYS = ()

def event(run_id, commit_sha, task_ids, criterion_id, phase, source, result, fails_on_base, detail):
    """One evidence event: a dict with the keys of KEYS in order and an event_id hashed from the rest."""
    raise NotImplementedError("fc_ledger.event")

def criterion_ids(meta):
    """`<task id>.<order>:<hash of the text>` for each criterion of the task, in order."""
    raise NotImplementedError("fc_ledger.criterion_ids")

def run_id(proj, tid, fresh=False):
    """The task's run id, kept in results/runs.json; a new one when it has none or `fresh` is true."""
    raise NotImplementedError("fc_ledger.run_id")

UNSAVED = []
SAVED = set()
BLOCK = None

def comment_text(rows):
    """One comment holding a batch of rows in an `evidence` fenced block."""
    raise NotImplementedError("fc_ledger.comment_text")

def parse_comment(body):
    """The rows of every `evidence` block in a comment body."""
    raise NotImplementedError("fc_ledger.parse_comment")

def add_row(issue, rows):
    """Write the issue's unsaved rows and these as one comment, retried; False while anything stays unsaved."""
    raise NotImplementedError("fc_ledger.add_row")

def unsaved():
    """The rows not saved yet, every issue, in order."""
    raise NotImplementedError("fc_ledger.unsaved")

COMMENTS = ""

def rows(issue, task_id=None, run_id=None, criterion_id=None):
    """Every evidence row of the issue's comments, once each, oldest first, filtered by task, run, or criterion."""
    raise NotImplementedError("fc_ledger.rows")

def table(rows):
    """The `## Evidence` section text: the verdict line and the 60 newest rows."""
    raise NotImplementedError("fc_ledger.table")

def refresh(issue):
    """Rewrite the issue description's `## Evidence` section from its rows, best effort."""
    raise NotImplementedError("fc_ledger.refresh")

def record(issue, events):
    """Write the events on the issue, then refresh its `## Evidence` section; the write's result."""
    raise NotImplementedError("fc_ledger.record")

def run_events(proj, repo, meta, result):
    """The evidence events of one finished task's run result, in order."""
    raise NotImplementedError("fc_ledger.run_events")
