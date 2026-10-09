---
description: List fast-coding workspaces, switch (`personal`), or manage them (`add <name>`, `key <name>`, `remove <name>`)
argument-hint: "[name | add <name> | key <name> | remove <name>]"
allowed-tools: Bash(fast-coding workspace:*)
---
Run `fast-coding workspace $ARGUMENTS < /dev/null` and show its output as is.

Never ask for, accept, or print an API key in chat.
After `add`, or when a workspace's key is "not set", tell the user to copy the OpenRouter key and type this themselves:
`! pbpaste | fast-coding workspace key <name>`
Remind them that OpenRouter presets are per account, so a new workspace's account needs the presets its models name (`gpt-oss-120b-cerebras`, `glm-5.3-flash-fast`).
