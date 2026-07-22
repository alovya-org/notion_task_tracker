CREATE TABLE google_calendar_event_ledger (
    tracker_user TEXT NOT NULL,
    calendar_id TEXT NOT NULL,
    google_event_id TEXT NOT NULL,
    ntt_task_id TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL
        CHECK (lifecycle_state IN ('active', 'deleted_by_ntt')),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tracker_user, calendar_id, google_event_id),
    FOREIGN KEY (tracker_user, calendar_id)
        REFERENCES google_calendar_change_cursors (tracker_user, calendar_id)
);

CREATE UNIQUE INDEX google_calendar_event_ledger_active_task
ON google_calendar_event_ledger (tracker_user, calendar_id, ntt_task_id)
WHERE lifecycle_state = 'active';

CREATE INDEX google_calendar_event_ledger_by_task
ON google_calendar_event_ledger (tracker_user, calendar_id, ntt_task_id);
