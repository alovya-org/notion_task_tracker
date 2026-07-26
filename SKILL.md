---
name: notion-task-tracker
description: Manage Notion tasks using the `ntt` CLI. Use when the user asks to read, work on, log progress for, complete, cancel, delete, or create tasks (parent, child, sibling) in the Notion tracker.
---

# Notion task

Use the installed `ntt` CLI for all tracker reads and writes. **Always read `/workspace/notion_task_tracker/README.md` for exact flags, JSON shapes, command schemas, and implementation details.** This skill only captures agent judgment.

## Operating principles

- Let the CLI own Notion reads, task writes, managed-page repair and command-result output.
- Do not manually send Notion writes unless the user is explicitly debugging the tracker itself.
- Run live Notion commands outside the network-restricted sandbox with `NOTION_API_KEY` available.
- If auth, permission, page-id, or Notion content-replacement errors occur, stop and report the blocker. Do not guess around them.

## Context quality

Logs should preserve the facts needed to resume work without rereading the chat.

- Prefer rich blocks for normal logs: paragraphs for conclusions and decisions, code blocks for commands, outputs, diffs, stack traces, paths, JSON/YAML, and structured observations.
- Give every task timeline log a concise title that identifies the behaviour, decision, or result recorded by that log.
- Include exact commands, files, errors, outputs, and test results when they matter.
- In paragraph text, wrap inline technical names such as file paths, commands, environment variables, functions, class names, field names, tickets, and literal values in backticks.
- Keep observation, inference, decision, and follow-up distinct.
- Avoid bland summaries such as "Discussed X" when the useful content is what happened, what changed, and why.
- Put detailed work on the most specific task page. Parent timeline entries created by child or sibling splits are bookkeeping links, not substitutes for the real log.

## Task creation judgement

- If a create action includes useful initial context, write that context as the new task's initial timeline entry via `--content-path` rather than creating a bare task and logging afterward.
- Use explicit relation-edit actions later only when the user asks for manual metadata changes; let `ntt` handle inheritance during creation.

## Reading and working

- For `read`, answer from the CLI summary plus fetched task context.
- For `work`, use the task page for intent, status, blockers, links, and recent timeline before editing any repo.
- If the task points to repo work, obey the repo's local instructions and decision records before changing code.

## Reporting back

After a tracker write, report the task updated, important Notion operations completed, output path, warnings and blockers. Keep command syntax and schema details out of the skill response unless the user asks.
