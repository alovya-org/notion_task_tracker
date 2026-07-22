export interface GoogleCalendarNotificationChannelState {
  channel_id: string;
  resource_id: string;
  channel_token_sha256: string;
  tracker_user: string;
  calendar_id: string;
  expiration: number;
  sync_token: string;
}

export interface GoogleCalendarChangeCursorState {
  tracker_user: string;
  sync_token: string;
}

export interface GoogleCalendarNotificationChannelRegistration {
  channelId: string;
  trackerUser: string;
  calendarId: string;
  resourceId: string;
  channelToken: string;
  syncToken: string;
  expiresAt: number;
}

export async function listGoogleCalendarChangeCursors(
  database: D1Database,
): Promise<GoogleCalendarChangeCursorState[]> {
  const cursors = await database.prepare(
    `SELECT tracker_user, sync_token
     FROM calendar_sync_cursors
     ORDER BY tracker_user, calendar_id`,
  ).all<GoogleCalendarChangeCursorState>();
  return cursors.results;
}

export async function saveGoogleCalendarNotificationChannel(
  database: D1Database,
  registration: GoogleCalendarNotificationChannelRegistration,
): Promise<void> {
  const recordedAt = new Date().toISOString();
  await database.batch([
    database.prepare(
      `INSERT INTO calendar_sync_cursors
         (tracker_user, calendar_id, sync_token, revision, updated_at)
       VALUES (?, ?, ?, 0, ?)
       ON CONFLICT (tracker_user, calendar_id) DO NOTHING`,
    ).bind(
      registration.trackerUser,
      registration.calendarId,
      registration.syncToken,
      recordedAt,
    ),
    database.prepare(
      `INSERT INTO calendar_channels
         (channel_id, tracker_user, calendar_id, resource_id, channel_token_sha256, expires_at, created_at)
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
            cursors.sync_token
     FROM calendar_channels AS channels
     JOIN calendar_sync_cursors AS cursors
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
            channels.channel_token_sha256,
            channels.tracker_user,
            channels.calendar_id,
            channels.expires_at AS expiration,
            cursors.sync_token
     FROM calendar_channels AS channels
     JOIN calendar_sync_cursors AS cursors
       ON cursors.tracker_user = channels.tracker_user
      AND cursors.calendar_id = channels.calendar_id
     WHERE channels.channel_id = ?`,
  ).bind(channelId).first<GoogleCalendarNotificationChannelState>();
}

export async function advanceGoogleCalendarChangeCursorInDatabase(
  database: D1Database,
  trackerUser: string,
  calendarId: string,
  previousSyncToken: string,
  nextSyncToken: string,
): Promise<boolean> {
  const updateResult = await database.prepare(
    `UPDATE calendar_sync_cursors
     SET sync_token = ?, revision = revision + 1, updated_at = ?
     WHERE tracker_user = ? AND calendar_id = ? AND sync_token = ?`,
  )
    .bind(nextSyncToken, new Date().toISOString(), trackerUser, calendarId, previousSyncToken)
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
