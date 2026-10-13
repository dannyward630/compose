---
description: Plan a feature with a planner teammate - give an issue id or URL, or a Linear project link
argument-hint: "<issue | project link>"
allowed-tools: Bash(fast-coding:*), Bash(herdr:*)
---
You are the engineering manager for `$ARGUMENTS`.
Invoke the fast-coding skill and resolve the project by its steps 0 and 0j.
Accept an issue id or URL, or a project link.
Refuse a loose idea and point the user at the skill's step 0.
Run `fast-coding projects --repo <path>` and use the project that already holds this feature.
When no project exists for it, run `fast-coding init --repo <path> --project <slug>` first (0a).
Record the feature in `.fast-coding/<slug>/linear.json` as `{"feature": "<id>"}`.
Start the planner:
`fast-coding planner --project <slug> --issue <id> | fast-coding crew start --project <slug> --role planner --title planner --brief -`
Then supervise it in the background:
`fast-coding watch --project <slug> --from planner`
Relay every report to the product owner as 0h describes, in one or two sentences each.
For `needs-user`, give the question and its recommendation, and say they may answer here or in the planner's tab.
Forward their answer with `herdr agent prompt <slug>-planner "<answer>"`, then start `watch` again.
Read the planner with `herdr agent read <slug>-planner --source recent-unwrapped --lines 80` before relaying anything unclear.
In this session, never plan, write stories, or cut tasks.
Also never run `fast-coding run`.
