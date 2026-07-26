# Notion task tracker

Notion Task Tracker (NTT) is a system for tracking tasks in Notion. It is designed to be used manually by humans or autonomously by AI agents, providing a reliable interface for reading, creating, and updating tasks. Google Calendar synchronisation is an optional addition.

## Installation

We recommend cloning the repository and installing it globally in editable mode using `pipx`. This ensures it is isolated, globally available on your `PATH`, and that the bundled agent skill auto-heals immediately when the source changes:

```bash
git clone https://github.com/alovya/notion_task_tracker.git
cd notion_task_tracker
pipx install -e .
```

This installs the `ntt` command. To update the tracker in the future, simply run `git pull` in the repository directory.

## Configuration

### 1. Prepare Notion
Create one parent page and one task database in Notion. Connect your Notion integration to both. The task database must use this exact schema:

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

### 2. Initialise the tracker
Set your `NOTION_API_KEY` environment variable, then initialise the tracker. This validates the database, creates three managed child pages (ongoing tasks, completed tasks, and execution order), and writes the configuration file:

```bash
ntt --init \
  --display-name "Example" \
  --ticket-prefix EXAMPLE \
  --parent-page-url "https://www.notion.so/..." \
  --task-database-url "https://www.notion.so/..."
```

The configuration is saved to `$XDG_CONFIG_HOME/notion-task-tracker/config.toml` (or `~/.config/notion-task-tracker/config.toml` on Linux). You can override this location using the `NTT_CONFIG_PATH` environment variable or the `--config-path` flag.

To opt in to two-way Google Calendar synchronisation, append calendar details to your `config.toml` and provide the required Google and Cloudflare D1 environment variables (see `DESIGN.md` for architecture details).

## Usage

NTT commands manage the complete lifecycle of a task. Every command outputs a JSON execution summary to `/tmp/notion_task_refreshed_result.json` (override with `--output-path`).

### Creating tasks

Create a top-level task:
```bash
ntt --parent --title "Measure activation mismatch" --priority P1
```

Create a child beneath an existing task. The child inherits the parent's dependencies:
```bash
ntt --child --parent-ticket-number 67 --title "Add explicit command-line actions" --priority P1
```

Create a sibling peer. The sibling inherits the source task's parent and dependencies:
```bash
ntt --sibling --sibling-ticket-number 67 --title "Document explicit command-line actions" --priority P2
```

### Reading and working on tasks

Read a task's summary:
```bash
ntt --read --ticket-number 67
```

Read a task's complete page content:
```bash
ntt --read-all --ticket-number 67
```

Mark a task as active and return its summary:
```bash
ntt --work --ticket-number 67
```

### Updating task properties

Mutate task attributes explicitly:
```bash
ntt --set-dependencies --ticket-number 67 --dependency-ticket-number 12
ntt --set-deadline --ticket-number 67 --deadline 2026-08-03
ntt --set-duration --ticket-number 67 --duration 2.5 --duration-unit Hours
ntt --set-external-coordination --ticket-number 67 --external-coordination Yes
ntt --reparent --ticket-number 67 --parent-ticket-number 42
```
*(Clear attributes using the corresponding `--clear-*` flags, e.g., `--clear-deadline`)*

### Logging progress

Append a dated timeline toggle to a task's page using a JSON content file:
```bash
ntt --log --ticket-number 67 --content-path /tmp/log.json
```

The JSON content file supports `blocks` (preferred) and `lines` (legacy). Here is a complete example showing all available options:

```json
{
  "title": "Investigated activation mismatch",
  "blocks": [
    {
      "type": "paragraph",
      "text": "The exported model shows a discrepancy in the final layer."
    },
    {
      "type": "code",
      "text": "def measure_activation(tensor):\n    return tensor.abs().max()",
      "language": "python"
    }
  ],
  "lines": [
    "Legacy string lines are also supported but blocks are preferred.",
    "Another line of text."
  ]
}
```

Move an identified timeline entry from one task to another:
```bash
ntt --move-logs --ticket-number 67 --destination-ticket-number 68 --log-id EXAMPLE-LOG-55d04742...
```

### Completing and deleting tasks

Complete a task (optionally appending a final timeline entry):
```bash
ntt --complete --ticket-number 67 --content-path /tmp/complete.json
```

Complete a task and all its unfinished children recursively:
```bash
ntt --complete-with-all-children --ticket-number 67
```

Cancel a task:
```bash
ntt --cancel --ticket-number 67
```

Delete a task entirely (moves the Notion page to trash, promotes its children to its parent, and removes it from dependency relationships):
```bash
ntt --delete --ticket-number 67
```

### Reconciling state

Reconcile all canonical task properties and update the managed Notion pages (ongoing, completed, execution order), and sync with Google Calendar if configured:
```bash
ntt --refresh-notion-task-tracker --tracker-user example
```

## Agent skill

The `notion-task-tracker` agent skill is bundled with this package. Every time you invoke `ntt`, it silently checks your agent configuration directories (e.g., `~/.cursor/skills/`) and auto-heals the `SKILL.md` file if it is missing or outdated.

## Running tests

Because `ntt` is installed in an isolated `pipx` environment, you must use the `pytest` binary from that specific environment to run the test suite:

```bash
pipx inject notion-task-tracker pytest pytest-mock pytest-asyncio
~/.local/share/pipx/venvs/notion-task-tracker/bin/pytest tests
```