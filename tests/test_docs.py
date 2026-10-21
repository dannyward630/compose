import hermetic  # first: no test sees the real home
import json
import os
import re
import unittest
from pathlib import Path
os.environ["HERDR_ENV"] = ""

ROOT = Path(__file__).resolve().parents[1]


MOVED = "0h 0a 0e 0b 0g 0d 1 2 3 3b 4 5 6 6a 7 8".split()


def read(rel):
    return (ROOT / rel).read_text()


class CliAndTasksDocs(unittest.TestCase):
    def section(self, text, start, end):
        self.assertIn(start, text)
        body = text.split(start, 1)[1]
        self.assertIn(end, body, f"{end!r} must still follow {start!r}")
        return body.split(end, 1)[0]

    def row(self, section, cmd):
        rows = [l for l in section.splitlines() if l.startswith(f"| `{cmd}`")]
        self.assertEqual(len(rows), 1, f"one row for {cmd} in Teammates and supervision")
        return rows[0]

    def test_cli_rows_name_the_design_commands_and_flags(self):
        sec = self.section(read("docs/cli.md"), "### Teammates and supervision", "### Workspaces")
        for word in ("--figma", "--extra -", "brief"):
            self.assertIn(word, self.row(sec, "designer"))
        for word in ("--only", "--print", "design-NNN"):
            self.assertIn(word, self.row(sec, "designcrews"))
        figma = self.row(sec, "figma check\\|tree\\|judge\\|publish")
        for word in ("check --figma", "tree --only", "Framelink", "judge --only", "linear.json", "results/NNN.tree.txt", "MET", "NOT_MET", "UNCLEAR", "check --plan", "figma_caps", "publish --library", "publish: ask"):
            self.assertIn(word, figma)
        for cmd in ("crew start\\|list\\|focus\\|stop", "explore", "testcrews", "report", "watch", "teardown", "frame0 up", "guard", "rewake", "skillcheck"):
            self.assertIn(f"| `{cmd}", sec)

    def test_tasks_design_section_shows_block_and_rules(self):
        text = read("docs/tasks.md")
        sec = self.section(text, "Three more rules apply", "## Right-sized")
        self.assertIn("\n## Design tasks\n", sec)
        design = sec.split("## Design tasks", 1)[1]
        self.assertIn("```compose\n", design)
        block = design.split("```compose\n", 1)[1].split("```", 1)[0]
        self.assertRegex(block, r"(?m)^kind: design$")
        self.assertRegex(block, r"(?m)^nodes: .+/.+")
        self.assertRegex(block, r"(?m)^test: compose figma judge --project \S+ --only (\d{3}|NNN)$")
        self.assertNotRegex(block, r"(?m)^files:")
        prose = re.sub(r"(?s)````.*?````|```.*?```", "", design)
        for word in ("page", "results/", "files"):
            self.assertIn(word, prose)
        self.assertNotRegex(prose, r"[.!?] [A-Z`]", "one sentence per line")
        for kept in ("files: extension/snapshot.js", "The `model:` field", "Only an issue with the block", "## Sync"):
            self.assertIn(kept, text)

    def test_pages_have_no_em_dash(self):
        for page in ("docs/cli.md", "docs/tasks.md"):
            self.assertNotIn("\u2014", read(page), page)


class HerdrAndWorkspacesDocs(unittest.TestCase):
    def section(self, rel, title):
        return read(rel).split("## " + title + "\n", 1)[1].split("\n## ", 1)[0]

    def test_the_docs_give_the_agent_name_herdr_registers_for_a_long_slug(self):
        import sys; sys.path.insert(0, str(ROOT / "bin"))
        import fc_herdr
        lead = fc_herdr.agent_name("clean-recut-branches", "orchestrator")
        for rel in ("docs/herdr.md", "sections/0h.md"):
            self.assertIn(f"project `clean-recut-branches` has team lead `{lead}`", read(rel).lower())
            self.assertIn("`compose crew list` shows", read(rel))

    def test_roles_table_names_the_design_roles(self):
        rows = {l.split("|")[1].strip(): l for l in self.section("docs/herdr.md", "Roles").splitlines() if l.startswith("|")}
        self.assertIn("tab `designer`, agent `<slug>-designer`", rows.get("designer", ""))
        self.assertIn("Figma", rows.get("designer", ""))
        self.assertIn("Claude only", rows.get("design-NNN", ""))
        self.assertIn("tab `design NNN`", rows.get("design-NNN", ""))
        self.assertIn("screenshot per story", rows.get("design-review", ""))
        self.assertIn("tab `orchestrator`, agent `<slug>-orchestrator`", rows.get("team lead", ""))

    def test_teammate_commands_block_holds_the_design_commands(self):
        code = self.section("docs/herdr.md", "Teammate commands").split("```bash\n", 1)[1].split("```", 1)[0]
        block = [" ".join(l.split()) for l in code.splitlines()]
        for line in (
            "compose figma check --project <slug> --figma <url or key>",
            "compose designer --project <slug> | compose crew start --project <slug> --role designer --title designer --brief -",
            "compose designcrews --project <slug>   # one design-NNN builder per open design task",
            "compose crew start --project <slug> --role orchestrator --title orchestrator --brief - < brief.txt",
            "compose crew list --project <slug>",
        ):
            self.assertIn(" ".join(line.split()), block)

    def test_crew_models_name_the_design_keys(self):
        text = self.section("docs/workspaces.md", "Crew models")
        self.assertIn("`designer`", text)
        self.assertIn("Opus 5.5", text)
        self.assertIn("high", text.split("Opus 5.5", 1)[1].splitlines()[0])
        self.assertIn("`design`", text)
        self.assertIn("design-review", text)
        self.assertIn("first word", text)
        self.assertRegex(text, r"`design-003`[^\n]*`design`")
        self.assertIn("Groundwork and test-writing teammates use `groundwork`.", text)
        self.assertIn("`models.crew` picks each teammate's model by role, then `default`.", text)

    def test_claude_parallel_is_documented_as_a_second_cap_for_claude_sessions(self):
        text = read("docs/workspaces.md")
        part = self.section("docs/workspaces.md", "Parallel")
        self.assertIn('"claude_parallel": 3', text)
        self.assertIn("`claude_parallel` (default 3)", part)
        for command in ("run", "resume", "testcrews"):
            self.assertRegex(part, rf"\| `{command}` \|[^\n]*`claude_parallel`")

    def test_pages_stay_plain_and_one_sentence_per_line(self):
        for rel, title in (("docs/herdr.md", "Roles"), ("docs/workspaces.md", "Crew models")):
            text = read(rel)
            self.assertNotIn("\u2014", text)
            for line in self.section(rel, title).splitlines():
                if not line.startswith("|"):
                    self.assertNotRegex(line, r"[.!?] [A-Z]", line)


class SkillDoc(unittest.TestCase):
    def section(self, start, end="\n### "):
        moved = start.startswith("### ") and start.split()[1].rstrip(".") in MOVED
        text = read("sections/" + start.split()[1].rstrip(".") + ".md") if moved else read("SKILL.md")
        self.assertTrue(start in text, f"no {start!r}")
        body = text[text.index(start) :]
        return body.split(end, 1)[0]

    def test_0d_carries_the_designer_spec(self):
        d = self.section("### 0d. ")
        for phrase in (
            "/compose:designer <ticket>",
            "--figma",
            "designcrews",
            "figma judge --project <slug> --only",
            "kind: design",
            "nodes:",
            "figma:figma-use",
            "design system",
            "Foundations",
            "Components",
            "Hand-off",
            "blocked by",
            "results/NNN.tree.txt",
            "get_design_context",
            "Code Connect",
            "30 variants",
            "models.crew.designer",
            "models.crew.design`",
            "one Framelink image (`download_figma_images`) per story",
            "WRITES ONLY",
            "design_concurrency",
            "figma_caps",
            "compose figma check --project <slug> --plan",
            "compose figma publish --project <slug> --library",
            "publish: ask",
        ):
            self.assertIn(phrase, d)
        self.assertLess(d.index("Foundations"), d.index("Components"))
        self.assertLess(d.index("Components"), d.index("Hand-off"))

    def test_0d_follows_0g_one_sentence_per_line_no_em_dash(self):
        text = read("SKILL.md")
        self.assertLess(text.index("### 0g. "), text.index("### 0d. "))
        d = self.section("### 0d. ")
        self.assertNotIn("\u2014", d)
        for line in d.splitlines():
            if not line.startswith(("|", "#")):
                self.assertNotRegex(line, r"[a-z)`]\. [A-Z]", line)

    def test_who_table_and_0h_name_the_design_crew(self):
        row = next(l for l in read("SKILL.md").splitlines() if l.startswith("| Designer"))
        teammates = next(l for l in self.section("### 0h. ").splitlines() if l.startswith("- **Teammates**"))
        for text in (row, teammates):
            for name in ("design-NNN", "design-review"):
                self.assertIn(name, text)
        self.assertIn("designer", teammates)
        self.assertIn("Linear only", row)
        self.assertIn("product question", row.split(" | ")[-1])

    def test_task_issue_format_names_design_fields(self):
        fmt = self.section("## Task issue format", "\n## Rules")
        self.assertIn("kind: design", fmt)
        self.assertIn("nodes:", fmt)


class DesignerCommand(unittest.TestCase):
    def parts(self):
        text = read("commands/designer.md")
        _, head, body = text.split("---\n", 2)
        return text, dict(line.split(": ", 1) for line in head.splitlines()), body

    def test_frontmatter_matches_the_workspace_command_shape(self):
        _, meta, _ = self.parts()
        self.assertEqual(set(meta), {"description", "argument-hint", "allowed-tools"})
        self.assertEqual(meta["description"].strip('"'), "Start the designer teammate for a ticket: continues design work in Figma from where it stopped")
        self.assertEqual(meta["argument-hint"], '"<Linear url or id> [--figma <file url or key>]"')
        self.assertEqual(meta["allowed-tools"], "Bash(compose designer:*)")

    def test_numbered_steps_name_the_commands_in_order(self):
        _, _, body = self.parts()
        steps = [line for line in body.splitlines() if line[:1].isdigit()]
        self.assertEqual([s.split(".", 1)[0] for s in steps], ["1", "2", "3", "4", "5"])
        self.assertIn("compose skill", steps[0])
        self.assertIn("0j", steps[0])
        self.assertIn("compose projects", steps[1])
        self.assertIn("compose init --project <slug>", steps[1])
        self.assertIn("--figma", steps[2])
        self.assertIn("compose figma check --project <slug> --figma <file>", steps[2])
        pipe = "compose designer --project <slug> | compose crew start --project <slug> --role designer --title designer --brief -"
        self.assertLess(body.index("compose figma check"), body.index(pipe))
        self.assertLess(body.index(pipe), body.index("compose watch --project <slug>"))
        self.assertNotIn("--from designer", body)  # the engineering manager's one watch covers a designer it started: no second watch
        self.assertIn("never start a second watch", body)
        self.assertIn("whatever `--from` says", body)
        self.assertIn('herdr agent prompt <slug>-designer "<answer>"', body)
        self.assertIn("never design in this session", body.lower())

    def test_plain_dashes_and_one_sentence_per_line(self):
        text, _, body = self.parts()
        self.assertNotIn("\u2014", text)
        for line in body.splitlines():
            self.assertNotRegex(line[3:] if line[:1].isdigit() else line, r"\. [A-Z]", line)


class BriefsNameFiles(unittest.TestCase):
    FILES = "SKILL.md, sections/0h.md, sections/0a.md, sections/0e.md, sections/0g.md, sections/4.md, sections/5.md, sections/6.md, sections/6a.md, sections/7.md, sections/8.md and ~/.claude/skills/herdr/SKILL.md, then continue from 0b"
    EM = "The engineering manager's own session is outside the CLI's reach: it runs unrestricted, with every server and skill the product owner has."

    def setUp(self):
        self.text = read("sections/0h.md")
        self.lines = self.text.splitlines()

    def test_team_lead_brief_reads_the_files(self):
        lead = [l for l in self.lines if l.startswith("- **Team lead**")]
        self.assertEqual(len(lead), 1)
        self.assertIn('"read ' + self.FILES + '"', lead[0].replace("\\~", "~"))
        self.assertIn("--role orchestrator --title orchestrator --brief -", lead[0])
        self.assertNotIn("invoke the compose skill", self.text.lower())

    def test_toolsmith_brief_reads_only_skill_md(self):
        block = self.text.split("**When compose itself fails**", 1)[1].split("The team lead reports at every point", 1)[0]
        lines = [l for l in block.splitlines() if "toolsmith" in l and "brief" in l and "SKILL.md" in l]
        self.assertTrue(lines, "a toolsmith brief line names SKILL.md")
        for line in lines:
            self.assertNotIn("sections/", line)
            self.assertNotIn("herdr/SKILL.md", line)
            self.assertNotRegex(line, r"invoke the `?compose`? skill")
        for command in ("compose toolsmith --project <slug> | compose crew start --project <slug> --role toolsmith --work-repo <cli_repo> --brief -",
                        "compose tool-bug file --project <slug> --body", "--approved", "compose tool-bug pr --project <slug> --worktree <path>"):
            self.assertIn(command, block)
        self.assertIn("never edits or commits", block)
        self.assertIn("no `Fixes #n`", block)
        self.assertNotIn("--role toolsmith --cwd", block)  # a session started in the CLI's checkout waits at the trust prompt

    def test_herdr_is_read_as_a_file(self):
        self.assertIn("Then read ~/.claude/skills/herdr/SKILL.md; it carries the safety rules for panes and agents.", self.text.replace("\\~", "~"))
        self.assertNotRegex(self.text.lower(), r"invoke the `?herdr`? skill")

    def test_engineering_manager_sentence_once_after_the_loop(self):
        self.assertEqual(self.text.count(self.EM), 1)
        self.assertIn(self.EM, self.lines, "the sentence sits on its own line")
        loop = next(i for i, l in enumerate(self.lines) if l.startswith("The engineering manager's loop:"))
        change = self.lines.index("**A change of course reaches the product owner through you.**")
        self.assertLess(loop, self.lines.index(self.EM))
        self.assertLess(self.lines.index(self.EM), change)

    def test_no_em_dash(self):
        self.assertNotIn("\u2014", self.text)


class PlannerReadsWritingPlans(unittest.TestCase):
    LS = "`ls ~/.claude/plugins/cache/*/superpowers/*/skills/writing-plans/SKILL.md`"
    SKILLS_OFF = "The planner session starts with skills off, so every skill it needs is read as a file."
    RUN = [
        "Read all of it.",
        f"Then read the writing-plans skill file (the newest of {LS}) for how to write the plan, but not where: the plan is a `## Plan` section in the feature issue's description (`compose linear update <feature> --section \"## Plan\" --file <path>`), never a file in the repo.",
        "Writing-plans' own save path does not apply.",
        SKILLS_OFF,
    ]

    def test_planner_reads_the_newest_writing_plans_file(self):
        text = read("sections/1.md")
        self.assertNotRegex(text, r"(?i)invoke\W*superpowers:writing-plans")
        self.assertIn(self.LS, text)
        self.assertIn("the newest", text)
        self.assertEqual(text.count(self.SKILLS_OFF), 1)

    def test_edited_sentences_keep_their_words_and_order(self):
        flat = " ".join(read("sections/1.md").split())
        self.assertIn(" ".join(self.RUN), flat)

    def test_plain_dashes_and_one_sentence_per_line(self):
        text = read("sections/1.md")
        self.assertNotIn("—", text)
        for line in text.splitlines()[1:]:
            if not line.startswith("|"):
                self.assertNotRegex(line, r"[.!?] [A-Z]", line)


class Frame0OptIn(unittest.TestCase):
    FIRST = "The wayfinder reads SKILL.md and sections/0b.md; nothing else of the skill is loaded."
    OPT_IN = "Frame0 is off by default: a prototype question asks the team lead for a session started with `compose crew start --frame0` (the wayfinder restarted that way, or a helper), and only that session has the `frame0` tools."
    ONLY = "Only a session started with `crew start --frame0` has the `frame0` tools, pointed at that app; draw from such a session, never from an older one."

    def setUp(self):
        self.text = read("sections/0b.md")
        self.lines = self.text.splitlines()

    def test_first_sentence_after_heading(self):
        self.assertEqual(self.lines[0], "### 0b. Find the way first, always")
        self.assertEqual(self.lines[1], self.FIRST)

    def test_opt_in_sits_right_after_the_prototype_line(self):
        self.assertEqual(self.text.count("--frame0` (the wayfinder"), 1)
        self.assertEqual(self.lines.count(self.OPT_IN), 1)
        proto = [i for i, l in enumerate(self.lines) if l.startswith("A **prototype** question about how a screen or flow should look")]
        self.assertEqual(len(proto), 1)
        self.assertEqual(self.lines[proto[0] + 1], self.OPT_IN)
        self.assertTrue(self.lines[proto[0] + 2].startswith("Each project draws in its own Frame0 app"))

    def test_old_sentence_replaced_in_place(self):
        for old in ("points every teammate's `frame0` tools", "started after this change"):
            self.assertFalse(old in self.text, old)
        self.assertEqual(self.lines.count(self.ONLY), 1)
        i = self.lines.index(self.ONLY)
        self.assertTrue(self.lines[i - 1].startswith("Each project draws in its own Frame0 app"))
        self.assertTrue(self.lines[i + 1].startswith("The first tool call makes Frame0 ask"))

    def test_plain_text_rules(self):
        self.assertNotIn("\u2014", self.text)
        # Older lines (e.g. 2-7 of the numbered steps, "`teardown` saves ...") already hold two sentences; the rule covers the new ones.
        for line in (self.FIRST, self.OPT_IN, self.ONLY):
            self.assertNotRegex(line, r"[.!?] [A-Z]", line)


class LinearCommands(unittest.TestCase):
    LEAD = "You create and edit issues and write judgment comments with `compose linear`"
    PROJECT = "Confirm the file points at a real project before any other Linear call: `compose linear project` must print a project on its team."

    def section0(self):
        text = read("SKILL.md")
        return text.split("\n### 0. ", 1)[1].split("\n### 0i. ", 1)[0].splitlines()

    def test_section_0_names_the_verbs_and_the_required_key(self):
        lines = self.section0()
        lead = [l for l in lines if l.startswith(self.LEAD)]
        self.assertEqual(len(lead), 1)
        for verb in ("get <id> [--body] [--comments]", "list --parent <id> | --search", "create", "update <id>", "comment <id>", "labels", "project", "doc"):
            self.assertIn(verb, lead[0])
        self.assertIn("never a Linear MCP tool", lead[0])
        self.assertIn("The Linear key is required: without it `compose doctor` fails and `compose linear` stops with the line that stores one.", lines)
        self.assertIn("Write bodies come from `--file <path>` or stdin, never from the command line.", lines)
        self.assertIn(self.PROJECT, lines)
        self.assertNotIn("fields", "\n".join(lines), "the compact lines replace the fields rule")

    def test_a_failing_call_is_a_compose_linear_call(self):
        self.assertIn("- a `compose linear` call fails (auth, connection, timeout)", read("SKILL.md"))

    def test_labels_and_the_reconcile_use_the_verbs(self):
        text = read("SKILL.md")
        self.assertIn("create the others once with `compose linear labels --create <name>` if `compose linear labels` does not show them", text)
        self.assertIn("`compose linear list --parent <feature>`, then `--parent` each story", text)

    def test_sync_reads_linear_and_the_mcp_recipe_is_gone(self):
        two = read("sections/2.md")
        self.assertIn("Run `compose sync --repo <wt> --project <slug>`: it reads the feature, its stories, and their tasks from Linear", two)
        self.assertIn("`--stdin` reads the same JSON from stdin instead", two)
        self.assertNotIn("--from-linear", two)
        tasks = read("docs/tasks.md")
        self.assertIn("`compose sync` reads the feature, its stories, and their tasks from Linear", tasks)
        self.assertIn("`compose sync --stdin` takes JSON of this shape instead", tasks)
        self.assertIn("The team lead writes everything else on Linear with `compose linear`.", tasks)
        self.assertNotIn("--from-linear", read("docs/cli.md"))

    def test_manager_session_line_and_the_key_requirement_in_the_docs(self):
        self.assertIn("Compose itself uses no Linear MCP, and this session uses `compose linear` too, never a Linear MCP.", read("sections/0h.md").splitlines())
        self.assertNotIn("connector", read("docs/new-machine.md").split("| Keys |", 1)[1].splitlines()[0])
        requirements = [l for l in read("docs/requirements.md").splitlines() if l.startswith("| Linear |")]
        self.assertEqual(len(requirements), 1)
        self.assertNotIn("connector", requirements[0])

    def test_docs_describe_the_verbs(self):
        cli = [l for l in read("docs/cli.md").splitlines() if l.startswith("| `linear <verb>`")]
        self.assertEqual(len(cli), 1)
        for word in ("get <id>", "--section", "labels [--create <name>]", "doc create", "--any-project"):
            self.assertIn(word, cli[0])


class NoLinearMcpToolName(unittest.TestCase):
    NAMES = ("save_issue", "get_issue", "list_issues", "save_comment", "get_project", "list_issue_labels", "create_issue_label",
             "save_document", "mcp__claude_ai_Linear")

    def test_no_shipped_text_names_a_linear_mcp_tool(self):
        files = [ROOT / "SKILL.md", ROOT / "README.md"]
        for rel, pattern in (("sections", "*.md"), ("commands", "*.md"), ("docs", "*.md"), ("bin", "*.py"), ("setup/compose_setup", "*.py")):
            files += sorted((ROOT / rel).glob(pattern))
        self.assertGreater(len(files), 40)
        hits = [f"{f.relative_to(ROOT)}: {n}" for f in files for n in self.NAMES if n in f.read_text()]
        self.assertEqual(hits, [])


    def test_size_and_one_pointer_per_moved_section(self):
        text = read("SKILL.md")
        self.assertLess(len(text.encode()), 30000)
        lines = text.splitlines()
        pointers = [l for l in lines if re.match(r"### \S+\. .*: read sections/\S+\.md$", l)]
        expected = []
        for sid in MOVED:
            title = read(f"sections/{sid}.md").splitlines()[0].split(f"### {sid}. ", 1)[1]
            expected.append(f"### {sid}. {title}: read sections/{sid}.md")
            self.assertEqual(lines.count(expected[-1]), 1, sid)
        self.assertEqual(pointers, expected, "pointer lines keep MOVED order and nothing else points")

    def test_plain_dashes_and_one_sentence_per_line_in_section_0(self):
        text = read("SKILL.md")
        self.assertNotIn("\u2014", text)
        for line in text.split("\n### 0. ", 1)[1].split("\n### 0i. ", 1)[0].splitlines()[1:]:
            if not line.startswith("|"):
                self.assertNotRegex(line, r"[.!?] [A-Z]", line)


class LeadRelaysOnce(unittest.TestCase):
    ONE_LINE = 'needs-user "<issue>: <n> cards <ids>; recommendation <one line>"'

    def setUp(self):
        self.text = read("sections/0h.md").replace("\\~", "~")
        self.lines = self.text.splitlines()
        start = next(i for i, l in enumerate(self.lines) if l.startswith("The engineering manager's loop:"))
        end = next(i for i, l in enumerate(self.lines) if l.startswith("**When compose itself fails**"))
        self.relay = self.lines[start:end]
        self.report = next(i for i, l in enumerate(self.lines) if l.startswith("The team lead reports at every point"))

    def test_lead_forwards_the_one_line_unchanged(self):
        line = next((l for l in self.relay if self.ONE_LINE in l), None)
        self.assertIsNotNone(line, "the relay names the one-line needs-user")
        self.assertIn("wayfinder", line)
        self.assertIn("planner", line)
        self.assertIn("unchanged", line)
        self.assertRegex(line.lower(), r"never re-?sen")

    def test_manager_asks_in_full_and_answers_travel_by_card_id(self):
        relay = "\n".join(self.relay)
        self.assertRegex(relay, r"engineering manager reads the issue once")
        self.assertRegex(relay, r"every card in full")
        self.assertIn('herdr agent prompt <slug>-wayfinder "<card id>: <answer>', relay)

    def test_lead_report_carries_the_line_not_the_cards(self):
        line = self.lines[self.report]
        self.assertNotIn("carrying the wayfinder's open cards", line)
        self.assertIn("needs-user", line)
        self.assertIn("not the cards", line)

    def test_lead_saves_linear_in_few_patches_near_its_reporting_rule(self):
        hits = [i for i, l in enumerate(self.lines) if "compose linear update --section" in l]
        self.assertEqual(len(hits), 1, "one compose linear update --section sentence")
        line = self.lines[hits[0]]
        self.assertLessEqual(abs(hits[0] - self.report), 2, "near the reporting rule")
        for words in ("team lead drafts", "Decisions", "Plan", "one per section", "task issues"):
            self.assertIn(words, line)

    def test_new_lines_are_plain_and_the_older_sentences_stay(self):
        new = [l for l in self.lines if self.ONE_LINE in l or "compose linear update --section" in l or "<card id>" in l]
        self.assertTrue(new)
        for line in new:
            self.assertNotRegex(line, r"[.!?] [A-Z]", line)
        self.assertNotIn("—", self.text)
        self.assertIn(BriefsNameFiles.EM, self.lines)
        self.assertIn('"read ' + BriefsNameFiles.FILES + '"', self.text)
        self.assertIn("Then read ~/.claude/skills/herdr/SKILL.md;", self.text)


class CardsOnTheMap(unittest.TestCase):
    FORM = '`needs-user "<issue>: <n> cards <ids>; recommendation <one line>"`'

    def setUp(self):
        self.text = read("sections/0b.md")
        self.lines = self.text.splitlines()

    def step(self, n):
        start = next(i for i, l in enumerate(self.lines) if l.startswith(f"{n}. "))
        end = next(i for i, l in enumerate(self.lines) if l.startswith(f"{n + 1}. "))
        self.assertLess(start, end, n)
        return self.lines[start:end]

    def test_steps_keep_their_order(self):
        starts = [next(i for i, l in enumerate(self.lines) if l.startswith(f"{n}. ")) for n in range(1, 8)]
        self.assertEqual(starts, sorted(starts))

    def test_step_2_writes_cards_to_the_map_first_numbered(self):
        step = " ".join(self.step(2))
        self.assertRegex(step, r"Not yet specified")
        self.assertRegex(step, r"\bnumbered\b")
        self.assertRegex(step, r"\bfirst\b")
        self.assertIn("recommended option", step, "the card still carries its recommendation")

    def test_step_3_reports_one_line_and_keeps_the_lavish_file(self):
        step = " ".join(self.step(3))
        self.assertIn(self.FORM, step)
        self.assertIn("visual cards open in Lavish: <url>", step)
        self.assertNotIn("the text cards in full", self.text)
        self.assertNotIn("with the text cards", self.text)

    def test_one_working_link_bounded_polls_acknowledged_answers_and_disconnect(self):
        text = " ".join(self.text.split())
        for want in ("`url:` that `lavish-axi <file>` printed", "in no second host form", "a link that does not answer",
                     "already asked and not answered", "answer in text", "rounds of 180000 ms", "--takeover",
                     "reply <file> --agent-reply", "`browser_disconnected`", "`needs-user \"reminder: ...\"`"):
            self.assertIn(want, text)
        self.assertIn("are the options pictures, or words?", text)
        self.assertEqual(self.text.count('is text although tokens are UI'), 1)
        self.assertEqual(self.text.count('is visual.'), 1)

    def test_yolo_answers_are_tagged_unconfirmed_on_the_map(self):
        text = " ".join(self.text.split())
        self.assertIn("`yolo:`", text)
        self.assertIn("(yolo recommendation, unconfirmed, <date>)", text)

    def test_steps_3_and_6_forward_unchanged_read_once_answer_by_card_id(self):
        both = " ".join(self.step(3) + self.step(6))
        self.assertRegex(both, r"team lead forwards[^.]*unchanged")
        self.assertRegex(both, r"engineering manager[^.]*reads the issue once")
        self.assertRegex(both, r"by card id")
        self.assertIn("herdr agent prompt", " ".join(self.step(3)))

    def test_step_6_uses_the_one_line_form(self):
        step = " ".join(self.step(6))
        self.assertNotIn("text cards in a new `needs-user`", step)
        self.assertIn("<n> cards <ids>", step)
        self.assertIn("--agent-reply", step, "visual cards still go on the same page")

    def test_plain_text_and_frame0_sentences_kept(self):
        self.assertNotIn("\u2014", self.text)
        for line in (Frame0OptIn.FIRST, Frame0OptIn.OPT_IN, Frame0OptIn.ONLY):
            self.assertEqual(self.lines.count(line), 1, line)
        new = ("<n> cards <ids>", "unchanged", "reads the issue once", "by card id", "numbered")
        for line in self.step(2) + self.step(3) + self.step(6):
            if any(m in line for m in new):
                self.assertNotRegex(line, r"[.!?] [A-Z]", line)


class PlannerSavesInPatches(unittest.TestCase):
    SAVE_PATH = "Writing-plans' own save path does not apply."

    def rule(self):
        text = read("sections/1.md")
        self.assertIn(self.SAVE_PATH + "\n", text)
        return " ".join(text.split(self.SAVE_PATH, 1)[1].split()).lower()

    def test_drafts_the_whole_plan_then_saves_in_few_patches_one_per_section(self):
        rule = self.rule()
        self.assertRegex(rule, r"drafts? the whole plan")
        self.assertIn("decisions", rule)
        self.assertRegex(rule, r"before (it )?sav")
        self.assertRegex(rule, r"few `compose linear update --section` writes")
        self.assertIn("one per section", rule)

    def test_task_detail_goes_on_task_issues_and_no_reread(self):
        rule = self.rule()
        self.assertIn("task issues", rule)
        self.assertRegex(rule, r"never re-?reads? an issue it just wrote")

    def test_no_reread_because_an_update_prints_only_its_id(self):
        self.assertIn("`compose linear update` prints only `updated <id>`", self.rule())

    def test_rule_is_stated_once_and_earlier_text_stays(self):
        text = read("sections/1.md")
        self.assertEqual(text.count("prints only `updated <id>`"), 1)
        flat = " ".join(text.split())
        self.assertIn(" ".join(PlannerReadsWritingPlans.RUN[:3]), flat)
        self.assertIn(PlannerReadsWritingPlans.SKILLS_OFF, flat)

    def test_plain_dashes_and_one_sentence_per_line(self):
        text = read("sections/1.md")
        self.assertNotIn("\u2014", text)
        for line in text.splitlines()[1:]:
            if not line.startswith("|"):
                self.assertNotRegex(line, r"[.!?] [A-Z]", line)


class OneWatchCoversTheManagersOwnTeammates(unittest.TestCase):
    """A planner or designer the engineering manager starts itself reports to it, and its one watch reports them: no second watch."""

    def test_planner_command_says_the_one_watch_covers_it(self):
        body = read("commands/planner.md").split("---\n", 2)[2]
        self.assertNotIn("--from planner", body)
        self.assertIn("compose watch --project <slug>", body)
        self.assertIn("Never start a second watch", body)
        self.assertIn("`--from orchestrator` watch", body)
        for line in body.splitlines():
            self.assertNotRegex(line, r"\. [A-Z]", line)

    def test_0h_says_the_watch_passes_teammates_the_manager_started(self):
        lines = read("sections/0h.md").splitlines()
        loop = next(i for i, l in enumerate(lines) if l.startswith("The engineering manager's loop:"))
        line = lines[loop + 1]
        self.assertTrue(line.startswith("That one watch also reports every teammate the engineering manager started itself"), line)
        for word in ("`reports_to`", "results/crew/<agent>.json", "`COMPOSE_ROLE`", "whatever `--from` says", "`needs-user` and `blocked`", "Never start a second watch"):
            self.assertIn(word, line)
        self.assertNotIn("—", line)


class NoGraftWord(unittest.TestCase):
    """Every doc names trail: no standalone word graft is left (`graft/`, `GRAFT_NO_*`, and `mcp__graft__` still pass)."""
    GRAFT = re.compile(r"(?<![\w/.@-])graft(?![\w/-])")

    def assert_no_graft(self, *rels):
        for rel in rels:
            for old in ("@nanonets/graft", "brew install graft"):
                self.assertNotIn(old, read(rel), rel)
            for n, line in enumerate(read(rel).splitlines(), 1):
                self.assertNotRegex(line, self.GRAFT, f"{rel}:{n}")

    def test_skill_and_0a(self):
        self.assert_no_graft("SKILL.md", "sections/0a.md")
        skill, zero_a = read("SKILL.md"), read("sections/0a.md")
        self.assertIn("evidence gathered in this session: trail output with file:line, a command", skill)
        rule = [l for l in skill.splitlines() if l.startswith("- Build a trail graph in the repo (`trail build .`")]
        self.assertEqual(len(rule), 1, "one graph rule")
        for cmd in ("`trail ask`", "`trail callers`", "Without trail"):
            self.assertIn(cmd, rule[0])
        # The old map folder is still ignored beside .trail/ and .compose/.
        self.assertIn("`compose init` ignores `.compose/`, `graft/`, and `.trail/` in every checkout", skill)
        self.assertIn("ignores the tool's files: `graft/`, `.trail/` (where trail", zero_a)
        self.assertRegex(zero_a, r"`\.trail/` \(where trail (0\.23 )?keeps the graph\), and `\.compose/`")
        # trail writes no root .ignore, so the doc must not claim one.
        self.assertNotIn("trail's `.ignore`", zero_a)
        self.assertIn("sets trail up in the worktree: wired for Claude Code (`trail init --no-agents --no-global`", zero_a)
        self.assertIn("with every file trail writes kept out of git through `info/exclude`", zero_a)
        self.assertIn("Without trail installed it prints the install command; `compose trail --project <slug>`", zero_a)

    def test_0d_and_0e(self):
        self.assert_no_graft("sections/0d.md", "sections/0e.md")
        design, explore = read("sections/0d.md"), read("sections/0e.md")
        self.assertIn(
            'through trail: `trail ask "design tokens theme css variables" --source`, `trail grep "--color-"`.',
            design,
        )
        self.assertIn("in the repo (`trail grep` for token files, `tailwind.config`, `tokens.json`)", design)
        self.assertIn("It maps the code through trail only, in under 3 minutes,", explore)
        self.assertIn("check it in the code first (`trail ask`, `trail callers`), and if the code cannot settle it", explore)

    def test_4_and_readme(self):
        self.assert_no_graft("sections/4.md", "README.md")
        four, readme = read("sections/4.md").splitlines(), read("README.md").splitlines()
        self.assertIn(
            "Each clone, and the worktree verify runs in, borrows the main checkout's git-ignored installs"
            " (`node_modules` at any depth, `vendor`, `.venv`) as symlinks that never show in `git status`,"
            " and trail never edits `.gitignore` there. So install dependencies once in the project worktree"
            " before `run`; do not patch test commands to link them.",
            four,
        )
        self.assertIn(
            "   An explore teammate maps your codebase through trail,"
            " so no question, ticket, or plan rests on a guess about the code.",
            readme,
        )
        # The trail rename touches only the tool word: the unrelated "trail in the ticket" line stays as is.
        self.assertIn(
            "- Log each steer as a comment on the task's Linear issue, one line,"
            " so the trail is in the ticket and not only in a terminal.",
            four,
        )

    def test_cli_and_requirements(self):
        self.assert_no_graft("docs/cli.md", "docs/requirements.md")
        cli, reqs = read("docs/cli.md").splitlines(), read("docs/requirements.md").splitlines()
        self.assertIn("| `trail` | Sets trail up again in the project's worktree |", cli)
        doctor = [l for l in cli if l.startswith("| `doctor` |")]
        self.assertEqual(len(doctor), 1, "one doctor row")
        self.assertIn("designer extras not set up", doctor[0])
        self.assertIn("| trail | `file:line` context packs for implementers | `npm i -g @trailhq/trail-code` |", reqs)
        self.assertIn("| `COMPOSE_NO_TRAIL=1` | skip trail |", reqs)
        self.assertIn("| `COMPOSE_TEST_SLOTS=<n>` | how many full-suite `compose timed` commands run at once on this machine (default 2); the next waits for a slot and says so. `COMPOSE_QUICK_SLOTS=<n>` is the same for scoped ones (a `-k`/`-run`/`--grep` filter, one test file or module), in lanes apart from the suites (default 2) |", reqs)
        timed = [l for l in cli if l.startswith("| `timed <seconds> -- <command>` |")]
        self.assertEqual(len(timed), 1, "one timed row")
        for part in ("exit 124", "scratch", "COMPOSE_TEST_SLOTS", "COMPOSE_QUICK_SLOTS", "SIGTERM"):
            self.assertIn(part, timed[0])
        # Only the tool word changes: the neighbouring env row stays, and the old graft env row is gone.
        self.assertIn("| `COMPOSE_NO_TREEHOUSE=1` | use plain git worktrees even with treehouse installed |", reqs)
        self.assertFalse([l for l in reqs if "COMPOSE_NO_GRAFT" in l], "COMPOSE_NO_GRAFT")

    def test_how_it_works_and_new_machine(self):
        self.assert_no_graft("docs/how-it-works.md", "docs/new-machine.md")
        how, machine = read("docs/how-it-works.md").splitlines(), read("docs/new-machine.md").splitlines()
        self.assertIn(
            "In a repo that already has code, an explore teammate maps it through trail first"
            " and adds a short codebase brief to the feature.",
            how,
        )
        self.assertIn(
            "1. It reads before it writes: the ticket and its parents with their Decisions so far, the Frame0 wireframes,"
            " the repo's tokens and components through trail, `DESIGN.md`, and what the Figma file already has.",
            how,
        )
        # The folder names stay: init still ignores the old map folder beside .trail/.
        self.assertIn("  `init` git-ignores it, `graft/`, and `.trail/` first.", how)
        # The step table holds the trail and treehouse install row.
        self.assertIn("| trail, treehouse | default | installs `@trailhq/trail-code` and treehouse | no |", machine)


class StackBaseDocs(unittest.TestCase):
    def between(self, rel, first, last):
        # The bullet that starts with `first`, with its continuation lines, up to the line starting with `last`.
        lines = read(rel).splitlines()
        at = next(i for i, l in enumerate(lines) if l.startswith(first))
        end = next(i for i in range(at + 1, len(lines)) if lines[i].startswith(last))
        self.assertNotIn("\u2014", "".join(lines[at:end]))
        return lines[at:end]

    def project_lines(self):
        # Lines 14-15 as edited, held between the untouched bullets around them.
        lines = self.between("sections/0a.md", "- From then on everything", "- Never mix two features")[1:]
        at = next(i for i, l in enumerate(lines) if "init --after <other-slug>" in l)
        self.assertGreater(at, 0, "the trunk line still comes before the --after line")
        return "\n".join(lines[:at]), "\n".join(lines[at:])

    def test_the_stack_sits_on_the_review_base_and_merges_all_or_nothing(self):
        lines = read("sections/0a.md").splitlines()
        for old in ("PRs target it", "final PR"):
            self.assertFalse([l for l in lines if old in l], old)
        trunk, _ = self.project_lines()
        for word in ("`review_base`", "default branch", "`gh stack merge`", "--branch <new>`", "renames its git branch"):
            self.assertIn(word, trunk)
        self.assertRegex(trunk, r"all.or.nothing")

    def test_an_after_project_stacks_on_that_projects_branch(self):
        _, after = self.project_lines()
        for word in ("`review_base`", "`(after <other-slug>)`", "`clean` counts a merge into either."):
            self.assertIn(word, after)
        self.assertRegex(after, r"layers\b[^.]*\b(stack|sit)[^.]*\b(that|the other) project's branch")
        self.assertNotIn("until that one merges", after)

    def test_the_rewritten_project_lines_hold_one_sentence_each(self):
        for line in "\n".join(self.project_lines()).splitlines():
            self.assertNotRegex(line, r"[a-z)`]\. [A-Z`]", line)

    def test_each_epic_feature_has_no_final_pr(self):
        line = " ".join(self.between("SKILL.md", "- **epic**:", "  - **Fog**"))
        self.assertNotIn("final PR", line)
        self.assertTrue(line.startswith("- **epic**: the epic is taken through to done as a unit, but it is never one project:"))
        for word in ("each feature is its own project (0a)", "worktree, team lead,", "stack", "whether its features are known:"):
            self.assertIn(word, line)


class HowItWorksStackBase(unittest.TestCase):
    def setUp(self):
        self.lines = read("docs/how-it-works.md").splitlines()
        self.assertFalse([l for l in self.lines if "\u2014" in l], "em dash")

    def box(self):
        # The flow box: from the line above its top border (`compose run│`) through the bottom border.
        run = next(i for i, l in enumerate(self.lines) if "compose run" in l)
        top = next(i for i in range(run, len(self.lines)) if "┌" in self.lines[i])
        end = next(i for i in range(top, len(self.lines)) if self.lines[i].startswith("  └"))
        return self.lines[top - 1], self.lines[top : end + 1]

    def test_the_box_commits_on_the_project_branch_name(self):
        _, box = self.box()
        self.assertFalse([l for l in box if "fast/" in l], "a fast/ branch in the box")
        self.assertEqual(len([l for l in box if re.fullmatch(r"  │ +format, commit on <project branch>-NNN +│", l)]), 1)

    def test_every_box_line_has_the_same_width_and_right_border(self):
        above, box = self.box()
        self.assertEqual({len(l) for l in box}, {len(box[1])}, [len(l) for l in box])
        self.assertEqual([l[-1] for l in box], ["┐"] + ["│"] * (len(box) - 2) + ["┘"])
        # The run arrow still drops into the box under the `compose run│` line above it.
        self.assertEqual(box[0].index("▼"), above.rindex("│"))
        line = r"  │        yes ─▶ implement \(edits only\) ─▶ CLI runs test, protected untouched, ≤350 lines +│"
        self.assertEqual(len([l for l in box if re.fullmatch(line, l)]), 1)

    def test_the_stack_sits_on_the_review_base_and_merges_all_or_nothing(self):
        self.assertFalse([l for l in self.lines if "trunk is the project branch" in l or "one final PR" in l])
        # The bullet just before the untouched `init --after` bullet, with any continuation lines.
        after = self.lines.index("- `init --after <other>` branches from another project's branch when the feature needs its code.")
        at = max(i for i in range(after) if self.lines[i].startswith("- "))
        self.assertEqual(self.lines[at - 1], "  `init` git-ignores it, `graft/`, and `.trail/` first.")
        line = " ".join(self.lines[at:after])
        for word in ("main", "`review_base`", "`gh stack merge`", "no final PR"):
            self.assertIn(word, line)
        self.assertRegex(line, r"all.or.nothing")
        self.assertRegex(line, r"\b(stack|sit)s?\b[^.]*\breview base\b")


class BranchNamesInSections(unittest.TestCase):
    # Each edit: (file, start of the untouched line above, the edited lines in full, start of the untouched line below).
    EDITS = [
        ("sections/3.md", "When it reports `stubs ready`, run `compose testcrews", [
            "Each test-writing teammate works in its own worktree on its own branch (`<project branch>-tests-NNN`, off the stubs commit), so no teammate can amend or reset another's commit.",
        ], "Tasks that share a protected test file get their writers one after another:"),
        ("sections/3.md", "Each test teammate reports `working \"test ready\"` once", [
            "Read every test once they are all in (`git log -p HEAD..<project branch>-tests-NNN`), send changes back with `herdr agent prompt <slug>-tests-NNN \"...\"` until each tests what its issue says, then tell each to report `done` and run `--collect` before `run`.",
        ], "A test that fails on the stubs because it needs code another task owns"),
        ("sections/5.md", "You are the senior engineer over the fast models.", [
            "`run` ends with a `NNN triage clean|flag: <reason>` line per passed task: a fast model checked each diff against its brief and the simplicity bar, all at once (`compose triage` repeats it). Read flagged layers in full. For a clean layer check only its diffstat (`git diff --stat <base>..<project branch>-NNN`): when every changed file is in the task's `files:`, accept it without reading the diff. Reading every diff of an all-clean run is the time triage exists to save. A flag is a pointer, never a verdict.",
            "Read `.compose/<project>/results/NNN.json` and the layer's own diff: `git diff <base>..<project branch>-NNN`, where `base` is in the result (`HEAD` or the lower task's branch). `gh stack view --json` from a layer branch shows the chain.",
        ], "Passing is not done."),
    ]

    def test_the_edited_lines_name_the_project_branch_between_untouched_neighbours(self):
        for rel, above, edited, below in self.EDITS:
            lines = read(rel).splitlines()
            at = [i for i, l in enumerate(lines) if l.startswith(above)]
            self.assertEqual(len(at), 1, (rel, above))
            end = at[0] + 1 + len(edited)
            self.assertEqual(lines[at[0] + 1 : end], edited, rel)
            self.assertTrue(lines[end].startswith(below), (rel, lines[end]))

    def test_no_fast_branch_or_em_dash_is_left_in_either_file(self):
        for rel in ("sections/3.md", "sections/5.md"):
            self.assertFalse([l for l in read(rel).splitlines() if "fast/" in l or "—" in l], rel)

    def test_each_new_name_appears_only_where_the_old_one_was(self):
        three, five = read("sections/3.md"), read("sections/5.md")
        self.assertEqual(three.count("<project branch>-tests-NNN"), 2)
        self.assertEqual(three.count("<project branch>-NNN"), 0, "the test writer's branch keeps its tests- part")
        self.assertEqual(five.count("<project branch>-NNN"), 2)
        self.assertEqual(five.count("<project branch>"), 2)
        # The results path and the herdr teammate name are not branches and keep their placeholders.
        self.assertEqual(five.count(".compose/<project>/results/NNN.json"), 1)
        self.assertEqual(three.count("herdr agent prompt <slug>-tests-NNN"), 1)


class StackDocs(unittest.TestCase):
    def setUp(self):
        # sections/4.md lines 8-11 plus the new cap line, between the untouched trunk and lockfile lines.
        lines = read("sections/4.md").splitlines()
        at = [i for i, l in enumerate(lines) if l.startswith("The trunk is the branch the user is on")]
        end = [i for i, l in enumerate(lines) if l.startswith("Lockfiles (`package-lock.json`")]
        self.assertEqual((len(at), len(end)), (1, 1))
        self.region = lines[at[0] + 1 : end[0]]

    def test_the_edited_lines_hold_one_sentence_each_and_no_em_dash(self):
        self.assertFalse([l for l in self.region if "\u2014" in l or re.search(r"[a-z)`]\. [A-Z`]", l)])

    def one(self, word):
        found = [l for l in self.region if word in l]
        self.assertEqual(len(found), 1, (word, found))
        return found[0]

    def test_the_chain_and_naming_line_default_to_project_branch_layers(self):
        chain = self.one("(main) <- ")
        self.assertIn("`(main) <- <project branch>-layer-01 <- <project branch>-layer-02 <- ...`", chain)
        self.assertNotIn("fast/", chain)
        naming = self.one("`task_prefix`")
        for word in ("`<project branch>-NNN`", "-tests-NNN`", "-layer-NN`", "every project"):
            self.assertIn(word, naming)
        # The old default, tied to a stored branch, is gone.
        self.assertFalse([l for l in self.region if "else `fast/" in l or "stored `branch`" in l])

    def test_the_naming_line_keeps_the_legacy_rule_with_both_prefixes(self):
        naming = self.one("`task_prefix`")
        for word in ("`fast/<project>/`", "`layer_prefix`", "verify.json", "`clean`"):
            self.assertIn(word, naming)
        self.assertLess(naming.index("<project branch>-NNN"), naming.index("fast/<project>/"), "new names first, legacy after")

    def test_the_cap_line_follows_the_grouping_line(self):
        cap = self.one("`max_stack_prs`")
        at = self.region.index(cap)
        self.assertTrue(self.region[at - 1].startswith("Consecutive tasks, in stack order, are grouped into one layer"))
        self.assertEqual(at, len(self.region) - 1, "the cap line sits just above the lockfile line")
        self.assertIn("Tasks stay tiny for implementers; the layers are sized for the reviewer.", self.region)
        for word in ("~/.compose/config.json", "verify.json", "adjacent", "fold", "same kind first"):
            self.assertIn(word, cap)
        self.assertRegex(cap, r"\bdefault[^.;]*\b10\b")

    def test_only_the_cli_stack_row_names_the_cap(self):
        cli = read("docs/cli.md").splitlines()
        rows = [l for l in cli if "max_stack_prs" in l]
        self.assertEqual(len(rows), 1, rows)
        self.assertTrue(rows[0].startswith("| `stack` | Cuts passed task branches into review layers (`review_layer_lines`"))
        self.assertIn("`--submit` pushes and opens one draft PR per layer", rows[0])
        at = cli.index(rows[0])
        self.assertTrue(cli[at - 1].startswith("| `verify` | Runs the local pipeline."))
        self.assertEqual(cli[at + 1], "| `top` | Checks out the stack top for manual testing. `--detach` releases it |")


class PrTextDocs(unittest.TestCase):
    def setUp(self):
        # sections/4.md's Lockfiles line and its closing `Nothing is pushed.` lines, held by their untouched neighbours.
        self.lines = read("sections/4.md").splitlines()
        at = self.index("Lockfiles (`package-lock.json`, `bun.lock`, `yarn.lock`, `pnpm-lock.yaml`, `go.sum`, any `*.lock`) are not counted, in a layer or in a task's 350 lines; ")
        self.lockfiles = self.lines[at : self.index("The project branch is not a PR: its groundwork commits")]
        self.pushed = self.lines[self.index("The CLI keeps Linear's state table true on the full path") + 1 :]
        self.text = "\n".join(self.pushed)

    def index(self, start):
        found = [i for i, l in enumerate(self.lines) if l.startswith(start)]
        self.assertEqual(len(found), 1, start)
        return found[0]

    def test_the_size_stays_on_the_layer_line_out_of_the_pr_body(self):
        line = " ".join(self.lockfiles)
        self.assertIn("each `layer` line names them and their size", line)
        self.assertIn("never in the PR body", line)
        self.assertNotIn("## What changed", line)

    def test_each_pr_is_titled_from_its_commits(self):
        self.assertTrue(self.pushed[0].startswith("Nothing is pushed."), self.pushed[0])
        self.assertRegex(self.text, r"\btitles?\b[^.]*\bcommits\b")
        for word in ("subject", "`and N more tasks`", "`Groundwork for <feature title>`", "72 characters", "groundwork", "Jira", "`(i/n)`", "feature's title for a one-PR stack", "one whole story", "more than one PR"):
            self.assertIn(word, self.text)

    def test_the_body_has_four_sections_in_order_from_issues_and_results_with_no_model(self):
        at = [self.text.find(h) for h in ("## Why", "## What changed", "## How it was tested", "## Tickets")]
        self.assertNotIn(-1, at)
        self.assertEqual(at, sorted(at))
        self.assertRegex(self.text, r"task issues?\b[^.]*\bresults\b")
        self.assertRegex(self.text, r"\b(no|without( a| any)?|never( calls)?( a| any)?)\s+model\b")
        self.assertFalse([l for l in self.lines if "size and generated files into the PR body" in l])
        for said in ("one line per task", "test commits folded in", "`compose verify passed`", "no attempt or round counts"):
            self.assertIn(said, self.text)

    def test_the_team_lead_writes_each_layers_title_why_and_what_changed_after_verify_and_before_the_preview(self):
        self.assertRegex(self.text, r"After verify passes and before you show the product owner the preview, write each layer's PR text")
        for said in ("`[written: .compose/<slug>/pr/<name>.md]`", "`[generated: write ", "never applied", "`# <title>`", "a reviewer who has not read the tickets",
                     "not one per commit", "is refused on its `pr` line with the reason", "never restate commit subjects", "ticket ids", "layer or groundwork"):
            self.assertIn(said, self.text)
        example = self.text.split("```markdown\n", 1)[1].split("```", 1)[0].splitlines()
        self.assertEqual([l for l in example if l.startswith("#")], ["# Keep the toggle's state across page reloads", "## Why", "## What changed"])
        self.assertIn("write each layer's PR text and show the `compose stack` preview", read("sections/6.md"))

    def test_the_submit_check_and_push_rule_stay_and_house_rules_hold(self):
        for kept in ("`gh stack submit --auto`", "`submit PR #N on <base>`", "`NO PR for <branch>`"):
            self.assertIn(kept, self.text)
        self.assertIn("Run it only when the user has explicitly asked for that push.", self.pushed)
        for l in self.lockfiles + self.pushed:
            self.assertNotIn("—", l)
            self.assertNotRegex(l, r"[a-z)`]\. [A-Z`]", l)


class ConfigKeysDocs(unittest.TestCase):
    def setUp(self):
        self.text = read("docs/workspaces.md")

    def section(self, title):
        self.assertEqual(self.text.count("\n## " + title + "\n"), 1, title)
        return self.text.split("\n## " + title + "\n", 1)[1].split("\n## ", 1)[0]

    def lines(self, *words):
        # The new section's lines holding every word, joined; at least one must.
        found = [l for l in self.section("Branch names and stack size").splitlines() if all(w in l for w in words)]
        self.assertTrue(found, words)
        return "\n".join(found)

    def test_the_example_config_parses_with_both_keys_at_their_defaults(self):
        cfg = json.loads(self.section("Config").split("```json\n", 1)[1].split("```", 1)[0])
        self.assertEqual((cfg.get("branch_prefix"), cfg.get("max_stack_prs")), ("compose/", 10))
        for name, ws in cfg.get("workspaces", {}).items():
            self.assertFalse({"branch_prefix", "max_stack_prs"} & set(ws), name)

    def test_the_section_sits_right_after_parallel_and_right_before_linear_key(self):
        self.section("Branch names and stack size")
        headings = re.findall(r"(?m)^## (.+)$", self.text)
        at = headings.index("Branch names and stack size")
        self.assertEqual(headings[at - 1 : at + 2], ["Parallel", "Branch names and stack size", "Linear key"])

    def test_branch_prefix_default_empty_value_and_init_record(self):
        self.assertRegex(self.lines("`branch_prefix`", "default"), r"default[^.;]*`compose/`")
        self.assertRegex(self.lines("slug"), r"empty|`\"\"`")
        self.assertRegex(self.lines("`init`", "verify.json", "`branch`"), r"\bonce\b")

    def test_the_three_branch_shapes(self):
        shapes = self.lines("-tests-NNN`", "-layer-NN`")
        self.assertRegex(shapes, r"(?<!tests)-NNN`")

    def test_max_stack_prs_default_override_and_fold(self):
        self.assertRegex(self.lines("`max_stack_prs`", "default"), r"default[^.;]*\b10\b")
        self.assertRegex(self.lines("verify.json"), r"overrid")
        self.assertRegex(self.lines("fold"), r"adjacent")

    def test_both_keys_can_be_set_per_workspace(self):
        self.assertRegex(self.lines("workspace"), r"top.level[^.]*workspace")

    def test_one_sentence_per_line_and_house_rules(self):
        for l in self.section("Branch names and stack size").splitlines():
            self.assertNotRegex(l, r"[a-z)`]\. [A-Z`]", l)
        self.assertNotIn("\u2014", self.text)
        self.assertNotRegex(self.text, r"\bgraft\b")


class ReadyDocs(unittest.TestCase):
    TASKS = ["sync", "linear <verb>", "tasks", "run", "done", "triage", "resume", "reflect", "hold", "change start\\|done\\|undo", "spec-check", "ready", "bench"]

    def tasks_rows(self):
        sec = read("docs/cli.md").split("### Tasks\n", 1)[1].split("### Verify and stack", 1)[0]
        return [l for l in sec.splitlines() if l.startswith("| `")]

    def skill_0i(self):
        text = read("SKILL.md")
        body = text[text.index("### 0i. The levels: project, epic, feature, story, task") :].split("\n### ", 1)[0]
        return [l for l in body.splitlines()[1:] if not l.startswith("|")]

    def test_ready_row_follows_spec_check_and_the_other_rows_stay(self):
        rows = self.tasks_rows()
        self.assertEqual([r.split("`")[1] for r in rows], self.TASKS)
        self.assertEqual(len([l for l in read("docs/cli.md").splitlines() if l.startswith("| `ready`")]), 1)

    def test_ready_row_states_the_rule_and_its_outputs(self):
        rows = [r for r in self.tasks_rows() if r.startswith("| `ready`")]
        self.assertEqual(len(rows), 1, "one ready row in Tasks")
        row = rows[0]
        for word in ("`Ready`", "story", "feature", "epic", "Todo", "Backlog", "blocker", "Done", "Canceled", "Design", "In Review"):
            self.assertIn(word, row)
        for word in ("can start now:", "results/ready.json", "compose linear labels --create Ready"):
            self.assertIn(word, row)
        self.assertNotIn("\u2014", row)

    def test_skill_0i_labels_sentence_names_ready(self):
        lines = [l for l in self.skill_0i() if all(f"`{w}`" in l for w in ("Epic", "Story", "Task"))]
        self.assertEqual(len(lines), 1)
        self.assertIn("`Ready`", lines[0])
        self.assertIn("compose linear labels --create", lines[0])

    def test_skill_0i_says_what_ready_means_and_who_sets_it(self):
        lines = [l for l in self.skill_0i() if "`compose ready`" in l]
        self.assertEqual(len(lines), 1, "one sentence names compose ready in 0i")
        for word in ("`Ready`", "story", "feature", "can start now"):
            self.assertIn(word, lines[0])
        self.assertNotIn("`Epic`", lines[0])
        self.assertNotRegex(lines[0], r"[.!?] [A-Z`]", "one sentence per line")
        self.assertNotIn("\u2014", lines[0])


class ReadyCheckpoints(unittest.TestCase):
    def skill_0s(self, body=False):
        text = read("SKILL.md")
        sec = text[text.index("### 0s. Every level's state, kept true") :].split("\n### ", 1)[0]
        return sec if body else [l for l in sec.splitlines()[1:] if not l.startswith("|")]

    def row(self, cmd):
        rows = [l for l in read("docs/cli.md").splitlines() if l.startswith(f"| `{cmd}`")]
        self.assertEqual(len(rows), 1, f"one {cmd} row")
        return rows[0]

    def one_line(self, lines, pred, what):
        found = [l for l in lines if pred(l)]
        self.assertEqual(len(found), 1, what)
        self.assertNotRegex(found[0], r"[.!?] [A-Z`]", "one sentence per line")
        self.assertNotIn("\u2014", found[0])
        return found[0]

    def test_0s_tells_the_lead_and_designer_to_run_ready_at_each_checkpoint(self):
        line = self.one_line(self.skill_0s(), lambda l: "compose ready --project <slug>" in l, "one 0s sentence runs compose ready")
        for word in ("checkpoint", "team lead", "designer"):
            self.assertIn(word, line)

    def test_0s_says_which_commands_refresh_the_marks(self):
        line = self.one_line(self.skill_0s(), lambda l: "`Ready`" in l and "refresh" in l, "one 0s sentence on the CLI's refreshes")
        self.assertNotIn("compose ready --project", line)
        for word in (r"roll-?\s?ups?", r"\bsync\b", r"\brun\b", r"\bverify\b.*\bPASS\b", r"\bclean\b"):
            self.assertRegex(line, word)

    def test_0s_keeps_its_checkpoint_reconcile_and_the_sentences_stay_in_0s(self):
        lines = self.skill_0s()
        self.assertTrue(any(l.startswith("Checkpoints, each followed by a reconcile of the whole tree") for l in lines))
        outside = read("SKILL.md").replace(self.skill_0s(body=True), "")
        self.assertNotIn("compose ready --project <slug>", outside)

    def test_cli_ready_row_names_the_commands_that_refresh_too(self):
        row = self.row("ready")
        for word in ("sync", "run", "verify", "clean"):
            self.assertRegex(row, rf"`(compose )?{word}`")

    def test_cli_sync_and_clean_rows_name_ready_and_keep_what_they_said(self):
        tasks = read("docs/cli.md").split("### Tasks\n", 1)[1].split("### Verify and stack", 1)[0]
        projects = read("docs/cli.md").split("### Projects\n", 1)[1].split("### Tasks\n", 1)[0]
        for cmd, sec, kept in (("sync", tasks, "--stdin"), ("clean", projects, "--delete-unmerged")):
            row = self.row(cmd)
            self.assertIn(row, sec)
            self.assertRegex(row, r"\bReady\b")
            self.assertIn(kept, row)
            self.assertNotIn("\u2014", row)


class TellWhatCanStart(unittest.TestCase):
    CAN_START = "can start now: NEB-x <title>, ..."

    def one_sentence(self, line):
        self.assertIn("event ready=", line)
        self.assertIn(self.CAN_START, line)
        self.assertIn("product owner", line)
        self.assertNotRegex(line, r"[.!?] [A-Z`]", "one sentence per line")
        self.assertNotIn("\u2014", line)

    def test_manager_tells_the_product_owner_unprompted_in_one_line(self):
        lines = read("sections/0h.md").splitlines()
        start = next(i for i, l in enumerate(lines) if l.startswith("The engineering manager supervises"))
        end = next(i for i in range(start, len(lines)) if not lines[i].strip())
        para = lines[start:end]
        found = [l for l in para if "event ready=" in l]
        self.assertEqual(len(found), 1, "one sentence on event ready= in the supervises paragraph")
        self.assertEqual([l for l in lines if "event ready=" in l], found, "and nowhere else in 0h")
        line = found[0]
        self.one_sentence(line)
        self.assertIn("event ready=<ids>", line)
        self.assertIn("unprompted", line)
        self.assertIn("one line", line)
        self.assertRegex(line, r"\b(no|not|never|without)\b[^.]*desktop notification")
        self.assertTrue(para[0].startswith("The engineering manager supervises, it does not only relay."))
        self.assertTrue(any(l.startswith("On a stall, read the team lead's pane") for l in para))

    def test_designer_starter_passes_ready_on_the_same_way(self):
        lines = read("sections/0d.md").splitlines()
        i = next(i for i, l in enumerate(lines) if l.startswith("The starter only relays"))
        self.assertIn("compose watch --project <slug> --from designer", lines[i])
        self.assertNotIn("event ready=", lines[i])
        line = lines[i + 1]
        self.one_sentence(line)
        self.assertIn("starter", line)
        self.assertIn("same way", line)
        self.assertEqual([l for l in lines if "event ready=" in l], [line], "one sentence in 0d")
        self.assertTrue(lines[i + 2].startswith("It is never inline"))


class ReadyEventDocs(unittest.TestCase):
    PROJECTS = ["setup", "update", "doctor", "init", "projects", "status", "clean", "trail"]

    def rows(self, start, end):
        sec = read("docs/cli.md").split(start + "\n", 1)[1].split(end, 1)[0]
        return [l for l in sec.splitlines() if l.startswith("| `")]

    def row(self, rows, cmd):
        found = [l for l in rows if l.startswith(f"| `{cmd}`")]
        self.assertEqual(len(found), 1, f"one {cmd} row in its section")
        self.assertEqual(len([l for l in read("docs/cli.md").splitlines() if l.startswith(f"| `{cmd}`")]), 1)
        self.assertNotIn("\u2014", found[0])
        return found[0]

    def projects_rows(self):
        return self.rows("### Projects", "### Tasks")

    def test_watch_row_names_the_ready_event_and_only_new_issues(self):
        row = self.row(self.rows("### Teammates and supervision", "### Workspaces"), "watch")
        self.assertIn("event ready=<ids>", row)
        self.assertRegex(row, r"\bonly\b[^|]*\bjust became ready\b")
        for kept in ("Blocks until something happens", "--now"):
            self.assertIn(kept, row)

    def test_status_row_shows_the_can_start_now_line_from_the_ready_list(self):
        row = self.row(self.projects_rows(), "status")
        self.assertIn("can start now:", row)
        self.assertIn("results/ready.json", row)
        self.assertIn("--watch", row)

    def test_projects_row_ends_each_line_with_can_start_now(self):
        row = self.row(self.projects_rows(), "projects")
        self.assertRegex(row, r"\bend(s|ing)? with\b[^|]*can start now:")
        self.assertIn("done/total", row)

    def test_only_existing_rows_change(self):
        self.assertEqual([r.split("`")[1] for r in self.projects_rows()], self.PROJECTS)
        sup = self.rows("### Teammates and supervision", "### Workspaces")
        self.assertFalse([r for r in sup if "ready" in r.split("|")[1]], "no new ready row in supervision")


class LinkFeatures(unittest.TestCase):
    EPIC = "- Epic: one planner per feature, in parallel."
    LINK = "Link a feature blocked by another feature only when it needs that feature's code."

    def bullet(self):
        lines = read("sections/0a.md").splitlines()
        i = next(i for i, l in enumerate(lines) if l.startswith("- A project made with `init --after <other-slug>`"))
        end = next(j for j in range(i + 1, len(lines)) if not lines[j].startswith("  "))
        return lines, lines[i:end]

    def one(self, lines, bullet, *words):
        found = [l for l in bullet if all(w in l for w in words)]
        self.assertEqual(len(found), 1, f"one line in the --after bullet with {words}")
        self.assertEqual([l for l in lines if all(w in l for w in words)], found, "and nowhere else in 0a")
        self.assertNotRegex(found[0], r"[.!?] [A-Z`]", "one sentence per line")
        return found[0]

    def test_after_bullet_says_sync_links_the_features(self):
        lines, bullet = self.bullet()
        line = self.one(lines, bullet, "`sync`", "blocked by")
        self.assertRegex(line, r"`sync` links\b")
        self.assertEqual(line.count("feature issue"), 2)
        self.assertIn("that project's feature issue", line)

    def test_after_bullet_links_only_on_a_code_need(self):
        lines, bullet = self.bullet()
        line = self.one(lines, bullet, "only when", "needs that feature's code")
        self.assertIn("blocked by", line)
        for verb in ("calls", "imports", "edits"):
            self.assertIn(verb, line)
        self.assertIn("what that feature builds", line)
        self.assertNotIn("`sync`", line)

    def test_after_bullet_keeps_its_lines(self):
        _, bullet = self.bullet()
        self.assertIn("records it as `review_base` in its `verify.json`", bullet[0])
        for kept in ("Its layers stack on that project's branch", "`clean` counts a merge into either."):
            self.assertTrue(any(kept in l for l in bullet[1:]), kept)
        self.assertFalse([l for l in bullet if "\u2014" in l])

    def test_planner_epic_line_ends_with_the_link_rule(self):
        brief = read("bin/fc_briefs.py").split('PLANNER_BRIEF = """', 1)[1].split('"""', 1)[0]
        lines = [l.strip() for l in brief.splitlines()]
        epic = [i for i, l in enumerate(lines) if l.startswith(self.EPIC)]
        self.assertEqual(len(epic), 1)
        line = lines[epic[0]]
        self.assertTrue(line.endswith(" " + self.LINK), line)
        self.assertIn("Fog (its features cannot be named yet) is wayfinder's: hand it to 0b and stop.", line)
        self.assertEqual(brief.count(self.LINK), 1)
        self.assertTrue(lines[epic[0] + 1].startswith("- Feature: "))


class DesignWaitsDocs(unittest.TestCase):
    DESIGNER = "The designer syncs (step 2), then starts every builder at once"

    def test_designcrews_row_starts_only_unblocked_tasks_and_prints_the_rest(self):
        cli = read("docs/cli.md")
        sec = cli.split("### Teammates and supervision\n", 1)[1].split("### Workspaces", 1)[0]
        rows = [l for l in sec.splitlines() if l.startswith("| `designcrews`")]
        self.assertEqual(len(rows), 1, "one designcrews row in Teammates and supervision")
        self.assertEqual(len([l for l in cli.splitlines() if l.startswith("| `designcrews`")]), 1)
        row = rows[0]
        self.assertRegex(row, r"\bonly\b[^|]*\bblock(ers?|ed by)\b[^|]*In Review or Done")
        self.assertIn("<id> waits on <ids>", row)
        self.assertEqual(row.count("waits on"), 1)
        for kept in ("design-NNN", "--only", "--max N", "--print", "design_concurrency"):
            self.assertIn(kept, row)
        self.assertNotIn("—", row)
        self.assertEqual(row.count(" | "), 1, "still two cells")

    def test_0d_says_a_design_task_waits_right_after_the_designer_line(self):
        lines = read("sections/0d.md").splitlines()
        i = next(i for i, l in enumerate(lines) if l.startswith(self.DESIGNER))
        self.assertIn("compose designcrews --project <slug>", lines[i])
        self.assertNotIn("In Review or Done", lines[i])
        line = lines[i + 1]
        for word in ("design task", "every task", "blocked by", "In Review or Done"):
            self.assertIn(word, line)
        self.assertRegex(line, r"\bwaits? until\b")
        self.assertNotRegex(line, r"[.!?] [A-Z`]", "one sentence per line")
        self.assertTrue(line.endswith("."))
        self.assertNotIn("—", line)
        self.assertEqual([l for l in lines if "In Review or Done" in l], [line], "one such sentence in 0d")
        self.assertTrue(lines[i + 2].startswith("`--only` picks tasks"))


SETUP_STEPS = [
    "2. Answer `compose setup`.",
    "   On a terminal it asks one question at a time: Quick start or Custom, a yes or no for each missing step under Custom, then each key with hidden input.",
    "   With `--yes`, or when there is no terminal, it runs the same steps with every default, never prompts, and ends by listing what is still missing.",
    "   It installs the tools `compose` needs, links the CLI and the skill, and saves your keys in `~/.compose/auth.json` (mode 600).",
    "   It sets up herdr with the notification settings `compose` needs, declares pi's OpenRouter provider, writes the default model choices, and ends with a model probe.",
]
SETUP_ROW = "| `compose setup [--yes]` | Installs and configures everything `compose` needs, one question at a time on a terminal; `--yes`, or no terminal, takes every default |"
DEVELOPMENT = [
    "## Development",
    "",
    "Run the CLI tests with `python3 -m unittest discover -s tests`.",
    "Type-check the CLI with `npx -y pyright@1.1.414 --pythonpath /usr/bin/python3` (strict; the error count is reported, nothing is gated on it).",
    "Run the jev tests with `cd jev && uv run pytest`, and the bp tests with `cd bp && npm test`.",
    "The CLI core is stdlib; `jev/` is a uv project, and `bp/` is one Node file with no dependencies.",
    "",
    "## Credits",
]
CLI_HEAD = "| `setup` | Installs and configures everything `compose` needs ([new-machine.md](new-machine.md)). On a terminal it asks one question at a time (Quick start or Custom, a yes or no per missing step under Custom, each key with hidden input); `--yes`, or no terminal, runs the same steps with every default and never prompts."
CLI_TAIL = " It exits 1 when Claude Code is missing. Without `--yes` it also exits 1 when a required key is missing or the model probe fails. With `--yes` it exits 0 and ends with `compose is installed but not ready:` when a required step is missing |"


class SetupDocs(unittest.TestCase):
    def assertBlock(self, lines, block):
        starts = [i for i, l in enumerate(lines) if l == block[0]]
        self.assertEqual(len(starts), 1, f"one line {block[0]!r}")
        self.assertEqual(lines[starts[0]:starts[0] + len(block)], block)

    def test_readme_setup_steps_in_place(self):
        self.assertBlock(read("README.md").splitlines(), SETUP_STEPS)

    def test_readme_setup_row_in_place(self):
        lines = read("README.md").splitlines()
        self.assertBlock(lines, ["| Command | What it does |", "|---|---|", SETUP_ROW])
        self.assertEqual([l for l in lines if l.startswith("| `compose setup [--yes]`")], [SETUP_ROW])
        self.assertIn("| `compose update` | Pulls this checkout (`--ff-only`), relinks what `compose` owns, and runs `doctor` |", lines)

    def test_readme_development_drops_the_setup_app(self):
        self.assertBlock(read("README.md").splitlines(), DEVELOPMENT)

    def test_cli_setup_row_keeps_the_rest(self):
        rows = [l for l in read("docs/cli.md").splitlines() if l.startswith("| `setup` |")]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].startswith(CLI_HEAD), rows[0])
        self.assertTrue(rows[0].endswith(CLI_TAIL), rows[0])

    def test_old_words_are_gone(self):
        for rel in ("README.md", "docs/cli.md"):
            for word in ("Textual", "guided", "plain path", "setup/tests"):
                self.assertNotIn(word, read(rel), f"{word!r} in {rel}")


MACHINE = {
    17: "",
    18: "On a terminal, `compose setup` asks one question at a time: Quick start takes every default, Custom asks a yes or no for each missing step.",
    19: "With `--yes`, or without a terminal, it runs the same steps with every default and never prompts.",
    20: "A key you did not enter is skipped, and the ending lists it with the command that sets it later.",
    45: "",
    46: "With `--yes`, setup ends with `compose is ready`, or with `compose is installed but not ready:` and one line per missing required step.",
    47: "Then it tells you the next move: `compose` outside herdr, or `claude` in a pane and `/compose` inside it.",
    50: "",
    51: "A machine without a herdr config gets the config the maintainer uses, from `bin/herdr.toml` in the checkout.",
    52: "A machine with one keeps all of it, and setup sets only the two lines `compose` needs, so the only desktop alert is the one `compose` sends itself:",
}
REQUIREMENTS = {
    105: "| `~/.pi/agent/` | pi's `models.json` (setup declares `openrouter-fast`), its own `auth.json`, and the herdr extension |",
    106: "| `~/.config/herdr/config.toml` | herdr's config: copied from `bin/herdr.toml` when absent, else only the two notification lines are set |",
    107: "",
}


class MachineDocs(unittest.TestCase):
    def assertLines(self, rel, want, count):
        lines = read(rel).splitlines()
        self.assertEqual(len(lines), count, f"{rel} keeps its {count} lines: edits replace lines, never add or drop")
        for n, line in want.items():
            self.assertEqual(lines[n - 1], line, f"{rel}:{n}")

    def test_new_machine_lines_in_place(self):
        self.assertLines("docs/new-machine.md", MACHINE, 101)

    def test_requirements_line_in_place(self):
        self.assertLines("docs/requirements.md", REQUIREMENTS, 138)

    def test_old_words_are_gone(self):
        for rel in ("docs/new-machine.md", "docs/requirements.md"):
            for word in ("guided", "plain path", "setup/herdr.toml"):
                self.assertFalse(word in read(rel), f"{word!r} in {rel}")

    def test_each_new_line_once(self):
        text = read("docs/new-machine.md")
        for n in (18, 19, 46, 51):
            self.assertEqual(text.count(MACHINE[n]), 1, MACHINE[n])
        self.assertEqual(read("docs/requirements.md").count("bin/herdr.toml"), 1)


DRY_ROW = "| `compose setup --dry-run` | Walks the same setup and changes nothing: every install, write, and key save prints as a `would` line, and the last line counts them |"
DRY_SENTENCE = " With `--dry-run` it asks the same questions and runs the same checks but changes nothing on the machine, prints each change as a `would` line, and ends with `dry run: nothing changed; N changes listed above`."
UPDATE_ROW = "| `compose update` | Pulls this checkout (`--ff-only`), relinks what `compose` owns, and runs `doctor` |"


class DryRunDocs(unittest.TestCase):
    def test_readme_row_right_after_the_setup_row(self):
        lines = read("README.md").splitlines()
        self.assertEqual(lines.count(SETUP_ROW), 1)
        i = lines.index(SETUP_ROW)
        self.assertEqual(lines[i:i + 3], [SETUP_ROW, DRY_ROW, UPDATE_ROW])

    def test_cli_sentence_right_after_the_defaults_sentence(self):
        rows = [l for l in read("docs/cli.md").splitlines() if l.startswith("| `setup` |")]
        self.assertEqual(rows, [CLI_HEAD + DRY_SENTENCE + CLI_TAIL])

    def test_each_file_names_the_flag_once(self):
        self.assertEqual(read("README.md").count("--dry-run"), 1)
        self.assertEqual(sum(l.count("--dry-run") for l in read("docs/cli.md").splitlines() if l.startswith("| `setup` |")), 1)  # `clean --abandon` has its own


FEATURE_HEAD = "- **feature**: if its map is not clear, wayfinder it (step 0b). When it has no stories, the planner teammate proposes them as a `needs-user` list "
FEATURE_TAIL = " and creates them on the product owner's go; then it writes the plan (step 1) and splits (step 2) under each story."
LEAN_PAREN = "(one issue per story, each the thinnest slice that works end to end and unblocks the next, at most 5 criteria, in the order they should ship)"
PLANNING_MISS = "A second wave for polish or a toolchain fix the first wave could have seen is a planning miss."
LEAN_LINES = [
    "Stories are lean: each is the thinnest slice that works end to end and unblocks the next story, with at most 5 criteria.",
    'Split cues in a story: "all", "every", several When/Then pairs, or several outside systems.',
    "When no split fits, a time-boxed probe answers the unknown first, then the split.",
]


class LeanStoryRule(unittest.TestCase):
    def test_feature_row_holds_the_lean_parenthesis_and_nothing_else_changes(self):
        rows = [l for l in read("SKILL.md").splitlines() if l.startswith("- **feature**:")]
        self.assertEqual(rows, [FEATURE_HEAD + LEAN_PAREN + FEATURE_TAIL])
        self.assertNotIn("one issue per user-visible slice", rows[0])

    def test_story_row_of_the_table_keeps_its_slice_wording(self):
        rows = [l for l in read("SKILL.md").splitlines() if l.startswith("| **story** |")]
        self.assertEqual(len(rows), 1)
        self.assertIn("its description is one user-visible slice with acceptance criteria", rows[0])

    def test_three_lines_right_after_the_planning_miss_line_once_each(self):
        lines = read("sections/1.md").splitlines()
        self.assertEqual(lines.count(PLANNING_MISS), 1)
        i = lines.index(PLANNING_MISS)
        self.assertEqual(lines[i + 1:i + 4], LEAN_LINES)
        self.assertTrue(lines[i + 4].startswith("The plan also states the simplicity bar"), "the three lines are added, not swapped in")
        for line in LEAN_LINES:
            self.assertEqual(lines.count(line), 1, line)

    def test_skill_stays_under_the_size_cap(self):
        self.assertLess(len(read("SKILL.md").encode()), 30000)

    def test_no_outside_source_named_in_the_skill(self):
        for path in [ROOT / "SKILL.md"] + sorted((ROOT / "sections").glob("*.md")):
            for word in ("Product-Manager-Skills", "deanpeters"):
                self.assertNotIn(word, path.read_text(), f"{word!r} in {path.name}")


class LeanDesignStories(unittest.TestCase):
    LEAN = "Design stories are lean: one flow's lowfi or one screen's hifi each, cut just ahead of the code story it unblocks, walking skeleton flow first, lowfi then hifi inside each flow."
    OLD = "| **epic** | Check for a design system (below). None: write the design-system epic with its features and stories, send its open decisions up as cards, build Foundations once they are answered. One exists: continue at the first story not Done under it or under the epic's features."

    def epic_row(self):
        lines = read("sections/0d.md").splitlines()
        rows = [i for i, l in enumerate(lines) if l.startswith("| **epic** |")]
        self.assertEqual(len(rows), 1, "one epic row in 0d")
        return lines, rows[0]

    def test_epic_row_ends_its_last_cell_with_the_lean_sentence(self):
        lines, i = self.epic_row()
        row = lines[i]
        self.assertTrue(row.endswith(self.LEAN + " |"), row)
        self.assertTrue(row.startswith(self.OLD), "the cell keeps its old text before the new sentence")
        self.assertRegex(row[len(self.OLD):-len(self.LEAN) - 2], r"^ +$")

    def test_row_stays_one_line_with_two_cells(self):
        lines, i = self.epic_row()
        row = lines[i]
        self.assertEqual(row.count("|"), 3)
        self.assertEqual(row.count(" | "), 1)
        self.assertEqual(lines[i - 1], "|---|---|")
        self.assertTrue(lines[i + 1].startswith("| **feature** |"))
        self.assertNotIn("—", row)

    def test_sentence_appears_once_in_0d(self):
        text = read("sections/0d.md")
        self.assertEqual(text.count(self.LEAN), 1)
        self.assertEqual(text.count("Design stories are lean"), 1)


PLAN_LINES = [
    "**The delivery plan.**",
    "The planner rewrites its judgment sections (Outside waits, How this maps to compose, Priority when something has to give) at each re-plan, with `compose linear doc update <id> --section \"<heading>\" --file <path>`.",
    "Priority is the ranked list under Priority when something has to give; Linear's priority field stays unused.",
    "The team lead and the engineering manager never edit the delivery plan by hand: the CLI rewrites its data sections and the planner its judgment sections.",
]
REPLAN = [
    "**Re-plan.**",
    "1. If no change is open: sync, then `compose change start --why \"<one line>\"`.",
    "2. The planner teammate edits Linear: `## Plan`; it cancels the tasks that rest on the old line (a canceled task loses its `compose` block), edits the briefs that change, and adds new tasks with the next ids, and `compose testcrews --only <new and changed ids> --redo` for their tests: `--redo` rewrites the test of a passed task whose brief changed.",
    "3. The 3b gate applies unchanged: a list that matches what the product owner just settled dispatches at once, and anything past it goes back up.",
    "4. Sync, then `compose change done`: it comments the change on the feature.",
    "5. `compose hold --release <ids>`, then `compose run --only <new and redone ids> --redo` for the layers built on the old line.",
]


class PlanOwnership(unittest.TestCase):
    def setUp(self):
        self.lines = read("sections/8.md").splitlines()

    def test_four_lines_and_a_blank_right_before_undo(self):
        i = self.lines.index("**Undo and update.**")
        self.assertEqual(self.lines[i - 5:i], PLAN_LINES + [""])

    def test_each_line_written_once(self):
        for line in PLAN_LINES:
            self.assertEqual(self.lines.count(line), 1, line)

    def test_replan_list_unchanged_and_nothing_else_between(self):
        self.assertEqual(self.lines.count(REPLAN[0]), 1)
        i = self.lines.index(REPLAN[0])
        self.assertEqual(self.lines[i:i + 6], REPLAN)
        self.assertEqual(self.lines.count(PLAN_LINES[0]), 1, "no delivery plan block")
        j = self.lines.index(PLAN_LINES[0])
        self.assertGreater(j, i + 5)
        self.assertEqual([l for l in self.lines[i + 6:j] if l.strip()], [])

    def test_house_rules(self):
        self.assertNotIn("\u2014", read("sections/8.md"))
        for line in PLAN_LINES:
            self.assertNotRegex(line, r"[.!?] [A-Z]")


class ManagerProseNamesPostures(unittest.TestCase):
    AWAY = "**Away: the product owner is away** (`/compose:away [--push] [words]`, `compose away`; modeled on firstmate's away mode)."
    BIAS = "Bias toward exit: when unsure whether a message is the return, it is."
    YOLO = [
        "**Yolo: the engineering manager answers until an explicit off** (`/compose:yolo [--push] [words]`, `compose yolo`).",
        "Yolo follows every Away rule above, with the `yolo:` prefix, the `(yolo recommendation, unconfirmed, <date>)` tag, and `compose yolo` in place of `compose away`; only the exit differs.",
        "Only an explicit off ends it: the message `yolo:off` (or `yolo off`), `/compose:yolo off`, or `compose yolo off --project <slug>`; then run `compose yolo off --project <slug>` (every project of an epic), relay the digest, and ask its \"To confirm\" decisions in one ask.",
        "Every other message is a steer: act on it at once (a change of plans goes to the team lead; an answer to a card goes to the teammate as the product owner's, and the wayfinder rewrites a tagged line as theirs), reply with what changed, and yolo stays on; \"To confirm\" waits for the off.",
        "`compose away digest --project <slug>` or `compose yolo digest --project <slug>` prints the digest and leaves the posture on.",
    ]
    NEVER = [
        "The never-set still stops and lands in \"Waiting on you\": destructive, irreversible, and security-sensitive actions are never pre-authorizable whatever the words say.",
        "That covers anything that costs money beyond the configured models (a model or provider switch, keys), the payment halt, merging a toolsmith fix into compose itself, force-push, `clean --delete-unmerged`, `clean --abandon`, `crew stop --force`, attended prompts (Frame0 Allow, sign-ins), and anything the product owner's CLAUDE.md forbids.",
    ]

    def setUp(self):
        self.lines = read("sections/0h.md").splitlines()

    def test_away_paragraph_is_the_old_paragraph_for_away(self):
        self.assertEqual(self.lines.count(self.AWAY), 1)
        self.assertEqual(self.lines.count(self.BIAS), 1)
        start, end = self.lines.index(self.AWAY), self.lines.index(self.YOLO[0])
        self.assertLess(self.lines.index(self.BIAS), end)
        away = "\n".join(self.lines[start:end])
        for want in ["compose away off --project <slug>", "away: <card ids>: accept-all",
                     "(away recommendation, unconfirmed, <date>)", "compose away decided --project <slug>"]:
            self.assertIn(want, away)
        for gone in ["compose yolo", "yolo:", "/compose:yolo", "(yolo recommendation"]:
            self.assertNotIn(gone, away)

    def test_yolo_paragraph_follows_the_away_paragraph_line_by_line(self):
        i = self.lines.index(self.YOLO[0])
        self.assertEqual(self.lines[i:i + 5], self.YOLO)
        self.assertEqual(self.lines.count(self.YOLO[0]), 1)
        self.assertGreater(i, self.lines.index(self.BIAS))
        self.assertEqual(self.lines[i - 1], "")
        self.assertEqual(self.lines[i - 2], self.BIAS)

    def test_never_set_lines_and_no_em_dash(self):
        for line in self.NEVER:
            self.assertEqual(self.lines.count(line), 1)
        self.assertNotIn("—", "\n".join(self.lines))


class SlashCommandsNamePostures(unittest.TestCase):
    HINT = 'argument-hint: "[--push] [words] | --clear-words | digest | off"'
    DESC = {"away": "description: Go away - the engineering manager answers with the recommendation and logs it; your first message ends it",
            "yolo": "description: Yolo - the engineering manager answers with the recommendation and logs it until you say yolo:off; you can still steer"}
    LAST = {"away": "Then continue under sections/0h.md's Away paragraph.",
            "yolo": "Then continue under sections/0h.md's Yolo paragraph."}

    def lines(self, p):
        return read(f"commands/{p}.md").splitlines()

    def test_frontmatter_and_last_line(self):
        for p in ("away", "yolo"):
            with self.subTest(p):
                lines = self.lines(p)
                self.assertEqual(lines[:5], ["---", self.DESC[p], self.HINT, f"allowed-tools: Bash(compose {p}:*)", "---"])
                self.assertEqual(lines[-1], self.LAST[p])

    def test_off_digest_and_otherwise_lines_in_order(self):
        for p in ("away", "yolo"):
            with self.subTest(p):
                lines = self.lines(p)
                off = [i for i, l in enumerate(lines) if l.startswith("If `$ARGUMENTS` is `off`, run ")]
                digest = f"If `$ARGUMENTS` is `digest`, run `compose {p} digest --project <slug> < /dev/null` for each project and show each digest as is; {p} stays on."
                other = f"Otherwise run `compose {p} --project <slug> $ARGUMENTS < /dev/null` for each project and show the announcement as is."
                self.assertEqual(len(off), 1)
                self.assertIn(f"`compose {p} off --project <slug> < /dev/null`", lines[off[0]])
                self.assertEqual(lines.count(digest), 1)
                self.assertEqual(lines.count(other), 1)
                self.assertLess(off[0], lines.index(digest))
                self.assertLess(lines.index(digest), lines.index(other))

    def test_keeps_project_and_words_lines(self):
        for p in ("away", "yolo"):
            with self.subTest(p):
                lines = self.lines(p)
                self.assertIn("The project is the one this session runs; for an epic, every project of the epic.", lines)
                self.assertIn("Do not reword, summarize, or widen the words: they pre-answer a question verbatim, never by analogy.", lines)

    def test_away_never_names_yolo_and_no_em_dash(self):
        self.assertNotIn("compose yolo", read("commands/away.md"))
        for p in ("away", "yolo"):
            self.assertNotIn("—", read(f"commands/{p}.md"))


if __name__ == "__main__":
    unittest.main()
