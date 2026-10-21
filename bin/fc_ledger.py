"""The evidence ledger's write side: evidence events, written as JSON lines in a fenced block of one Linear comment per
batch on the task or feature issue, retried, and kept in memory while unsaved. Stages hand it events and never write
Linear themselves; fc_evidence reads the rows back and derives the `## Evidence` section."""

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

def comment_text(rows):
    """One comment holding a batch of rows in an `evidence` fenced block."""
    raise NotImplementedError("fc_ledger.comment_text")

def add_row(issue, rows):
    """Write the issue's unsaved rows and these as one comment, retried; False while anything stays unsaved."""
    raise NotImplementedError("fc_ledger.add_row")

def unsaved():
    """The rows not saved yet, every issue, in order."""
    raise NotImplementedError("fc_ledger.unsaved")

def record(issue, events):
    """Write the events on the issue, then refresh its `## Evidence` section; the write's result."""
    raise NotImplementedError("fc_ledger.record")

def run_events(proj, repo, meta, result):
    """The evidence events of one finished task's run result, in order."""
    raise NotImplementedError("fc_ledger.run_events")

def counted(repo, proj, meta, ref, rows):
    """Copies of the rows that count for the task: its run, its revision at `ref`, and its current criteria."""
    raise NotImplementedError("fc_ledger.counted")

def record_task(repo, proj, meta, ref, events):
    """`record` for a task issue: write the events, then refresh its `## Evidence` section from the rows that count."""
    raise NotImplementedError("fc_ledger.record_task")

def verify_record(proj, repo, report):
    """Record one verify round's evidence: checks, e2e, review on the feature issue, scoped and acceptance on each task issue; True when all saved"""
    raise NotImplementedError("fc_ledger.verify_record")
