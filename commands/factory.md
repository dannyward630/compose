---
description: Start the factory - it builds ready stories in delivery plan order at a day pace and offers planning when nothing is ready
argument-hint: "[stop [--hold <why>] | status | pace <n>]"
allowed-tools: Bash(compose:*), Bash(herdr:*)
---
Invoke the compose skill, resolve the repo by its steps 0 and 0j, and follow sections/0f.md.
When `$ARGUMENTS` is `stop`, `status`, or `pace <n>`, run `compose factory $ARGUMENTS` and show its output as is.
In this session, never write code, stories, or tasks yourself.
