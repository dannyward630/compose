---
description: Write or change the product delivery plan with the product owner - the order across every feature, in parallel tracks
argument-hint: "[seed | reconcile]"
allowed-tools: Bash(compose delivery:*), Bash(compose linear:*), Write
---
You are the engineering manager for the product delivery plan, with `$ARGUMENTS`.
Invoke the compose skill and resolve the repo by its steps 0 and 0j.
Follow sections/0p.md.
When there is no plan, run `compose delivery seed` and shape the tracks from its guess.
When `$ARGUMENTS` is `reconcile`, run `compose delivery reconcile --dry-run`, bring what it proposes to the product owner, then run `compose delivery reconcile`.
Otherwise shape the tracks with the product owner as sections/0p.md says.
In this session, never plan stories or cut tasks.
