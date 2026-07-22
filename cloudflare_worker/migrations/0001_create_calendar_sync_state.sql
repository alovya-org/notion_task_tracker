CREATE TABLE calendar_sync_cursors (
    tracker_user TEXT NOT NULL,
    calendar_id TEXT NOT NULL,
    sync_token TEXT NOT NULL,
    revision INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tracker_user, calendar_id)
);

CREATE TABLE calendar_channels (
    channel_id TEXT PRIMARY KEY,
    tracker_user TEXT NOT NULL,
    calendar_id TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    channel_token_sha256 TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (tracker_user, calendar_id)
        REFERENCES calendar_sync_cursors (tracker_user, calendar_id)
);

CREATE INDEX calendar_channels_by_tracker_calendar
ON calendar_channels (tracker_user, calendar_id);

CREATE INDEX calendar_channels_by_expiration
ON calendar_channels (expires_at);
