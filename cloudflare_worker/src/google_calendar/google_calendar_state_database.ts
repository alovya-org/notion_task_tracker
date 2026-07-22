export interface GoogleCalendarNotificationChannelState {
  channel_id: string;
  resource_id: string;
  notification_channel_token_sha256: string;
  tracker_user: string;
  calendar_id: string;
  expiration: number;
  google_change_cursor: string;
}

export interface GoogleCalendarChangeCursorState {
  tracker_user: string;
  google_change_cursor: string;
}

export interface GoogleCalendarEventLedgerEntry {
  google_event_id: string;
  ntt_task_id: string;
  lifecycle_state: "active" | "deleted_by_ntt";
}

export interface GoogleCalendarNotificationChannelRegistration {
  channelId: string;
  trackerUser: string;
  calendarId: string;
  resourceId: string;
  channelToken: string;
  googleChangeCursor: string;
  expiresAt: number;
}

export async function listGoogleCalendarChangeCursors(
  database: D1Database,
): Promise<GoogleCalendarChangeCursorState[]> {
  const cursors = await database.prepare(
    `SELECT tracker_user, google_change_cursor
     FROM google_calendar_change_cursors
     ORDER BY tracker_user, calendar_id`,
  ).all<GoogleCalendarChangeCursorState>();
  return cursors.results;
}

export async function readGoogleCalendarChangeCursor(
  database: D1Database,
  trackerUser: string,
  calendarId: string,
): Promise<string | null> {
  const cursor = await database.prepare(
    `SELECT google_change_cursor
     FROM google_calendar_change_cursors
     WHERE tracker_user = ? AND calendar_id = ?`,
  ).bind(trackerUser, calendarId).first<{ google_change_cursor: string }>();
  return cursor?.google_change_cursor ?? null;
}

export async function listGoogleCalendarEventLedgerEntries(
  database: D1Database,
  trackerUser: string,
  calendarId: string,
): Promise<GoogleCalendarEventLedgerEntry[]> {
  const entries = await database.prepare(
    `SELECT google_event_id, ntt_task_id, lifecycle_state
     FROM google_calendar_event_ledger
     WHERE tracker_user = ? AND calendar_id = ?
     ORDER BY google_event_id`,
  ).bind(trackerUser, calendarId).all<GoogleCalendarEventLedgerEntry>();
  return entries.results;
}

export async function saveActiveGoogleCalendarEventMapping(
  database: D1Database,
  trackerUser: string,
  calendarId: string,
  googleEventId: string,
  nttTaskId: string,
): Promise<void> {
  await database.prepare(
    `INSERT INTO google_calendar_event_ledger
       (tracker_user, calendar_id, google_event_id, ntt_task_id, lifecycle_state, updated_at)
     VALUES (?, ?, ?, ?, 'active', ?)
     ON CONFLICT (tracker_user, calendar_id, google_event_id) DO UPDATE SET
       ntt_task_id = excluded.ntt_task_id,
       lifecycle_state = 'active',
       updated_at = excluded.updated_at`,
  ).bind(
    trackerUser,
    calendarId,
    googleEventId,
    nttTaskId,
    new Date().toISOString(),
  ).run();
}

export async function markGoogleCalendarEventDeletedByNtt(
  database: D1Database,
  trackerUser: string,
  calendarId: string,
  googleEventId: string,
  nttTaskId: string,
): Promise<boolean> {
  const updateResult = await database.prepare(
    `UPDATE google_calendar_event_ledger
     SET lifecycle_state = 'deleted_by_ntt', updated_at = ?
     WHERE tracker_user = ?
       AND calendar_id = ?
       AND google_event_id = ?
       AND ntt_task_id = ?
       AND lifecycle_state IN ('active', 'deleted_by_ntt')`,
  ).bind(
    new Date().toISOString(),
    trackerUser,
    calendarId,
    googleEventId,
    nttTaskId,
  ).run();
  return updateResult.meta.changes === 1;
}

export async function deleteGoogleCalendarEventMapping(
  database: D1Database,
  trackerUser: string,
  calendarId: string,
  googleEventId: string,
  nttTaskId: string,
): Promise<boolean> {
  const deleteResult = await database.prepare(
    `DELETE FROM google_calendar_event_ledger
     WHERE tracker_user = ?
       AND calendar_id = ?
       AND google_event_id = ?
       AND ntt_task_id = ?`,
  ).bind(trackerUser, calendarId, googleEventId, nttTaskId).run();
  return deleteResult.meta.changes === 1;
}

export async function replaceGoogleCalendarEventLedgerFromSnapshot(
  database: D1Database,
  trackerUser: string,
  calendarId: string,
  activeEvents: Array<{ googleEventId: string; nttTaskId: string }>,
): Promise<void> {
  const recordedAt = new Date().toISOString();
  await database.batch([
    database.prepare(
      `DELETE FROM google_calendar_event_ledger
       WHERE tracker_user = ? AND calendar_id = ?`,
    ).bind(trackerUser, calendarId),
    ...activeEvents.map((event) => database.prepare(
      `INSERT INTO google_calendar_event_ledger
         (tracker_user, calendar_id, google_event_id, ntt_task_id, lifecycle_state, updated_at)
       VALUES (?, ?, ?, ?, 'active', ?)`,
    ).bind(
      trackerUser,
      calendarId,
      event.googleEventId,
      event.nttTaskId,
      recordedAt,
    )),
  ]);
}

export async function saveGoogleCalendarNotificationChannel(
  database: D1Database,
  registration: GoogleCalendarNotificationChannelRegistration,
): Promise<void> {
  const recordedAt = new Date().toISOString();
  await database.batch([
    database.prepare(
      `INSERT INTO google_calendar_change_cursors
         (tracker_user, calendar_id, google_change_cursor, revision, updated_at)
       VALUES (?, ?, ?, 0, ?)
       ON CONFLICT (tracker_user, calendar_id) DO NOTHING`,
    ).bind(
      registration.trackerUser,
      registration.calendarId,
      registration.googleChangeCursor,
      recordedAt,
    ),
    database.prepare(
      `INSERT INTO google_calendar_notification_channels
         (channel_id, tracker_user, calendar_id, resource_id, notification_channel_token_sha256, expires_at, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
    ).bind(
      registration.channelId,
      registration.trackerUser,
      registration.calendarId,
      registration.resourceId,
      await hashGoogleCalendarNotificationChannelToken(registration.channelToken),
      registration.expiresAt,
      recordedAt,
    ),
  ]);
}

export async function findLatestGoogleCalendarNotificationChannel(
  database: D1Database,
  trackerUser: string,
  calendarId: string,
): Promise<Record<string, unknown> | null> {
  return await database.prepare(
    `SELECT channels.channel_id,
            channels.resource_id,
            channels.expires_at,
            cursors.google_change_cursor
     FROM google_calendar_notification_channels AS channels
     JOIN google_calendar_change_cursors AS cursors
       ON cursors.tracker_user = channels.tracker_user
      AND cursors.calendar_id = channels.calendar_id
     WHERE channels.tracker_user = ? AND channels.calendar_id = ?
     ORDER BY channels.expires_at DESC
     LIMIT 1`,
  ).bind(trackerUser, calendarId).first();
}

export async function findGoogleCalendarNotificationChannelById(
  database: D1Database,
  channelId: string,
): Promise<GoogleCalendarNotificationChannelState | null> {
  return await database.prepare(
    `SELECT channels.channel_id,
            channels.resource_id,
            channels.notification_channel_token_sha256,
            channels.tracker_user,
            channels.calendar_id,
            channels.expires_at AS expiration,
            cursors.google_change_cursor
     FROM google_calendar_notification_channels AS channels
     JOIN google_calendar_change_cursors AS cursors
       ON cursors.tracker_user = channels.tracker_user
      AND cursors.calendar_id = channels.calendar_id
     WHERE channels.channel_id = ?`,
  ).bind(channelId).first<GoogleCalendarNotificationChannelState>();
}

export async function advanceGoogleCalendarChangeCursorInDatabase(
  database: D1Database,
  trackerUser: string,
  calendarId: string,
  previousGoogleChangeCursor: string,
  nextGoogleChangeCursor: string,
): Promise<boolean> {
  const updateResult = await database.prepare(
    `UPDATE google_calendar_change_cursors
     SET google_change_cursor = ?, revision = revision + 1, updated_at = ?
     WHERE tracker_user = ? AND calendar_id = ? AND google_change_cursor = ?`,
  )
    .bind(
      nextGoogleChangeCursor,
      new Date().toISOString(),
      trackerUser,
      calendarId,
      previousGoogleChangeCursor,
    )
    .run();
  return updateResult.meta.changes === 1;
}

export async function hashGoogleCalendarNotificationChannelToken(
  channelToken: string,
): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(channelToken),
  );
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}
