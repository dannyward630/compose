"""The project's mandatory verification policies: the Linear document titled "Verification policies" in the repo's Linear
project, one `## ` section per policy with a plain-language statement, an optional `globs:` line and a `checks:` line."""

import fnmatch

POLICY_DOC = "Verification policies"


def parse_policies(text):
    """One {"name", "statement", "globs", "checks"} per `## ` heading of the document's markdown."""
    policies, parts = [], []
    for line in text.splitlines():
        if line.startswith("## "):
            if policies:
                policies[-1]["statement"] = " ".join(parts)
            parts = []
            policies.append({"name": line[3:].strip(), "statement": "", "globs": [], "checks": []})
        elif policies:
            s = line.strip()
            if s.startswith("globs:"):
                policies[-1]["globs"] = [p for p in (x.strip() for x in s[6:].split(",")) if p]
            elif s.startswith("checks:"):
                policies[-1]["checks"] = [p for p in (x.strip() for x in s[7:].split(",")) if p]
            elif s:
                parts.append(s)
    if policies:
        policies[-1]["statement"] = " ".join(parts)
    return policies


def glob_matches(policies, files):
    """The policies with a glob that fnmatches one of `files`, in document order."""
    return [p for p in policies if any(fnmatch.fnmatch(f, g) for g in p["globs"] for f in files)]


def read_policies(repo):
    """(policies, note) read from the repo's Linear project; raises RuntimeError when the document cannot be read."""
    raise NotImplementedError("read_policies")
