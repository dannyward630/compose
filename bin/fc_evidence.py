"""The evidence ledger's read side: the rows of an issue's evidence comments, and the `## Evidence` section of its
description derived from them. fc_ledger writes the rows."""

BLOCK = None
COMMENTS = ""

def parse_comment(body):
    """The rows of every `evidence` block in a comment body."""
    raise NotImplementedError("fc_evidence.parse_comment")

def rows(issue, task_id=None, run_id=None, criterion_id=None):
    """Every evidence row of the issue's comments, once each, oldest first, filtered by task, run, or criterion."""
    raise NotImplementedError("fc_evidence.rows")

def task_rows(issue, feature, task_id):
    """The task issue's rows and the feature issue's rows naming the task or no task, once each, oldest first."""
    raise NotImplementedError("fc_evidence.task_rows")

def table(rows):
    """The `## Evidence` section text: the verdict line and the 60 newest rows."""
    raise NotImplementedError("fc_evidence.table")

def refresh(issue, select=None):
    """Rewrite the issue description's `## Evidence` section from its rows, or from `select(issue)`, best effort."""
    raise NotImplementedError("fc_evidence.refresh")
