import re
import unittest
from pathlib import Path

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
        figma = self.row(sec, "figma check\\|tree\\|judge")
        for word in ("check --figma", "tree --only", "Framelink", "judge --only", "linear.json", "results/NNN.tree.txt", "MET", "NOT_MET", "UNCLEAR"):
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
        for command in ("compose toolsmith --project <slug> | compose crew start --project <slug> --role toolsmith --cwd <cli_repo> --brief -",
                        "compose tool-bug file --project <slug> --body", "--approved", "gh issue close <n> --comment"):
            self.assertIn(command, block)
        self.assertIn("never edits or commits", block)
        self.assertIn("no `Fixes #n`", block)

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
        f"Then read the writing-plans skill file (the newest of {LS}) for how to write the plan, but not where: the plan is a `## Plan` section in the feature issue's description (`save_issue`), never a file.",
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


class LinearFields(unittest.TestCase):
    SENTENCE = "Every `list_issues` call passes `fields` (`id`, `title`, `status`, and more only when the body is needed): the default reply carries whole descriptions and costs about ten times the tokens."
    LEAD = "You create and edit issues and write judgment comments through the Linear MCP tools"

    def test_sentence_once_in_section_0_right_after_the_mcp_line(self):
        text = read("SKILL.md")
        self.assertEqual(text.count(self.SENTENCE), 1)
        section = text.split("\n### 0. ", 1)[1].split("\n### 0i. ", 1)[0]
        lines = section.splitlines()
        self.assertIn(self.SENTENCE, lines, "the sentence is its own line inside section 0")
        lead = [i for i, l in enumerate(lines) if l.startswith(self.LEAD)]
        self.assertEqual(len(lead), 1)
        self.assertEqual(lines[lead[0] + 1], self.SENTENCE)
        self.assertIn("`list_issues`", lines[lead[0]], "the MCP tools line itself is unchanged")

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
        hits = [i for i, l in enumerate(self.lines) if "save_issue" in l]
        self.assertEqual(len(hits), 1, "one save_issue sentence")
        line = self.lines[hits[0]]
        self.assertLessEqual(abs(hits[0] - self.report), 2, "near the reporting rule")
        for words in ("team lead drafts", "Decisions", "Plan", "one per section", "task issues", "whole issue"):
            self.assertIn(words, line)

    def test_new_lines_are_plain_and_the_older_sentences_stay(self):
        new = [l for l in self.lines if self.ONE_LINE in l or "save_issue" in l or "<card id>" in l]
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
        self.assertIn("visual cards open in Lavish: <file>", step)
        self.assertNotIn("the text cards in full", self.text)
        self.assertNotIn("with the text cards", self.text)

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
        self.assertRegex(rule, r"few `?save_issue`? patches")
        self.assertIn("one per section", rule)

    def test_task_detail_goes_on_task_issues_and_no_reread(self):
        rule = self.rule()
        self.assertIn("task issues", rule)
        self.assertRegex(rule, r"never re-?reads? an issue it just wrote")

    def test_reason_is_that_each_save_echoes_the_whole_issue(self):
        rule = self.rule()
        self.assertRegex(rule, r"echoes the whole issue")
        self.assertIn("355k", rule)

    def test_rule_is_stated_once_and_earlier_text_stays(self):
        text = read("sections/1.md")
        self.assertEqual(len(re.findall(r"(?i)echoes the whole issue", text)), 1)
        flat = " ".join(text.split())
        self.assertIn(" ".join(PlannerReadsWritingPlans.RUN[:3]), flat)
        self.assertIn(PlannerReadsWritingPlans.SKILLS_OFF, flat)

    def test_plain_dashes_and_one_sentence_per_line(self):
        text = read("sections/1.md")
        self.assertNotIn("\u2014", text)
        for line in text.splitlines()[1:]:
            if not line.startswith("|"):
                self.assertNotRegex(line, r"[.!?] [A-Z]", line)


if __name__ == "__main__":
    unittest.main()


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
        self.assertIn("(herdr, treehouse, trail, gh, gh stack, claude, npx, pi, bp, the `framelink-figma`", doctor[0])
        self.assertIn("pi, bp, treehouse, and trail only warn, and Framelink warns as `needed for the designer`", doctor[0])
        self.assertIn("| trail | `file:line` context packs for implementers | `npm i -g @trailhq/trail-code` |", reqs)
        self.assertIn("| `COMPOSE_NO_TRAIL=1` | skip trail |", reqs)
        # Only the tool word changes: the neighbouring env row stays, and the old graft env row is gone.
        self.assertIn("| `COMPOSE_NO_TREEHOUSE=1` | use plain git worktrees even with treehouse installed |", reqs)
        self.assertFalse([l for l in reqs if "COMPOSE_NO_GRAFT" in l], "COMPOSE_NO_GRAFT")

    def test_how_it_works_and_new_machine(self):
        self.skipTest("not written yet")
