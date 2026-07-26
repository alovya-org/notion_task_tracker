# System design and architecture

This document explains how the Notion Task Tracker (NTT) enforces authority boundaries, executes synchronisation, and maps behaviour to the codebase.

## Authority boundaries

Each system owns a deliberately narrow part of the tracker:

1. **Notion** is the absolute task authority. It owns task identity, title, hierarchy, dependencies, status, priority, schedule, timeline content, and the rendered managed pages. A Notion-only tracker never contacts Google or Cloudflare D1.
2. **Google Calendar** (when configured) owns the current presentation of eligible scheduled tasks. A person may move, resize, or delete an event that is uniquely owned by the tracker. Google edits become Notion schedule changes before the resulting current Notion task data is projected back into Calendar.
3. **Cloudflare D1** (when Calendar is configured) owns the Calendar synchronisation cursor, Google-event-to-task identity, and tracker-originated deletion provenance. It is not a task cache or an alternative source of tracker data.
4. **GitHub Actions** owns wake-ups and serialised execution of the configured synchronisation lifecycle. A GitHub event says only *why* work should begin; it does not choose a different kind of synchronisation.

## The universal synchronisation lifecycle

Every command that works with tasks follows the same opening sequence to ensure it acts on current, valid data:

1. Resolve the configured database and managed pages.
2. Query the task database exactly once.
3. Parse and validate one in-memory task tree.
4. Derive narrow repairs for stale task titles or derived end values.
5. Perform the requested work against that same tree.
6. Write the execution summary and discard the tree.

No command depends on a previous command’s JSON output. If current Notion rows contain an invalid identity, relationship, or schedule, construction fails instead of continuing from older data.

### Calendar opt-in lifecycle

When Calendar is configured, the `--refresh-notion-task-tracker` command continues from the loaded task tree through a two-way Calendar lifecycle:

1. Read the D1 cursor and event ledger.
2. Fetch outstanding Google changes.
3. Apply owned Google changes to Notion and the in-memory task tree.
4. Reconcile affected managed Notion pages.
5. Project the resulting task tree into Google (creating, updating, or deleting events).
6. Update D1 event identity and deletion provenance.
7. Advance the cursor.

“Two-way” does not mean simultaneous conflict resolution. Outstanding Google changes are applied first, and the resulting tree is then projected into Google.

## Behaviour to file mapping

The codebase is divided by behaviour to ensure clear ownership:

- **CLI entrypoint (`notion_task_tracker/run_notion_task_tracker.py`)**: Parses actions, auto-heals the agent skill, and runs one task-bearing command from current Notion data.
- **Lifecycle orchestration (`notion_task_tracker/refresh_notion_task_tracker.py`)**: Owns the universal one-load lifecycle and selects the configured mode (Notion-only or Calendar-enabled).
- **Notion operations (`notion_task_tracker/notion_operations/`)**:
  - `load_current_task_tree_from_notion.py` performs the single database query and validates the in-memory task tree.
  - Other files resolve configured resources, plan narrow Notion writes, and reconcile managed pages.
- **Task domain (`notion_task_tracker/tasks/`)**: Owns task, schedule, hierarchy, and rendering rules.
- **Calendar protocol (`notion_task_tracker/google_calendar_sync/`)**: Continues an already loaded lifecycle through the optional Calendar protocol (`continue_synchronisation_with_google_calendar.py`).
- **Worker deployment (`cloudflare_worker/`)**: Owns authenticated webhook wake-ups (Notion and Google) and exposes the narrow D1 Calendar protocol boundary.

## Recovery and failure behaviour

- **Cursor expiry**: If Google expires the cursor, NTT fetches current Google events and rebuilds the D1 event ledger from that current snapshot before continuing.
- **Foreign events**: Foreign, malformed, and ambiguously owned Google events remain untouched.
- **Deletion provenance**: Tracker-originated deletion provenance in D1 prevents Google’s cancellation record from reverse-unscheduling a task in Notion.
- **Atomic cursor advancement**: The cursor advances only after all required Notion, Google, and D1 operations succeed. A failed operation leaves it unchanged so the outstanding changes can be retried.
- **Serialised execution**: GitHub serialises each user’s lifecycle so overlapping wake-ups read the latest cursor when they begin. The Worker also wakes synchronisation daily at `00:00 UTC`, preventing a missed notification from hiding changes permanently.