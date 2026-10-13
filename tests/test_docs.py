import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
        figma = self.row(sec, "figma check\\|judge")
        for word in ("check --figma", "judge --only", "linear.json", "results/NNN.tree.txt", "MET", "NOT_MET", "UNCLEAR"):
            self.assertIn(word, figma)
        for cmd in ("crew start\\|list\\|focus\\|stop", "explore", "testcrews", "report", "watch", "teardown", "frame0 up", "guard", "rewake"):
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
        text = read("SKILL.md")
        self.assertTrue(start in text, f"SKILL.md has no {start!r}")
        body = text[text.index(start) :]
        return body[: body.find(end, len(start))]

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
            "one `get_screenshot` per story",
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
    pass


if __name__ == "__main__":
    unittest.main()
