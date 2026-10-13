---
description: "Start the designer teammate for a ticket: continues design work in Figma from where it stopped"
argument-hint: "<Linear url or id> [--figma <file url or key>]"
allowed-tools: Bash(fast-coding designer:*)
---
The ticket and options are `$ARGUMENTS`.

1. Invoke the fast-coding skill as the engineering manager, and resolve the ticket's level and its feature (0, 0j).
2. Find the project for that feature with `fast-coding projects`, else create it with `fast-coding init --project <slug>`.
3. When `--figma` is given, run `fast-coding figma check --project <slug> --figma <file>`.
4. Start the designer in its own pane: `fast-coding designer --project <slug> | fast-coding crew start --project <slug> --role designer --title designer --brief -`.
5. Relay its reports with `fast-coding watch --project <slug> --from designer`, and forward the product owner's answers with `herdr agent prompt <slug>-designer "<answer>"`.

Never design in this session: no Figma write and no design issue here.
The designer and its crew do that work in their own panes (SKILL.md 0d).
