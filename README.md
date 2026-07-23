# Notion task tracker

Notion task tracker turns explicit command-line actions into Notion task changes and keeps eligible scheduled tasks visible in Google Calendar.

## Authority boundaries

Each system owns a deliberately narrow part of the tracker:

| System | Values it owns |
|---|---|
| Notion | Task identity, title, hierarchy, dependencies, status, priority, schedule, timeline content and the rendered managed pages |
| Google Calendar | The current presentation of eligible scheduled tasks; a person may move, resize or delete an event that is uniquely owned by the tracker |
| Cloudflare D1 | The Calendar synchronisation cursor, Google-event-to-task identity and tracker-originated deletion provenance |
| GitHub Actions | Wake-ups and serialised execution of the same complete synchronisation lifecycle |

Notion is the task authority. Google edits become Notion schedule changes before the resulting current Notion task data is projected back into Calendar. D1 is not a task cache or an alternative source of tracker data. A GitHub event says only why work should begin; it does not choose a different kind of synchronisation.

## Configuration

Install the package from this repository:

```bash
python -m pip install .
```

For local development:

```bash
python -m pip install -e .
```

The package installs the `ntt` and `notion-task-tracker` commands. `python -m notion_task_tracker` is also supported.

### Initialise Notion

Create one ordinary parent page and one task database in Notion. Connect the Notion integration to both. The task database must use this schema:

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
| `Start` | Date | Optional scheduled start |
| `End` | Date | Derived by NTT |
| `Duration` | Number | Optional independent duration estimate |
| `Duration unit` | Select | `Hours`, `Days`, `Weeks` |
| `External coordination` | Select | `No`, `Yes` |
| `Uncertainty` | Select | `Low`, `High` |
| `Friction` | Select | `None`, `Insufficiently decomposed`, `Charged`, `Stale` |

`Duration` and `Duration unit` are set together. They may exist without `Start`. Timed starts use hours; date-only starts use whole days or weeks. When a task has a complete schedule, NTT derives `End` as `Start + Duration`. Clearing either input clears `End` without clearing the other input.

Set `NOTION_API_KEY`, then initialise the tracker:

```bash
ntt --init \
  --display-name "Example" \
  --ticket-prefix EXAMPLE \
  --parent-page-url "https://www.notion.so/..." \
  --task-database-url "https://www.notion.so/..."
```

Initialisation validates the database, creates three managed child pages and writes their returned URLs to the configuration:

```text
Tracker parent page
├── Example's ongoing tasks
├── Example's completed tasks
└── Example's tasks in execution order
```

The default configuration locations are:

- Linux: `$XDG_CONFIG_HOME/notion-task-tracker/config.toml`, or `~/.config/notion-task-tracker/config.toml`
- macOS: `~/Library/Application Support/notion-task-tracker/config.toml`
- Windows: the application-data directory returned by `platformdirs`

Use `NTT_CONFIG_PATH` or `--config-path` to select another file. Keep credentials in environment variables or a secret store.

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

[calendar]
calendar_id = "primary"
timezone_name = "Europe/London"
colour_id = "8"
```

Calendar synchronisation also requires:

```text
GOOGLE_CALENDAR_CLIENT_ID
GOOGLE_CALENDAR_CLIENT_SECRET
GOOGLE_CALENDAR_REFRESH_TOKEN
NTT_GOOGLE_CALENDAR_STATE_API_TOKEN
NTT_GOOGLE_CALENDAR_STATE_API_URL
```

Obtain the Google refresh token through offline OAuth consent with `https://www.googleapis.com/auth/calendar.events`. NTT renews short-lived access tokens automatically.

Every command writes one JSON execution summary. It defaults to `/tmp/notion_task_refreshed_result.json`; use `--output-path` for another output file. This summary is an output artefact, not input to a later command.

Install the bundled agent skill with:

```bash
ntt --install-skill
```

## One current Notion load per command

Every command that works with tasks follows the same opening:

1. Resolve the configured database and managed pages.
2. Query the task database once.
3. Parse and validate one in-memory `TaskTree`.
4. Derive narrow repairs for stale task titles or derived end values.
5. Perform the requested work against that same tree.
6. Write the execution summary and discard the tree.

No command depends on a previous command’s JSON output. If current Notion rows contain an invalid identity, relationship or schedule, construction fails instead of continuing from older data. Commands may apply the narrow canonical repairs discovered during their load, including commands that otherwise only read task pages.

## Ordinary commands

### Read and reconcile

Read one task summary:

```bash
ntt --read --ticket-number 67
```

Read its complete page content:

```bash
ntt --read-all --ticket-number 67
```

Mark a task active and return its summary:

```bash
ntt --work --ticket-number 67
```

Reconcile canonical task properties and all managed pages:

```bash
ntt --refresh-notion-task-tracker
```

### Create tasks

Create a top-level task:

```bash
ntt --parent --title "Measure activation mismatch" --priority P1
```

Create a child beneath task 67:

```bash
ntt --child \
  --parent-ticket-number 67 \
  --title "Add explicit command-line actions" \
  --priority P1
```

Create a peer of task 67:

```bash
ntt --sibling \
  --sibling-ticket-number 67 \
  --title "Document explicit command-line actions" \
  --priority P2
```

Notion assigns each new task’s numeric identity. A child inherits the source task’s dependencies and dependants, while the source becomes a parent container and loses its own dependency relations. A sibling inherits the source task’s dependency relations and parent.

`--content-path` may supply the initial timeline entry:

```json
{
  "title": "Started activation measurement",
  "blocks": [
    {
      "type": "paragraph",
      "text": "Measure the exported model before changing conversion settings."
    }
  ]
}
```

### Change tasks

Common mutations are explicit:

```bash
ntt --set-dependencies --ticket-number 67 --dependency-ticket-number 12
ntt --set-dependants --ticket-number 67 --dependant-ticket-number 80
ntt --set-deadline --ticket-number 67 --deadline 2026-08-03
ntt --clear-deadline --ticket-number 67
ntt --set-start --ticket-number 67 --start "2026-08-03T10:00"
ntt --clear-start --ticket-number 67
ntt --set-duration --ticket-number 67 --duration 2.5 --duration-unit Hours
ntt --clear-duration --ticket-number 67
ntt --set-external-coordination --ticket-number 67 --external-coordination Yes
ntt --set-uncertainty --ticket-number 67 --uncertainty High
ntt --set-friction --ticket-number 67 --friction Charged
ntt --reparent --ticket-number 67 --parent-ticket-number 42
```

Append a dated timeline toggle:

```bash
ntt --log --ticket-number 67 --content-path /tmp/log.json
```

Move an identified timeline entry:

```bash
ntt \
  --move-logs \
  --ticket-number 67 \
  --destination-ticket-number 68 \
  --log-id EXAMPLE-LOG-55d04742-f584-4b28-b47d-e383f87406c0
```

The move copies and verifies the complete toggle at the destination before removing and verifying the source. Without `--log-id`, a source containing anything other than exactly one movable entry produces candidates and performs no writes.

### Complete, cancel and delete tasks

```bash
ntt --complete --ticket-number 67 --content-path /tmp/complete.json
ntt --complete-with-all-children --ticket-number 67 --content-path /tmp/complete.json
ntt --cancel --ticket-number 67 --content-path /tmp/cancel.json
ntt --delete --ticket-number 67
```

Completion and cancellation update status, append the supplied timeline entry and reconcile affected managed pages. Recursive completion applies to every unfinished task in the selected subtree. Deletion moves the Notion database page to trash, promotes its children to its parent and removes the deleted task from dependency relationships.

## Managed-page reconciliation

The ongoing and completed pages are derived indexes. The execution-order page is a linked database view of active leaf tasks whose dependencies are complete.

For each managed page, NTT renders the desired current output, reads the existing page and compares the two. It writes only a page that is genuinely stale. Re-running reconciliation without changes therefore produces no managed-page writes.

Task timeline bodies remain user-owned. Timeline commands make targeted changes around the `Timeline log` heading and dated toggles; managed-page reconciliation does not replace task bodies.

## Two-way Calendar lifecycle

A task is eligible for Calendar when it is active, has no children and has a complete start and duration. For example:

```text
Notion task:  [EXAMPLE-42] Pay council tax
Start:        2026-08-03 10:00
Duration:     1 hour

Google event: [NTT] Pay council tax
Start:        2026-08-03 10:00
End:          2026-08-03 11:00
```

Run the complete lifecycle with:

```bash
ntt \
  --synchronise-notion-task-tracker-with-google-calendar \
  --tracker-user example
```

The command performs one ordered story:

```text
resolve resources
→ load and validate Notion once
→ execute canonical Notion repairs
→ read the D1 cursor and event ledger
→ fetch outstanding Google changes
→ apply owned Google changes to Notion and the same TaskTree
→ reconcile affected managed Notion pages
→ project the resulting TaskTree into Google
→ update D1 event identity and deletion provenance
→ advance the cursor
→ emit one summary
```

“Two-way” does not mean simultaneous conflict resolution. Outstanding Google changes are applied first. The resulting in-memory tree, including those changes, is then projected into Google:

1. A Notion schedule change creates or updates its Google event.
2. Moving or resizing a uniquely owned Google event updates the Notion start and duration.
3. Deleting a uniquely owned Google event clears the Notion schedule.
4. Completing, cancelling, unscheduling or parenting a task removes an event that is no longer eligible.

NTT identifies owned events through private Google extended properties containing the configured ticket prefix and full task identity. Synced events have an `[NTT]` title and remain transparent so meetings may overlap them. Foreign, malformed and ambiguously owned events remain untouched.

## D1’s narrow Calendar role

D1 stores only the protocol facts required to process Google changes safely:

- The last completely applied Google change cursor.
- The unique Google event mapped to each tracker task.
- Whether NTT deleted an event and is awaiting Google’s cancellation record.
- Temporary Google notification-channel records.

When NTT deletes an event, it records deletion provenance before issuing the deletion. Google may later return only the cancelled event identity. The provenance distinguishes NTT’s own deletion from a person deleting an active owned event, preventing an NTT-originated deletion from clearing the Notion schedule.

D1 contains no task snapshot, hierarchy, status, priority, schedule or managed-page content.

## GitHub wake-up reasons

`.github/workflows/refresh-notion-task-tracker.yml` accepts three wake-up routes:

1. A Notion notification dispatch named `refresh-notion-task-tracker`.
2. A Google notification dispatch named `apply-google-calendar-changes-to-notion-task-tracker`.
3. A manual workflow dispatch.

All three invoke the same `--synchronise-notion-task-tracker-with-google-calendar` command in the same per-user concurrency group. The event name remains visible as the wake-up reason, but it does not select narrower work. Dispatch payloads contain only `tracker_user`; they do not carry Calendar progress.

Each tracker user is one GitHub environment. It supplies:

- Secret `NTT_CONFIG_TOML`
- Secret `NOTION_API_KEY`
- Secrets `GOOGLE_CALENDAR_CLIENT_ID`, `GOOGLE_CALENDAR_CLIENT_SECRET` and `GOOGLE_CALENDAR_REFRESH_TOKEN`
- Secret `NTT_GOOGLE_CALENDAR_STATE_API_TOKEN`
- Variable `NTT_GOOGLE_CALENDAR_NOTIFICATION_URL`
- Variable `NTT_GOOGLE_CALENDAR_STATE_API_URL`

Manual synchronisation asks for the environment name as `tracker_user`. A Notion wake-up uses:

```json
{
  "event_type": "refresh-notion-task-tracker",
  "client_payload": {
    "tracker_user": "example"
  }
}
```

Google uses `apply-google-calendar-changes-to-notion-task-tracker` with the same identity-only payload.

The separate notification-channel maintenance workflow runs:

```bash
ntt \
  --maintain-google-calendar-notification-channel \
  --tracker-user example \
  --calendar-notification-url https://<worker>/google-calendar-notifications
```

Google notification channels expire and cannot be extended. Maintenance creates a replacement before expiry. If the old channel already expired, maintenance renews it and wakes the ordinary complete lifecycle. The current scheduled workflow is deliberately configured for the `al0vya` environment.

## Worker deployment

`cloudflare_worker/` authenticates Notion and Google webhook requests, dispatches GitHub wake-ups and exposes the authenticated D1 Calendar protocol API.

Inspect and run the package’s pinned scripts:

```bash
cd cloudflare_worker
npm ci
npm test
npm run typecheck
```

Configure Worker secrets:

```bash
cd cloudflare_worker
npx wrangler secret put GITHUB_REPOSITORY_DISPATCH_TOKEN
npx wrangler secret put NOTION_WEBHOOK_SECRET
npx wrangler secret put NTT_GOOGLE_CALENDAR_STATE_API_TOKEN
```

Apply D1 migrations and deploy:

```bash
cd cloudflare_worker
npx wrangler d1 migrations apply GOOGLE_CALENDAR_STATE_DATABASE --remote
npm run deploy
```

The deployed endpoints used by GitHub are:

```text
NTT_GOOGLE_CALENDAR_NOTIFICATION_URL=https://<worker>/google-calendar-notifications
NTT_GOOGLE_CALENDAR_STATE_API_URL=https://<worker>/google-calendar
```

Configure Notion’s `Send webhook` action to send `POST /notion-task-tracker-changes` with `notion_webhook_secret` and `tracker_user` headers. The Worker rejects alternate body fields, query parameters and aliases.

## Recovery and failure behaviour

- If Google expires the cursor, NTT fetches current Google events and rebuilds the D1 event ledger from that current snapshot before continuing.
- Foreign, malformed and ambiguously owned Google events remain untouched.
- Tracker-originated deletion provenance prevents Google’s cancellation record from reverse-unscheduling a task.
- The cursor advances only after all required Notion, Google and D1 operations succeed. A failed operation leaves it unchanged so the outstanding changes can be retried.
- A run with no changes performs no task or managed-page writes.
- GitHub serialises each user’s lifecycle so overlapping wake-ups read the latest cursor when they begin.
- The Worker also wakes synchronisation daily at `00:00 UTC`, preventing a missed notification from hiding changes permanently.

## Package ownership

The behaviour is divided at these boundaries:

- `notion_task_tracker/run_notion_task_tracker.py` parses actions and runs one task-bearing command from current Notion data.
- `notion_task_tracker/notion_operations/load_current_task_tree_from_notion.py` performs the single database query and validates the in-memory task tree.
- `notion_task_tracker/notion_operations/` resolves configured resources, plans narrow Notion writes and reconciles managed pages.
- `notion_task_tracker/tasks/` owns task, schedule, hierarchy and rendering rules.
- `notion_task_tracker/google_calendar_sync/synchronise_notion_task_tracker_with_google_calendar.py` owns the complete two-way lifecycle.
- `cloudflare_worker/` owns authenticated wake-ups and the narrow D1 Calendar protocol boundary.

## Tests

Run the complete Python suite:

```bash
python -m pytest
```

Run Worker verification:

```bash
cd cloudflare_worker
npm test
npm run typecheck
```
