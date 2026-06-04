# Notion Task Tracker

This package turns explicit CLI actions into Notion writes. The agent supplies intent; the tracker owns tree projection, page shape, rendering, write ordering, and Notion SDK calls. Task metadata now comes from `Alovya's task database`; task page bodies contain timeline logs only, and the ongoing and completed task landing pages are derived views.

Fixed page names live in `fixed_pages.py`:

1. `Alovya's ongoing tasks landing page`
2. `Alovya's completed tasks landing page`
3. `Alovya's miscellanous notes`
4. `Alovya's synthesis notes`

Notion page ids live in tracker state because Notion assigns them. The task database source and saved-view URLs live in `tasks/database.py`.

## Agent Workflow

1. Choose one explicit CLI action such as `--log`, `--child`, or `--read`.
2. Put multi-paragraph or nested content in a JSON file passed through `--content-path`.
3. Let the CLI resolve tracker state, the Notion API token, and output paths from its defaults.
4. The CLI fetches only task pages needed by that action, updates their local metadata projection, applies the command, writes to Notion when the action is mutating, and saves tracker state after successful writes.
5. Read the output JSON for completed operation keys, read summaries, and warnings.
6. Treat a CLI failure as a failed write. Do not manually send Notion writes unless debugging with the user.

The default tracker state path is `~/.notion-task-tracker/notion_tasks_tree.json`. Override it only with `--tracker-state-path`. Authentication uses `NOTION_API_KEY`.

Run an explicit action from an environment where `notion-task-tracker` is installed:

```bash
ntt \
  --log \
  --ticket-number 67 \
  --content-path /tmp/notion_task_log.json
```

Execution needs `NOTION_API_KEY` to contain the `ntn_` Notion integration token.

Install the package into the local venv with:

```bash
/workspace/venv/bin/python -m pip install /home/alovyachowdhury/notion_task_tracker
```

Install it from GitHub with:

```bash
python -m pip install git+https://github.com/alovya/notion_task_tracker.git
```

During local development, install it as editable:

```bash
/workspace/venv/bin/python -m pip install -e /home/alovyachowdhury/notion_task_tracker
```

The package installs `ntt` and `notion-task-tracker` console commands. `python -m notion_task_tracker` remains supported.

Install the task-tracker skill into Codex and Claude user-scope skill directories with:

```bash
ntt --install-skill
```

This requires `CODEX_HOME` and `CLAUDE_CONFIG_DIR`, then copies root `SKILL.md` to `$CODEX_HOME/skills/notion_task_tracker/SKILL.md` and `$CLAUDE_CONFIG_DIR/skills/notion_task_tracker/SKILL.md`. Existing identical files are left alone; differing files are not overwritten.

Mutating action output contains:

1. `backup_path`: tracker state backup from before the command.
2. `action_name`: explicit CLI action that ran.
3. `completed_operations`: operation keys successfully written to Notion.
4. `tracker_state_path`: canonical tracker-state path written after Notion writes succeeded.
5. `warnings`: non-fatal reconciliation warnings.

The live path uses the Notion REST client for task creation, logging, completion, reconciliation, and landing-page rendering.

## Explicit CLI Actions

Use these actions for normal agent operation. The action flag freezes the accepted schema; `--content-path` carries the rich content.

```bash
python -m notion_task_tracker --read --ticket-number 67 --ticket-number 80
python -m notion_task_tracker --work --ticket-number 67
python -m notion_task_tracker --log --ticket-number 67 --content-path /tmp/log.json
python -m notion_task_tracker --complete --ticket-number 67 --content-path /tmp/complete.json
python -m notion_task_tracker --cancel --ticket-number 67 --content-path /tmp/cancel.json
python -m notion_task_tracker --parent --title "Measure activation mismatch" --priority P1 --content-path /tmp/initial.json
python -m notion_task_tracker --child --parent-ticket-number 67 --title "Add explicit CLI actions" --title "Document explicit CLI actions" --priority P1 --content-path /tmp/initial.json
python -m notion_task_tracker --sibling --sibling-ticket-number 67 --title "Document explicit CLI actions" --priority P2 --content-path /tmp/initial.json
python -m notion_task_tracker --misc --content-path /tmp/misc.json
python -m notion_task_tracker --synth --synthesis-key explicit_tracker_cli --title "Explicit tracker CLI" --content-path /tmp/synth.json
```

`--read` and `--work` are read-only with respect to Notion. They fetch live task pages, refresh local task metadata, write a JSON summary to `--output-path`, and perform no Notion writes.

Timeline content files for `--log`, `--complete`, `--cancel`, `--parent`, `--child`, and `--sibling` use this shape:

```json
{
  "subheading": "Optional toggle title",
  "blocks": [
    {
      "type": "paragraph",
      "text": "Investigated the REST migration boundary."
    },
    {
      "type": "code",
      "language": "bash",
      "text": "python -m notion_task_tracker --read --ticket-number 67"
    }
  ]
}
```

Miscellaneous content files use `lines` or paragraph `blocks`:

```json
{
  "lines": ["Captured context that does not yet belong on a task."]
}
```

Synthesis content files use this shape:

```json
{
  "summary": "Reusable tracker CLI design.",
  "sources": [
    {
      "source_type": "Notion page",
      "label": "ALOVYA-67",
      "page_key": "task:ALOVYA-67"
    }
  ],
  "lines": ["Actions freeze schemas; content remains free-form."]
}
```

## Fetch And Reconcile From Notion

Use this when the user edited task rows in the Notion UI:

```bash
ntt --reconcile-from-notion
```

This command creates a timestamped backup under `/tmp`, queries the saved `Alovya's task database` view, rebuilds the local tree projection from row properties, and repairs derived landing pages or task titles when needed.

Ordinary commands do not query the full database view. They fetch the task pages they depend on, so command execution is not blocked by slow saved-view export. If a targeted fetch finds a parent page outside local tracker state, run the full update command before retrying.

### Targeted Preflight Footguns

Normal commands are fast because they only refresh the task pages they touch. They do not discover every remote database edit.

1. `append_task_timeline_log`, `complete_task`, and `cancel_task` fetch the target task page, refresh that task's database properties in local state, fetch timeline headings, then write.
2. `split_task_into_children` fetches the source task and parent chain, creates two child database rows, clears the source task's dependency/dependant relations, updates the source timeline, and refreshes derived landing pages.
3. `split_task_with_sibling` fetches the source sibling and parent chain, creates one new database row beside it, updates the parent timeline when there is a parent, and refreshes derived landing pages.
4. `create_top_level_task` creates a new top-level database row without fetching the full database view.
5. Miscellaneous and synthesis commands do not use the task database view.
6. `--reconcile-from-notion` is the only normal path that pulls the saved task database view and rebuilds the whole local task tree projection.

Run full reconciliation when a task was created only in Notion UI and is missing locally, when broad unrelated database edits must be reflected locally, when a manually added child or sibling must appear in derived landing pages, or when targeted preflight reports a missing related parent page.

Targeted preflight intentionally fails instead of guessing when the touched page has malformed task properties, reports a different `Ticket ID` than the requested task, has more than one parent, or points to a parent page that is absent from local tracker state.

Task ids are derived from Notion's `Ticket ID`. The visible Notion page title stays as the human title and does not include the `ALOVYA-N` prefix.

## Task Commands

Append a timeline log. Timeline logs are user-owned in Notion and may contain handwritten edits, so this command must emit targeted Notion writes. It must never replace a whole task page or landing page just to add log lines once a timeline log exists. Before writing, the CLI fetches the target task page and records any existing date headings under `Timeline log`. If the page lacks a usable `Timeline log` section with at least one date heading, the CLI initialises the body as `Timeline log`, today's date, then any existing body content underneath. New date sections are prepended directly under `Timeline log`; existing date sections get new lines inserted under their date heading:

```json
{
  "command": "append_task_timeline_log",
  "task_id": "ALOVYA-5",
  "timeline_entry": {
    "entry_date": "2026-05-24",
    "heading": "<mention-date start=\"2026-05-24\"/>",
    "lines": ["Investigated the current blocker."]
  }
}
```

Add `subheading` to put the new log lines under a Notion toggle for that date:

```json
{
  "command": "append_task_timeline_log",
  "task_id": "ALOVYA-5",
  "timeline_entry": {
    "entry_date": "2026-05-24",
    "heading": "<mention-date start=\"2026-05-24\"/>",
    "subheading": "Design notes",
    "lines": ["Moved task metadata into the database."]
  }
}
```

Complete a task. The tracker marks the task `Complete`, appends or merges the timeline entry by `entry_date`, updates database properties, and refreshes the ongoing and completed landing pages:

```json
{
  "command": "complete_task",
  "task_id": "ALOVYA-5",
  "timeline_entry": {
    "entry_date": "2026-05-24",
    "heading": "<mention-date start=\"2026-05-24\"/>",
    "lines": ["Completed the task."]
  }
}
```

Cancel a task. The tracker marks the task `Cancelled`, appends or merges the timeline entry by `entry_date`, updates database properties, and refreshes the ongoing and completed landing pages:

```json
{
  "command": "cancel_task",
  "task_id": "ALOVYA-5",
  "timeline_entry": {
    "entry_date": "2026-05-24",
    "heading": "<mention-date start=\"2026-05-24\"/>",
    "lines": ["Cancelled the task."]
  }
}
```

Create a top-level task. In database-backed mode, the tracker creates a database row, Notion assigns `Ticket ID`, and the tracker then records the assigned task id:

```json
{
  "command": "create_top_level_task",
  "task": {
    "title": "Measure activation mismatch after QNN export",
    "configured_priority": "P1",
    "status": "Active"
  },
  "timeline_entry": {
    "entry_date": "2026-05-24",
    "heading": "<mention-date start=\"2026-05-24\"/>",
    "lines": ["Started task: measure activation mismatch after QNN export."]
  }
}
```

Split a task into two child tasks. The command does not include child `task_id` values; Notion assigns them. Each new child page copies the source task's `Dependencies` and `Dependants`, is created with a dated Timeline log entry that links back to the source task, and the source task receives dated Timeline log entries that link to the created children. After the children are created, the source task becomes a parent/container and its own dependency and dependant relations are cleared:

```json
{
  "command": "split_task_into_children",
  "source_task_id": "ALOVYA-5",
  "child_tasks": [
    {
      "title": "Measure activation mismatch after QNN export",
      "configured_priority": "P1",
      "status": "Active"
    },
    {
      "title": "Document activation mismatch findings",
      "configured_priority": "P1",
      "status": "Active"
    }
  ],
  "parent_timeline_entry": {
    "entry_date": "2026-05-24",
    "heading": "<mention-date start=\"2026-05-24\"/>",
    "lines": ["Spawned child task: measure activation mismatch after QNN export."]
  }
}
```

Record a page id returned by `notion-create-pages`. This is used by miscellaneous and synthesis page creation; task creation captures the created database row and assigned `Ticket ID` inside live command execution:

```json
{
  "command": "record_page_id",
  "local_page_key": "miscellaneous:2026-05-24",
  "notion_page_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}
```

Refresh task views and task database properties:

```json
{
  "command": "refresh_task_pages",
  "operation_keys": ["update_properties:task:ALOVYA-5", "replace:ongoing_landing_page"]
}
```

Omit `operation_keys` to update every known task title/property and both task landing pages. Task page body replacement is not part of current task refresh; task bodies are timeline logs.

The ongoing and completed landing pages are rendered task indexes. They are not the source of truth for task membership or hierarchy. The ongoing landing page starts entries only from incomplete top-level tasks, but still shows completed subtasks inside those trees. The completed landing page starts entries only from completed or cancelled top-level tasks.

## Miscellaneous Commands

Append context to a dated miscellaneous page:

```json
{
  "command": "append_miscellaneous_note",
  "note_date": "2026-05-24",
  "lines": ["Recent context to preserve before it becomes a task or synthesis page."]
}
```

Refresh miscellaneous pages:

```json
{
  "command": "refresh_miscellaneous_pages"
}
```

## Synthesis Commands

Create a synthesis page with explicit sources:

```json
{
  "command": "create_synthesis_page",
  "synthesis_key": "onnx_qdq_export",
  "title": "ONNX QDQ export behaviour",
  "summary": "Reusable notes on export behaviour.",
  "sources": [
    {
      "source_type": "Notion page",
      "label": "ALOVYA-2",
      "page_key": "task:ALOVYA-2"
    },
    {
      "source_type": "Google doc",
      "label": "Export notes",
      "external_url": "https://example.invalid/doc"
    }
  ],
  "lines": ["QDQ nodes preserve quantisation boundaries for export."]
}
```

Reconcile the synthesis root after editing page mentions in Notion:

```json
{
  "command": "reconcile_synthesis_root_page_mentions",
  "root_page_content": "<mention-page url=\"https://www.notion.so/wayve/Guide-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\">Guide</mention-page>",
  "page_titles_by_id": {
    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb": "Title for a bare page mention"
  }
}
```

This replaces the local existing-page mention list with exactly the page mentions or child pages present on the fetched synthesis root. It emits no Notion write calls.

## Supported Commands

- `append_task_timeline_log`: add a dated timeline entry to one task with targeted page content. New dates are prepended under `Timeline log`; existing dates are updated under their date heading. It must not replace the task page or landing pages.
- `complete_task`: mark one task complete, append or merge a dated timeline entry, update database properties, and refresh the ongoing and completed landing pages.
- `cancel_task`: mark one task cancelled, append or merge a dated timeline entry, update database properties, and refresh the ongoing and completed landing pages.
- `create_top_level_task`: create a top-level task database row and use Notion's assigned `Ticket ID`.
- `split_task_into_children`: create two child task database rows under an existing source task, copy the source task's dependencies and dependants onto both children, clear the source task's own relation fields, initialise each child Timeline log with a parent link, and append source timeline entries linking to the children.
- `split_task_with_sibling`: create one task database row under the same parent as an existing source task, or top-level when the source has no parent. The new sibling copies the source task's dependencies and dependants. If the sibling has a parent, initialise the new page with a parent link and append a parent timeline entry linking to the new page.
- `record_page_id`: record a page id returned by a page creation write.
- `refresh_task_pages`: update task database properties and the derived task landing pages.
- `append_miscellaneous_note`: add lines to a dated miscellaneous subpage.
- `refresh_miscellaneous_pages`: regenerate the miscellaneous root and dated pages.
- `create_synthesis_page`: create one synthesis subpage with sources and content.
- `reconcile_synthesis_root_page_mentions`: update local synthesis-root references from fetched Notion page mentions without writing to Notion.
- `refresh_synthesis_pages`: regenerate the synthesis root page and tracker-created synthesis pages.

## Package Shape

The package is Python metadata and Notion write execution code. Live fetch/write execution uses the authenticated Notion REST client through `notion-client`.

- `pyproject.toml`: package metadata, runtime dependencies, and console scripts.
- `notion_task_tracker/__main__.py`: tiny shim for `python -m notion_task_tracker`.
- `notion_task_tracker/build_tracker_command.py`: build deterministic tracker commands from explicit CLI flags.
- `notion_task_tracker/run_notion_task_tracker.py`: parse explicit CLI actions, build tracker commands, run reads, writes, and full database reconciliation.
- `notion_task_tracker/apply_tracker_command.py`: apply one already-built tracker command to local state and derive Notion write intents.
- `notion_task_tracker/tasks/task_tree.py`: task tree validation, priority rollup, and task-write orchestration.
- `notion_task_tracker/tasks/database.py`: task database projection and database-row parsing.
- `notion_task_tracker/tasks/task.py`: task, priority, status, timeline-entry data, task property refresh intents, and timeline-log update intents.
- `notion_task_tracker/tasks/landing_pages.py`: ongoing and completed task landing-page rendering and refresh intents.
- `notion_task_tracker/tasks/timeline_log.py`: task page body parsing for timeline logs.
- `notion_task_tracker/tasks/create_task.py`: local task tree changes for creating parent, child, and sibling tasks.
- `notion_task_tracker/tasks/derive_task_timeline_log.py`: timeline-log facts derived from fetched task page content.
- `notion_task_tracker/tasks/refresh_task_tracker_state.py`: local task tree refresh from Notion database rows.
- `notion_task_tracker/notion_operations/`: Notion boundary code for page references, write intents, Markdown helpers, database-property conversion, the REST client, and write execution.
- `notion_task_tracker/fixed_pages.py`: names and local keys for fixed tracker pages.
- `notion_task_tracker/miscellaneous_pages.py`: dated miscellaneous notes.
- `notion_task_tracker/synthesis_pages.py`: flat synthesis root mentions and synthesis subpages with sources.

## Tests

```bash
cd /home/alovyachowdhury/notion_task_tracker
/workspace/venv/bin/python -m pytest tests
```
