"""The project's mandatory verification policies: the Linear document titled "Verification policies" in the repo's Linear
project, one `## ` section per policy with a plain-language statement, an optional `globs:` line and a `checks:` line."""


POLICY_DOC = "Verification policies"


def parse_policies(text):
    """One {"name", "statement", "globs", "checks"} per `## ` heading of the document's markdown."""
    raise NotImplementedError("parse_policies")


def glob_matches(policies, files):
    """The policies with a glob that fnmatches one of `files`, in document order."""
    raise NotImplementedError("glob_matches")


def read_policies(repo):
    """(policies, note) read from the repo's Linear project; raises RuntimeError when the document cannot be read."""
    raise NotImplementedError("read_policies")
