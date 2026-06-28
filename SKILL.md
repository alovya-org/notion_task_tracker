---
name: notion_task_tracker
description: Work or create tracker tasks, read tracker task context, log tracker task progress, complete, cancel, or delete tracker tasks, capture miscellaneous notes, or create synthesis notes from the personal Notion task tree. Use when the user types notion_task read N, notion_task work N, notion_task log N [notes], notion_task complete N [notes], notion_task cancel N [notes], notion_task delete N, notion_task parent [pX] [title], notion_task child PARENT [pX] [title], notion_task sibling EXISTING [pX] [title], notion_task misc [title] NOTES, notion_task synth [title] SOURCES NOTES, asks to continue an existing tracker task, or asks to write task/misc/synthesis context to Notion.
---

# Notion Task

Use the installed `ntt` CLI for all tracker reads and writes. The README owns exact flags, JSON shapes, command schemas, and implementation details; this skill only captures agent judgment.

## Operating Principles

- Treat every user request as one explicit tracker action: read, work, log, complete, cancel, delete, parent, child split, sibling split, misc, synth, or update.
- Let the CLI own Notion writes, task metadata refresh, tracker-state persistence, landing-page repair, page mentions, and page-id capture.
- Do not manually send Notion writes unless the user is explicitly debugging the tracker itself.
- Use the default tracker state unless the user asks for a non-default path.
- Run live Notion commands outside the network-restricted sandbox with `NOTION_API_KEY` available.
- If auth, permission, page-id, or Notion content-replacement errors occur, stop and report the blocker. Do not guess around them.

## Context Quality

Logs should preserve the facts needed to resume work without rereading the chat.

- Prefer rich blocks for normal logs: paragraphs for conclusions and decisions, code blocks for commands, outputs, diffs, stack traces, paths, JSON/YAML, and structured observations.
- Include exact commands, files, errors, outputs, and test results when they matter.
- In paragraph text, wrap inline technical names such as file paths, commands, environment variables, functions, class names, field names, tickets, and literal values in backticks.
- Keep observation, inference, decision, and follow-up distinct.
- Avoid bland summaries such as "Discussed X" when the useful content is what happened, what changed, and why.
- Put detailed work on the most specific task page. Parent timeline entries created by child or sibling splits are bookkeeping links, not substitutes for the real log.

## Task Creation Judgment

- Use `parent` for new top-level work, never an implicit or generic "new" task.
- Use `child` when one source task should gain exactly one child task.
- Use `sibling` when one source task should gain exactly one peer.
- For split actions, dependency and dependant relations come from the source task. Use explicit relation-edit actions later only when the user asks for manual metadata changes.
- If a create action includes useful initial context, write that context as the new task's initial timeline entry rather than creating a bare task and logging afterward.

## Reading And Working

- For `read`, answer from the CLI summary plus fetched task context; treat it as read-only.
- For `work`, use the task page for intent, status, blockers, links, and recent timeline before editing any repo.
- If the task points to repo work, obey the repo's local instructions and decision records before changing code.
- If local state is missing a task or related page, reconcile from Notion before continuing.

## Miscellaneous And Synthesis

- Use miscellaneous notes for context that is useful but not yet attached to a specific task.
- Use synthesis pages for reusable conclusions across tasks, notes, docs, links, or conversations.
- Fetch sources only deeply enough to support the synthesis; preserve source labels and links clearly.

## Reporting Back

After a tracker write, report the task or note updated, important Notion operations completed, tracker-state path if relevant, warnings, and blockers. Keep command syntax and schema details out of the skill response unless the user asks; point to README for exact forms.
