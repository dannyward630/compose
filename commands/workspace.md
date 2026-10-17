---
description: List compose workspaces, switch (`personal`), or manage them (`add <name>`, `key <name>`, `remove <name>`)
argument-hint: "[name | add <name> | key <name> | remove <name>]"
allowed-tools: Bash(compose workspace:*)
---
Run `compose workspace $ARGUMENTS < /dev/null` and show its output as is.

Never ask for, accept, or print an API key in chat.
This covers the OpenRouter key and the workspace's Linear API key alike.
After `add`, or when a workspace's key is "not set", tell the user to copy the OpenRouter key and type this themselves:
`! pbpaste | compose workspace key <name>`
Remind them that OpenRouter presets are per account, so a new workspace's account needs the presets its models name (`glm-5-3-flash-fast` by default).
For the CLI to keep Linear's states (full-path projects), each workspace needs its own Linear API key, from that workspace's Linear account (Settings, Security & access, Personal API keys). When the listing shows a workspace's linear key "not set", tell the user to copy it and type this themselves:
`! pbpaste | compose workspace key <name> --linear`
