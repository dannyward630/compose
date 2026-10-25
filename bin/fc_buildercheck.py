"""The builder check's brief: a fresh builder reads a written design cold and reports the questions it would still need answered."""
import json, sys

import fc_core, fc_herdr


BUILDER_CHECK_BRIEF = """You are the builder check for project {slug}, a talented builder handed the design on {issue} cold. Worktree: {wt}.

1. Read the artifact: `compose linear get {issue} --body` (its description), then every Linear document it links: `compose linear doc list`, and `compose linear doc get <id>` for each one it names.
2. Plan the build from it with no one to ask. Where the artifact leaves a choice to the builder, make it and move on.
3. When a question might be answered by the repo, look first with `trail ask "<question>"`.
4. Keep only the questions you would still need answered where a wrong guess would change what gets built. For each, say why the guess matters. Rank them by importance, most important first.
5. Skip what the artifact rightly leaves to the builder, and wording nitpicks.
6. You never write Linear and never write files. Report once, then stop:
   `compose report --project {slug} --as {name} done "<n> questions: 1. <question> - <why>; 2. ..."`
   or, when the artifact is enough to build from, `compose report --project {slug} --as {name} done "nothing important left"`.
"""

def cmd_buildercheck(a):
    """Print the builder check's brief for --issue (default: the project's feature), plus the team lead's notes from --extra (or stdin with `-`)."""
    proj = fc_core.project_dir(a); wt = fc_herdr.project_worktree(proj)
    extra = sys.stdin.read() if a.extra == "-" else (a.extra or "")
    feature = (json.loads((proj / "linear.json").read_text()) if (proj / "linear.json").exists() else {}).get("feature", "<feature id>")
    print(BUILDER_CHECK_BRIEF.format(slug=proj.name, wt=wt, issue=a.issue or feature, name=fc_herdr.agent_name(proj.name, "builder-check"))
           + (f"\nProject notes from the team lead:\n{extra.strip()}\n" if extra.strip() else ""))
