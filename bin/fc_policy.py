"""The project's mandatory verification policies: the Linear document titled "Verification policies" in the repo's Linear
project, one `## ` section per policy with a plain-language statement, an optional `globs:` line and a `checks:` line."""

import fnmatch

import fc_config, fc_linear, fc_linear_cmd

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


class _Duplicate(RuntimeError):
    """More than one document titled "Verification policies"; raised out of the retry instead of retried."""


def read_policies(repo):
    """(policies, note) read from the repo's Linear project; raises RuntimeError when the document cannot be read."""
    if not fc_config.LINEAR_KEY:
        return [], "policies unavailable: no Linear key"
    for _ in range(2):
        try:
            p = fc_linear_cmd.linear_project(repo)
            docs, after = [], None
            while True:
                page = fc_linear.linear_gql("query($id: String!, $after: String) { project(id: $id) { documents(first: 100, after: $after) { pageInfo { hasNextPage endCursor } nodes { id title updatedAt } } } }",
                                            {"id": p["id"], "after": after})["project"]["documents"]
                docs += page["nodes"]
                if not page["pageInfo"]["hasNextPage"]:
                    break
                after = page["pageInfo"]["endCursor"]
            matches = [d for d in docs if d["title"] == POLICY_DOC]
            if len(matches) > 1:
                raise _Duplicate(f"{len(matches)} documents titled Verification policies: {', '.join(d['id'] for d in matches)}")
            if not matches:
                return [], "no Verification policies document"
            doc = fc_linear.linear_gql("query($id: String!) { document(id: $id) { title content url } }", {"id": matches[0]["id"]})["document"]
            return parse_policies(doc["content"]), ""
        except _Duplicate:
            raise
        except (Exception, SystemExit) as e:
            error = e
    raise RuntimeError(f"policies unreadable: {error}")
