# Notion task tracker

This package turns explicit CLI actions into Notion writes. Each user supplies one parent page and one fixed-schema task database. Initialisation creates three tracker-owned pages beneath that parent:

```text
Tracker parent page
├── <display name>'s ongoing tasks
├── <display name>'s completed tasks
└── <display name>'s tasks in execution order
```

Task metadata lives in the database. Task page bodies contain timeline logs, while the ongoing and completed pages are derived views.

## Install

Install the package into a virtual environment from the repository directory:

```bash
python -m pip install .
```

Install it from GitHub with:

```bash
python -m pip install git+https://github.com/alovya/notion_task_tracker.git
```

During local development, install it as editable:

```bash
python -m pip install -e .
```

The package installs `ntt` and `notion-task-tracker` console commands. `python -m notion_task_tracker` remains supported.

## Initialise a tracker

Create these two objects in the Notion UI:

1. One ordinary parent page. Connect the Notion integration to this page so it can create the four managed child pages.
2. One task database using the fixed schema below. The database may also live beneath the parent page. Connect the integration to the database as well.

| Property | Notion type | Required values or relation |
|---|---|---|
| `Task page` | Title | Task title |
| `Task ID` | Unique ID | Notion-assigned number |
| `Priority` | Select | `P0`, `P1`, `P2`, `P3` |
| `Status` | Select | `Active`, `Blocked`, `Parked`, `Complete`, `Cancelled` |
| `Parent` | Relation | Same task database |
| `Dependencies` | Relation | Same task database |
| `Dependants` | Relation | Same task database |
| `Deadline` | Date | Optional date |
| `Start` | Date | Optional scheduled start, with or without a time |
| `End` | Date | Optional end derived and maintained by NTT |
| `Duration` | Number | Optional independent duration estimate |
| `Duration unit` | Select | `Hours`, `Days`, `Weeks` |
| `External coordination` | Select | `No`, `Yes` |
| `Uncertainty` | Select | `Low`, `High` |
| `Friction` | Select | `None`, `Insufficiently decomposed`, `Charged`, `Stale` |

`Duration` and `Duration unit` are set together, but they do not require `Start`; a task may be estimated before it is scheduled. Timed starts use `Hours`. Date-only starts use whole `Days` or `Weeks`, where one week means seven calendar days. `End` is empty until the task has a complete schedule, then NTT derives and maintains it as `Start + Duration`. It is never an independently authored source value.

Set `NOTION_API_KEY` to the integration token, then initialise with the two URLs:

```bash
ntt --init \
  --display-name "Example" \
  --ticket-prefix EXAMPLE \
  --parent-page-url "https://www.notion.so/..." \
  --task-database-url "https://www.notion.so/..."
```

Initialisation validates the database property names and types, discovers its data-source ID, creates the five managed pages, and records the URLs returned by Notion. It refuses to replace existing tracker files.

Configuration is written to the platform user-configuration directory:

- Linux: `$XDG_CONFIG_HOME/notion-task-tracker/config.toml`, falling back to `~/.config/notion-task-tracker/config.toml`.
- macOS: `~/Library/Application Support/notion-task-tracker/config.toml`.
- Windows: the user application-data directory returned by `platformdirs`.

Set `NTT_CONFIG_PATH` or pass `--config-path` to use another file. Mutable tracker state remains at `~/.notion-task-tracker/notion_tasks_tree.json` unless `--tracker-state-path` is supplied.

The configuration contains identity, the two supplied URLs, and the three generated page URLs. Database property names are defined by the codebase, not user configuration. Keep `NOTION_API_KEY` in the environment or a private secret store; it is never written to configuration or state.

```toml
[identity]
display_name = "Example"
ticket_prefix = "EXAMPLE"

[notion]
parent_page_url = "https://www.notion.so/..."
task_database_url = "https://www.notion.so/..."

[pages]
ongoing_tasks_url = "https://www.notion.so/..."
completed_tasks_url = "https://www.notion.so/..."
ready_priority_page_url = "https://www.notion.so/..."
```

Run an explicit action after initialisation:

```bash
ntt --log --ticket-number 67 --content-path /tmp/notion_task_log.json
```

## Install the agent skill

Install the task-tracker skill into Codex and Claude user-scope skill directories with:

```bash
ntt --install-skill
```

For each configured tool, this copies root `SKILL.md` to `$CODEX_HOME/skills/notion_task_tracker/SKILL.md` or `$CLAUDE_CONFIG_DIR/skills/notion_task_tracker/SKILL.md`. Unconfigured tools are skipped with a warning. Existing identical files are left alone; differing files are not overwritten.

Mutating action output contains:

1. `backup_path`: tracker state backup from before the command.
2. `action_name`: explicit CLI action that ran.
3. `completed_operations`: operation keys successfully written to Notion.
4. `tracker_state_path`: canonical tracker-state path written after Notion writes succeeded.
5. `warnings`: non-fatal refresh or synchronisation warnings.

The live path uses the Notion REST client for task creation, logging, completion, tracker refreshes, and landing-page rendering.

## Explicit CLI actions

Use these actions for normal CLI operation. The action flag freezes the accepted schema; `--content-path` carries the rich content.

```bash
python -m notion_task_tracker --read --ticket-number 67 --ticket-number 80
python -m notion_task_tracker --read-all --ticket-number 67
python -m notion_task_tracker --work --ticket-number 67
python -m notion_task_tracker --log --ticket-number 67 --content-path /tmp/log.json
python -m notion_task_tracker --complete --ticket-number 67 --content-path /tmp/complete.json
python -m notion_task_tracker --cancel --ticket-number 67 --content-path /tmp/cancel.json
python -m notion_task_tracker --delete --ticket-number 67
python -m notion_task_tracker --set-start --ticket-number 67 --start "2026-07-23T09:30"
python -m notion_task_tracker --clear-start --ticket-number 67
python -m notion_task_tracker --set-duration --ticket-number 67 --duration 2.5 --duration-unit Hours
python -m notion_task_tracker --clear-duration --ticket-number 67
python -m notion_task_tracker --parent --title "Measure activation mismatch" --priority P1 --content-path /tmp/initial.json
python -m notion_task_tracker --child --parent-ticket-number 67 --title "Add explicit CLI actions" --priority P1 --content-path /tmp/initial.json
python -m notion_task_tracker --sibling --sibling-ticket-number 67 --title "Document explicit CLI actions" --priority P2 --content-path /tmp/initial.json
python -m notion_task_tracker --move-logs --ticket-number 67 --destination-ticket-number 68 --log-id ALOVYA-LOG-55d04742-f584-4b28-b47d-e383f87406c0
```

`--read`, `--read-all`, and `--work` are read-only with respect to Notion. They fetch live task pages, refresh local task metadata, write JSON to `--output-path`, and perform no Notion writes. `--read` and `--work` include a five-line page summary; `--read-all` additionally includes the complete fetched page markup in each task's `full_page_content` field.

Scheduling actions update `Start` and `Duration` independently. `--set-start` accepts `YYYY-MM-DD`, `YYYY-MM-DD HH:MM`, or `YYYY-MM-DDTHH:MM`; NTT applies the machine's local timezone to timed starts. `--set-duration` requires a positive duration together with `Hours`, `Days`, or `Weeks`. A duration estimate may exist without a start. NTT always derives `End` when both fields form a complete valid schedule; clearing either field clears `End` without clearing the other field.

Timeline content files for `--log`, `--complete`, `--cancel`, `--parent`, `--child`, and `--sibling` use this shape:

```json
{
  "title": "REST migration investigation",
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

Every timeline write creates one Notion toggle beneath its date heading. The CLI combines the configured ticket prefix with a UUID4 logical identifier and appends it to the supplied title, producing a toggle title such as `REST migration investigation · ALOVYA-LOG-55d04742-f584-4b28-b47d-e383f87406c0` when `ticket_prefix` is `ALOVYA`. The identifier remains part of that log when it is later copied or moved. Existing raw timeline content is left unchanged.

Move one identified timeline log by giving its source task, destination task, and logical identifier. The CLI reads both pages, copies the complete toggle to the same date on the destination, verifies the copy, removes the physical source block, then verifies its removal. A retry after an interrupted copy detects the logical identifier at the destination and continues with source removal. If `--log-id` is omitted and the source does not contain exactly one movable log, the CLI performs no writes and returns compact candidates containing only the date, title, and logical identifier. Raw legacy logs and toggles without an identifier are not candidates.

## Refresh the Notion task tracker

Use this when the user edited task rows in the Notion UI:

```bash
ntt --refresh-notion-task-tracker
```

This command creates a timestamped backup under `/tmp`, queries the configured task database data source, rebuilds local tracker state from row properties, and repairs derived landing pages or task titles when needed. If the tracker state JSON is missing, the command first creates local state from `config.toml`: it resolves the task database data-source id, derives managed page ids from the configured page URLs, writes empty task state, and then continues the refresh. This bootstrap step does not create Notion pages.

Refreshing the tracker also updates the task execution-order page as an unsorted linked table over the task database. A task appears there only when it is not complete or cancelled, has no children, and either has no dependencies or every dependency is complete. NTT records that derived membership in the `In execution order` checkbox; the view only filters for checked rows and does not contain readiness logic. The table shows `Task page`, `Priority`, `Deadline`, `Start`, `End`, `Duration`, `Duration unit`, `Status`, `Parent`, `Dependencies`, `Dependants`, `External coordination`, `Uncertainty`, and `Friction`. Newly eligible rows appear at the bottom and can be dragged into the desired order in Notion.

The managed execution-order page must be empty when NTT creates its linked table. After creation it may contain only that linked database. NTT fails clearly instead of interpreting or replacing other page content.

The state bootstrap requires the `[pages]` URLs written by `ntt --init`:

```toml
[pages]
ongoing_tasks_url = "https://www.notion.so/..."
completed_tasks_url = "https://www.notion.so/..."
ready_priority_page_url = "https://www.notion.so/..."
```

## Google Calendar synchronisation

Google Calendar presents scheduled NTT work; Notion remains the task database. A task appears in Calendar only when it is active, has no children, and has a complete `Start`, `Duration`, and `Duration unit` schedule.

For example:

```text
Notion task: [ALOVYA-42] Pay council tax
Start:       2026-08-03 10:00
Duration:    1 hour

Google event: [NTT] Pay council tax
Start:        2026-08-03 10:00
End:          2026-08-03 11:00
```

The synchronisation supports three user-visible changes:

1. Change the task schedule in Notion. The next synchronisation creates or updates its Google event.
2. Move or resize the owned Google event. The next synchronisation writes the resulting start and duration to Notion.
3. Delete the owned Google event. The next synchronisation clears the task's schedule in Notion.

NTT also deletes Calendar events itself when their tasks become complete, cancelled, unscheduled, non-active, parents, or absent. Google reports those deletions through the same notification system as a deletion made by a person. NTT therefore keeps a small durable D1 ledger:

```text
Google event ID   NTT task ID   Lifecycle
google-789        ALOVYA-42     active
```

Before NTT deletes an event, it changes that row to `deleted_by_ntt`. When Google's cancellation later arrives, NTT can distinguish the two meanings:

1. An active mapping was cancelled: the person deleted the event, so unschedule the task.
2. A `deleted_by_ntt` mapping was cancelled: NTT is seeing confirmation of its own deletion, so leave the task unchanged.

Google may return a cancelled event containing only its event ID. The ledger supplies the missing task identity. It stores current mappings and short-lived deletion provenance, not edit history. Acknowledged cancellations are removed, and expired notification channels are pruned.

### The synchronisation lifecycle

Google's notification contains no changed event. It only tells the Cloudflare Worker that something may have changed. Every Notion webhook, Google notification, daily recovery, or manual wake-up enters the same tracker-scoped GitHub concurrency group and performs one ordered lifecycle:

1. Build current local tracker state from Notion.
2. Read the current Google change cursor and event ledger from D1 after the workflow enters concurrency.
3. Ask Google for every change after that cursor.
4. Apply owned Google moves, resizes, and user deletions to Notion.
5. Persist the corresponding ledger transitions.
6. Advance the D1 cursor only after those Notion and ledger writes succeed.
7. Refresh authoritative Notion state again.
8. Create, replace, or delete Google events until Calendar matches Notion.

Dispatch payloads contain only `tracker_user`; they never carry the change cursor. Duplicate or coalesced wake-ups are safe because whichever run survives reads the latest durable cursor when it starts. If Google expires a cursor, NTT fetches a complete owned-event snapshot, compares it with the previous ledger, applies missing active events as user deletions, replaces the ledger, then saves the rebuilt cursor.

Google notification channels expire and cannot be extended. The maintenance workflow creates a replacement before the current channel expires. If it finds that the previous channel already expired, it renews the channel and wakes the ordinary synchronisation workflow rather than reconciling concurrently. Notifications stop authenticating ten minutes after their recorded expiry, and later maintenance removes their D1 rows. Cloudflare also wakes synchronisation every day at `00:00 UTC` so a missed notification cannot permanently hide changes.

### Calendar configuration

Configure the non-secret Calendar identity and display behaviour:

```toml
[calendar]
calendar_id = "primary"
timezone_name = "Europe/London"
colour_id = "8"
```

Keep Google OAuth secrets outside this file. Set `GOOGLE_CALENDAR_CLIENT_ID`, `GOOGLE_CALENDAR_CLIENT_SECRET`, and `GOOGLE_CALENDAR_REFRESH_TOKEN` in the process environment or deployment secret store. Obtain the refresh token through offline OAuth consent using only `https://www.googleapis.com/auth/calendar.events`; NTT does not request Gmail access. The Calendar client renews short-lived access tokens automatically. If the OAuth application is external and remains in Google's testing state, confirm its refresh-token lifetime before relying on unattended synchronisation.

Sync scheduled active leaf tasks after refreshing the current Notion database:

```bash
ntt --sync-tasks-to-google-calendar --tracker-user al0vya
```

Apply outstanding Google changes using the current cursor stored in D1:

```bash
ntt --apply-google-calendar-changes-to-tasks --tracker-user al0vya
```

Maintain the temporary Google notification channel:

```bash
ntt --maintain-google-calendar-notification-channel \
  --tracker-user al0vya \
  --calendar-notification-url https://<worker>/google-calendar-notifications
```

NTT identifies live owned events through private Google extended properties containing the configured ticket prefix and full task ID. It creates missing events, replaces changed events, and deletes only uniquely identified NTT events whose task is no longer eligible. Foreign, malformed, and duplicate events are preserved. Synced task slots use an `[NTT]` title, remain transparent so meetings may be booked over them, and may use the configured colour. Keep recurring daily routines as native recurring Google Calendar events; synchronisation covers only tasks stored in the NTT task database.

Ordinary commands do not query the full database. They fetch the task pages they depend on. If a targeted fetch finds a parent page outside local tracker state, run the full update command before retrying.

### Targeted preflight footguns

Normal commands are fast because they only refresh the task pages they touch. They do not discover every remote database edit.

1. `append_task_timeline_log`, `complete_task`, and `cancel_task` fetch the target task page, refresh that task's database properties in local state, fetch timeline headings, then write.
2. `split_task_into_children` fetches the source task and parent chain, creates one child database row, clears the source task's dependency/dependant relations, updates the source timeline, and refreshes derived landing pages.
3. `split_task_with_sibling` fetches the source sibling and parent chain, creates one new database row beside it, updates the parent timeline when there is a parent, and refreshes derived landing pages.
4. `create_top_level_task` creates a new top-level database row without fetching the full database.
5. `--refresh-notion-task-tracker` is the only normal path that queries every task row and rebuilds the whole local task tree.

Run a full tracker refresh when a task was created only in the Notion UI and is missing locally, when broad unrelated database edits must be reflected locally, when a manually added child or sibling must appear in derived landing pages, or when targeted preflight reports a missing related parent page.

Targeted preflight intentionally fails instead of guessing when the touched page has malformed task properties, reports a different `Task ID` than the requested task, has more than one parent, or points to a parent page that is absent from local tracker state.

Task ids are derived from Notion's `Task ID`. The visible Notion page title stays as the human title and does not include the `EXAMPLE-N` prefix.

## Synchronise from GitHub Actions

`.github/workflows/refresh-notion-task-tracker.yml` owns the complete two-way lifecycle described above. Notion dispatches, Google dispatches, and manual runs all wake this workflow rather than selecting separate one-way workflows.

Each tracker user is represented by one GitHub environment. The environment name is the `tracker_user` value passed to the workflow. Each environment must define:

- `NTT_CONFIG_TOML`: the full `config.toml` created by that user's local `ntt --init`.
- `NOTION_API_KEY`: the Notion integration token connected to that user's tracker parent page, task database, and managed pages.
- `GOOGLE_CALENDAR_CLIENT_ID`: the OAuth application identity.
- `GOOGLE_CALENDAR_CLIENT_SECRET`: the OAuth application credential.
- `GOOGLE_CALENDAR_REFRESH_TOKEN`: the user's offline Calendar delegation.
- `NTT_GOOGLE_CALENDAR_STATE_API_TOKEN`: the shared secret used to call the Worker's authenticated Calendar state API.

The environment must also define `NTT_GOOGLE_CALENDAR_NOTIFICATION_URL` and `NTT_GOOGLE_CALENDAR_STATE_API_URL` as non-secret variables.

Provision a tracker environment with:

```bash
TRACKER_USER=al0vya

gh api \
  --method PUT \
  "repos/:owner/:repo/environments/$TRACKER_USER"

gh secret set NTT_CONFIG_TOML --env "$TRACKER_USER" < ~/.config/notion-task-tracker/config.toml
gh secret set NOTION_API_KEY --env "$TRACKER_USER"
gh secret set GOOGLE_CALENDAR_CLIENT_ID --env "$TRACKER_USER"
gh secret set GOOGLE_CALENDAR_CLIENT_SECRET --env "$TRACKER_USER"
gh secret set GOOGLE_CALENDAR_REFRESH_TOKEN --env "$TRACKER_USER"
gh secret set NTT_GOOGLE_CALENDAR_STATE_API_TOKEN --env "$TRACKER_USER"
```

Commands without redirected input prompt for their value. Manual synchronisations run from the GitHub Actions page by entering the tracker user. External Notion wake-ups use `repository_dispatch`:

```json
{
  "event_type": "refresh-notion-task-tracker",
  "client_payload": {
    "tracker_user": "al0vya"
  }
}
```

Google wake-ups use event type `apply-google-calendar-changes-to-notion-task-tracker` with the same identity-only payload. Neither event contains a Google cursor. The GitHub token used to dispatch the workflow is separate from the Notion and Google credentials.

The scheduled notification-channel maintenance deployment deliberately uses the `al0vya` GitHub environment. The central workflow and D1 schema retain `tracker_user` as a tenant boundary, but adding another environment does not automatically schedule that user's channel renewal. The workflow contains a TODO at this boundary.

Ordinary jobs receive only `contents: read`. A separate failure-reporting job receives `issues: write` only after its main job fails and creates an issue linking to the failed run.

## Refresh from a Notion webhook

`cloudflare_worker/` contains a small Cloudflare Worker that turns two Notion webhook headers into the authenticated GitHub `repository_dispatch` request above. Notion sends a shared secret to the Worker, the Worker dispatches `refresh-notion-task-tracker`, and GitHub Actions refreshes the configured tracker user.

Install the pinned Worker development dependencies and verify the Worker locally:

```bash
cd cloudflare_worker
npm ci
npm test
npm run typecheck
```

`package.json` declares the Node.js tools and `package-lock.json` pins their complete dependency tree. Use `npm ci` for a reproducible clean install.

Configure the Worker secrets with the pinned local Wrangler installation:

```bash
cd cloudflare_worker
npx wrangler secret put GITHUB_REPOSITORY_DISPATCH_TOKEN
npx wrangler secret put NOTION_WEBHOOK_SECRET
npx wrangler secret put NTT_GOOGLE_CALENDAR_STATE_API_TOKEN
```

`GITHUB_REPOSITORY_DISPATCH_TOKEN` is a GitHub token that can create repository dispatch events for this repository. `NOTION_WEBHOOK_SECRET` is any strong shared value that Notion will send to the Worker. `NTT_GOOGLE_CALENDAR_STATE_API_TOKEN` authenticates GitHub when it reads or changes channels, cursors and the event ledger or requests a synchronisation dispatch through the Worker. Store the same randomly generated value under that exact name in both Cloudflare and the GitHub environment.

Apply D1 migrations before deploying code that uses a new schema:

```bash
cd cloudflare_worker
npx wrangler d1 migrations apply GOOGLE_CALENDAR_STATE_DATABASE --remote
```

Deploy the Worker:

```bash
cd cloudflare_worker
npm run deploy
```

Configure these GitHub environment variables with URLs from the deployed Worker:

```text
NTT_GOOGLE_CALENDAR_NOTIFICATION_URL=https://<worker>/google-calendar-notifications
NTT_GOOGLE_CALENDAR_STATE_API_URL=https://<worker>/google-calendar
```

Configure Notion's `Send webhook` action to call the deployed Worker's `/notion-task-tracker-changes` URL with `POST`. Add these custom headers:

```text
notion_webhook_secret: the same value stored in Cloudflare
tracker_user: al0vya
```

Both values are required as headers. The Worker deliberately rejects body fields, URL parameters, aliases, and other fallback formats. `tracker_user` is the GitHub environment name that owns `NTT_CONFIG_TOML` and `NOTION_API_KEY`.

Configure a Cloudflare alert for failures of the Worker's scheduled `00:00 UTC` handler. GitHub failure issues cover synchronisation and channel-maintenance jobs, but they cannot report a failure that prevents the Worker from reaching GitHub at all.

## Task commands

Append a timeline log. Timeline logs are user-owned in Notion and may contain handwritten edits, so this command must emit targeted Notion writes. It must never replace a whole task page or landing page just to add log lines once a timeline log exists. Before writing, the CLI fetches the target task page and records any existing date headings under `Timeline log`. If the page lacks a usable `Timeline log` section with at least one date heading, the CLI initialises the body as `Timeline log`, today's date, then any existing body content underneath. New date sections are prepended directly under `Timeline log`; existing dates receive another toggle without changing legacy raw content:

```json
{
  "command": "append_task_timeline_log",
  "task_id": "EXAMPLE-5",
  "timeline_entry": {
    "log_id": "ALOVYA-LOG-55d04742-f584-4b28-b47d-e383f87406c0",
    "title": "Remaining blocker",
    "entry_date": "2026-05-24",
    "heading": "<mention-date start=\"2026-05-24\"/>",
    "lines": ["Investigated the current blocker."]
  }
}
```

Complete a task. The tracker marks the task `Complete`, appends an identified timeline toggle beneath `entry_date`, updates database properties, and refreshes the ongoing and completed landing pages:

```json
{
  "command": "complete_task",
  "task_id": "EXAMPLE-5",
  "timeline_entry": {
    "log_id": "ALOVYA-LOG-7a741bb7-6946-47e0-a749-fb57f9608e44",
    "title": "Completed task",
    "entry_date": "2026-05-24",
    "heading": "<mention-date start=\"2026-05-24\"/>",
    "lines": ["Completed the task."]
  }
}
```

Cancel a task. The tracker marks the task `Cancelled`, appends an identified timeline toggle beneath `entry_date`, updates database properties, and refreshes the ongoing and completed landing pages:

```json
{
  "command": "cancel_task",
  "task_id": "EXAMPLE-5",
  "timeline_entry": {
    "log_id": "ALOVYA-LOG-850cabed-c36f-424d-89c5-6bc02fa6e65a",
    "title": "Cancelled task",
    "entry_date": "2026-05-24",
    "heading": "<mention-date start=\"2026-05-24\"/>",
    "lines": ["Cancelled the task."]
  }
}
```

Delete a task. The tracker moves its Notion database page to trash, removes it from local state and both landing pages, promotes its children to its parent, and removes it from dependency relationships:

```bash
ntt --delete --ticket-number 67
```

Create a top-level task. In database-backed mode, the tracker creates a database row, Notion assigns `Task ID`, and the tracker then records the assigned task id:

```json
{
  "command": "create_top_level_task",
  "task": {
    "title": "Measure activation mismatch after QNN export",
    "configured_priority": "P1",
    "status": "Active"
  },
  "timeline_entry": {
    "log_id": "ALOVYA-LOG-a4f10b8d-928e-49f5-aa42-d8bf86b02631",
    "title": "Started activation measurement",
    "entry_date": "2026-05-24",
    "heading": "<mention-date start=\"2026-05-24\"/>",
    "lines": ["Started task: measure activation mismatch after QNN export."]
  }
}
```

Add one child task under an existing parent task. The command does not include a child `task_id`; Notion assigns it. The new child page copies the source task's `Dependencies` and `Dependants`, is created with a dated Timeline log entry that links back to the source task, and the source task receives a dated Timeline log entry that links to the created child. After the child is created, the source task becomes a parent/container and its own dependency and dependant relations are cleared:

```json
{
  "command": "split_task_into_children",
  "source_task_id": "EXAMPLE-5",
  "child_tasks": [
    {
      "title": "Measure activation mismatch after QNN export",
      "configured_priority": "P1",
      "status": "Active"
    }
  ],
  "parent_timeline_entry": {
    "log_id": "ALOVYA-LOG-9cad02f6-f3a8-4586-9c66-7fb7f5514db6",
    "title": "Created activation measurement child",
    "entry_date": "2026-05-24",
    "heading": "<mention-date start=\"2026-05-24\"/>",
    "lines": ["Spawned child task: measure activation mismatch after QNN export."]
  }
}
```

Refresh task views and task database properties:

```json
{
  "command": "refresh_task_pages",
  "operation_keys": ["update_properties:task:EXAMPLE-5", "replace:ongoing_landing_page"]
}
```

Omit `operation_keys` to update every known task title/property and both task landing pages. Task page body replacement is not part of current task refresh; task bodies are timeline logs.

The ongoing and completed landing pages are rendered task indexes. They are not the source of truth for task membership or hierarchy. The ongoing landing page starts entries only from incomplete top-level tasks, but still shows completed subtasks inside those trees. The completed landing page starts entries only from completed or cancelled top-level tasks.

## Supported commands

- `append_task_timeline_log`: add one UUID4-identified toggle beneath a task's date heading with targeted page content. New dates are prepended under `Timeline log`; existing dates receive another toggle. It must not replace the task page or landing pages.
- `move_task_timeline_log`: copy one identified toggle to another task page, verify the destination, reuse an existing destination copy with the same logical identifier, delete its physical source block, then verify the source.
- `complete_task`: mark one task complete, append an identified dated timeline toggle, update database properties, and refresh the ongoing and completed landing pages.
- `cancel_task`: mark one task cancelled, append an identified dated timeline toggle, update database properties, and refresh the ongoing and completed landing pages.
- `delete_task`: move one task page to trash, remove its local state and relationships, promote its children, and refresh both landing pages.
- `create_top_level_task`: create a top-level task database row and use Notion's assigned `Task ID`.
- `split_task_into_children`: create one child task database row under an existing source task, copy the source task's dependencies and dependants onto the child, clear the source task's own relation fields, initialise the child Timeline log with a parent link, and append a source timeline entry linking to the child.
- `split_task_with_sibling`: create one task database row under the same parent as an existing source task, or top-level when the source has no parent. The new sibling copies the source task's dependencies and dependants. If the sibling has a parent, initialise the new page with a parent link and append a parent timeline entry linking to the new page.
- `record_page_id`: record a page id returned by a page creation write.
- `refresh_task_pages`: update task database properties and the derived task landing pages.

## Package shape

The package is Python metadata and Notion write execution code. Live fetch/write execution uses the authenticated Notion REST client through `notion-client`.

- `pyproject.toml`: package metadata, runtime dependencies, and console scripts.
- `notion_task_tracker/__main__.py`: tiny shim for `python -m notion_task_tracker`.
- `notion_task_tracker/build_tracker_command.py`: build deterministic tracker commands from explicit CLI flags.
- `notion_task_tracker/config.py`: load and write per-user identity and Notion location configuration.
- `notion_task_tracker/initialise_tracker.py`: validate the supplied database, create managed pages, and write initial local files.
- `notion_task_tracker/run_notion_task_tracker.py`: parse explicit CLI actions, build tracker commands, run reads, writes, and full tracker refreshes from Notion.
- `notion_task_tracker/apply_tracker_command.py`: apply one already-built tracker command to local state and derive Notion write intents.
- `notion_task_tracker/tasks/task_tree.py`: task tree validation, priority rollup, and task-write orchestration.
- `notion_task_tracker/tasks/database.py`: task database rows and their parsing.
- `notion_task_tracker/tasks/task.py`: task, priority, status, timeline-entry data, task property refresh intents, and timeline-log update intents.
- `notion_task_tracker/tasks/landing_pages.py`: ongoing and completed task landing-page rendering and refresh intents.
- `notion_task_tracker/tasks/timeline_log.py`: task page body parsing for timeline logs.
- `notion_task_tracker/tasks/create_task.py`: local task tree changes for creating parent, child, and sibling tasks.
- `notion_task_tracker/tasks/derive_task_timeline_log.py`: timeline-log facts derived from fetched task page content.
- `notion_task_tracker/tasks/refresh_task_tracker_state.py`: local task tree refresh from Notion database rows.
- `notion_task_tracker/notion_operations/`: Notion boundary code for page references, write intents, Markdown helpers, database-property conversion, the REST client, and write execution.
- `notion_task_tracker/fixed_pages.py`: stable local keys and generic defaults for tracker pages.

## Tests

```bash
cd /path/to/notion_task_tracker
python -m pytest tests
```
