CREATE TABLE google_calendar_change_cursors (
    tracker_user TEXT NOT NULL,
    calendar_id TEXT NOT NULL,
    google_change_cursor TEXT NOT NULL,
    revision INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tracker_user, calendar_id)
);

CREATE TABLE google_calendar_notification_channels (
    channel_id TEXT PRIMARY KEY,
    tracker_user TEXT NOT NULL,
    calendar_id TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    notification_channel_token_sha256 TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (tracker_user, calendar_id)
        REFERENCES google_calendar_change_cursors (tracker_user, calendar_id)
);

CREATE INDEX google_calendar_notification_channels_by_tracker_calendar
ON google_calendar_notification_channels (tracker_user, calendar_id);

CREATE INDEX google_calendar_notification_channels_by_expiration
ON google_calendar_notification_channels (expires_at);
