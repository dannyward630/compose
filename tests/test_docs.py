import hashlib
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
        self.assertIn("```fast-coding\n", design)
        block = design.split("```fast-coding\n", 1)[1].split("```", 1)[0]
        self.assertRegex(block, r"(?m)^kind: design$")
        self.assertRegex(block, r"(?m)^nodes: .+/.+")
        self.assertRegex(block, r"(?m)^test: fast-coding figma judge --project \S+ --only (\d{3}|NNN)$")
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
            "fast-coding figma check --project <slug> --figma <url or key>",
            "fast-coding designer --project <slug> | fast-coding crew start --project <slug> --role designer --title designer --brief -",
            "fast-coding designcrews --project <slug>   # one design-NNN builder per open design task",
            "fast-coding crew start --project <slug> --role orchestrator --title orchestrator --brief - < brief.txt",
            "fast-coding crew list --project <slug>",
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
            "/fast-coding:designer <ticket>",
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
        self.assertEqual(meta["allowed-tools"], "Bash(fast-coding designer:*)")

    def test_numbered_steps_name_the_commands_in_order(self):
        _, _, body = self.parts()
        steps = [line for line in body.splitlines() if line[:1].isdigit()]
        self.assertEqual([s.split(".", 1)[0] for s in steps], ["1", "2", "3", "4", "5"])
        self.assertIn("fast-coding skill", steps[0])
        self.assertIn("0j", steps[0])
        self.assertIn("fast-coding projects", steps[1])
        self.assertIn("fast-coding init --project <slug>", steps[1])
        self.assertIn("--figma", steps[2])
        self.assertIn("fast-coding figma check --project <slug> --figma <file>", steps[2])
        pipe = "fast-coding designer --project <slug> | fast-coding crew start --project <slug> --role designer --title designer --brief -"
        self.assertLess(body.index("fast-coding figma check"), body.index(pipe))
        self.assertLess(body.index(pipe), body.index("fast-coding watch --project <slug> --from designer"))
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
        self.assertNotIn("invoke the fast-coding skill", self.text.lower())

    def test_toolsmith_brief_reads_only_skill_md(self):
        block = self.text.split("**When fast-coding itself fails**", 1)[1].split("The team lead reports at every point", 1)[0]
        lines = [l for l in block.splitlines() if "toolsmith" in l and "brief" in l and "SKILL.md" in l]
        self.assertTrue(lines, "a toolsmith brief line names SKILL.md")
        for line in lines:
            self.assertNotIn("sections/", line)
            self.assertNotIn("herdr/SKILL.md", line)
            self.assertNotRegex(line, r"invoke the `?fast-coding`? skill")

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
    OPT_IN = "Frame0 is off by default: a prototype question asks the team lead for a session started with `fast-coding crew start --frame0` (the wayfinder restarted that way, or a helper), and only that session has the `frame0` tools."
    ONLY = "Only a session started with `crew start --frame0` has the `frame0` tools, pointed at that app; draw from such a session, never from an older one."
    # sha256 of sections/0b.md at 21c79e5 without its old "`crew start` points every teammate's ..." line
    UNCHANGED = "219835e3389a20aa47291d679f0fef06f1c589693883d3fd0a0000a999b498d6"

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

    def test_rest_of_file_unchanged(self):
        rest = [l for l in self.lines if l not in (self.FIRST, self.OPT_IN, self.ONLY)]
        self.assertEqual(len(self.lines), 34)
        self.assertEqual(hashlib.sha256("\n".join(rest).encode()).hexdigest(), self.UNCHANGED)

    def test_plain_text_rules(self):
        self.assertNotIn("\u2014", self.text)
        # Older lines (e.g. 2-7 of the numbered steps, "`teardown` saves ...") already hold two sentences; the rule covers the new ones.
        for line in (self.FIRST, self.OPT_IN, self.ONLY):
            self.assertNotRegex(line, r"[.!?] [A-Z]", line)


if __name__ == "__main__":
    unittest.main()
