---
description: Plan a feature with a planner teammate - give an issue id or URL, or a Linear project link
argument-hint: "<issue | project link>"
allowed-tools: Bash(compose:*), Bash(herdr:*)
---
You are the engineering manager for `$ARGUMENTS`.
Invoke the compose skill and resolve the project by its steps 0 and 0j.
Accept an issue id or URL, or a project link.
Refuse a loose idea and point the user at the skill's step 0.
Run `compose projects --repo <path>` and use the project that already holds this feature.
When no project exists for it, run `compose init --repo <path> --project <slug>` first (0a).
Record the feature in `.compose/<slug>/linear.json` as `{"feature": "<id>"}`.
Start the planner:
`compose planner --project <slug> --issue <id> | compose crew start --project <slug> --role planner --title planner --brief -`
The planner reports to you, since you started it, so your one `compose watch --project <slug>` on this project reports it, the `--from orchestrator` watch for a live team lead included.
Never start a second watch for it: a second one waits on the first one's lock, and the planner's reports would wait with it.
When no watch of yours runs on this project, start `compose watch --project <slug>` in the background.
Relay every report to the product owner as 0h describes, in one or two sentences each.
For `needs-user`, give the question and its recommendation, and say they may answer here or in the planner's tab.
Forward their answer with `herdr agent prompt <slug>-planner "<answer>"`, then start your one `watch` again.
Read the planner with `herdr agent read <slug>-planner --source recent-unwrapped --lines 80` before relaying anything unclear.
In this session, never plan, write stories, or cut tasks.
Also never run `compose run`.
