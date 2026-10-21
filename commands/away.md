---
description: Go away - the engineering manager answers with the recommendation and logs it; your first message ends it
argument-hint: "[--push] [words] | --clear-words | digest | off"
allowed-tools: Bash(compose away:*)
---
The project is the one this session runs; for an epic, every project of the epic.
If `$ARGUMENTS` is `off`, run `compose away off --project <slug> < /dev/null` for each project and show each digest as is, then ask its "To confirm" decisions in one message: accept all, or name the ones to change.
If `$ARGUMENTS` is `digest`, run `compose away digest --project <slug> < /dev/null` for each project and show each digest as is; away stays on.
Otherwise run `compose away --project <slug> $ARGUMENTS < /dev/null` for each project and show the announcement as is.
Do not reword, summarize, or widen the words: they pre-answer a question verbatim, never by analogy.
Then continue under sections/0h.md's Away paragraph.
