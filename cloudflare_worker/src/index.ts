import { createJsonResponse } from "./create_http_response";
import { requireEnvironmentVariables, WorkerEnvironment } from "./environment";
import {
  createGitHubDispatchPayload,
  createGitHubFailureResponse,
  sendGitHubRepositoryDispatch,
} from "./github/send_github_repository_dispatch";
import { dispatchNotionTaskChangeToGitHub } from "./notion/dispatch_notion_task_change_to_github";

interface CalendarChannelState {
  channel_id: string;
  resource_id: string;
  channel_token_sha256: string;
  tracker_user: string;
  calendar_id: string;
  expiration: number;
  sync_token: string;
}

interface CalendarSyncCursorState {
  tracker_user: string;
  sync_token: string;
}

const GOOGLE_CALENDAR_NOTIFICATION_PATH = "/google-calendar-notifications";
const CALENDAR_CHANNEL_REGISTRATION_PATH = "/calendar-sync-state/channels";
const CALENDAR_CURSOR_ADVANCEMENT_PATH = "/calendar-sync-state/cursors";
const NOTION_TASK_CHANGES_PATH = "/notion-task-changes";

export default {
  async fetch(request: Request, environment: WorkerEnvironment): Promise<Response> {
    const requestPath = new URL(request.url).pathname;
    if (requestPath === GOOGLE_CALENDAR_NOTIFICATION_PATH) {
      return await _dispatchGoogleCalendarChangeToGitHub(request, environment);
    }
    if (requestPath === CALENDAR_CHANNEL_REGISTRATION_PATH) {
      return await _registerGoogleCalendarChannel(request, environment);
    }
    if (requestPath === CALENDAR_CURSOR_ADVANCEMENT_PATH) {
      return await _advanceGoogleCalendarSyncCursor(request, environment);
    }
    if (requestPath === NOTION_TASK_CHANGES_PATH) {
      return await dispatchNotionTaskChangeToGitHub(request, environment);
    }
    return createJsonResponse({ error: "Not found." }, 404);
  },

  async scheduled(
    _controller: ScheduledController,
    environment: WorkerEnvironment,
  ): Promise<void> {
    await _dispatchDailyCalendarRecoveryToGitHub(environment);
  },
};

async function _dispatchDailyCalendarRecoveryToGitHub(
  environment: WorkerEnvironment,
): Promise<void> {
  _assertGoogleCalendarEnvironmentIsComplete(environment);
  const cursors = await environment.CALENDAR_SYNC_STATE.prepare(
    `SELECT tracker_user, sync_token
     FROM calendar_sync_cursors
     ORDER BY tracker_user, calendar_id`,
  ).all<CalendarSyncCursorState>();

  for (const cursor of cursors.results) {
    const dispatchPayload = createGitHubDispatchPayload(
      environment.GITHUB_CALENDAR_DISPATCH_EVENT_TYPE,
      cursor.tracker_user,
      undefined,
      cursor.sync_token,
    );
    const githubResponse = await sendGitHubRepositoryDispatch(
      environment.GITHUB_OWNER,
      environment.GITHUB_REPOSITORY,
      environment.GITHUB_API_VERSION,
      environment.GITHUB_DISPATCH_TOKEN,
      dispatchPayload,
    );
    if (!githubResponse.ok) {
      throw new Error(
        `Daily Calendar recovery dispatch failed for ${cursor.tracker_user}: ${githubResponse.status}`,
      );
    }
  }
}

async function _registerGoogleCalendarChannel(
  request: Request,
  environment: WorkerEnvironment,
): Promise<Response> {
  if (request.method === "GET") {
    return await _readLatestGoogleCalendarChannel(request, environment);
  }
  if (request.method !== "POST") {
      return createJsonResponse({ error: "Use GET or POST." }, 405, { Allow: "GET, POST" });
  }
  const authorisationFailure = _authoriseCalendarSyncStateAdministration(request, environment);
  if (authorisationFailure !== null) {
    return authorisationFailure;
  }

  const channel = await request.json<Record<string, unknown>>();
  const channelId = _readRequiredString(channel, "channel_id");
  const trackerUser = _readRequiredString(channel, "tracker_user");
  const calendarId = _readRequiredString(channel, "calendar_id");
  const resourceId = _readRequiredString(channel, "resource_id");
  const channelToken = _readRequiredString(channel, "channel_token");
  const syncToken = _readRequiredString(channel, "sync_token");
  const expiresAt = _readRequiredNumber(channel, "expires_at");
  const recordedAt = new Date().toISOString();

  await environment.CALENDAR_SYNC_STATE.batch([
    environment.CALENDAR_SYNC_STATE.prepare(
      `INSERT INTO calendar_sync_cursors
         (tracker_user, calendar_id, sync_token, revision, updated_at)
       VALUES (?, ?, ?, 0, ?)
       ON CONFLICT (tracker_user, calendar_id) DO NOTHING`,
    ).bind(trackerUser, calendarId, syncToken, recordedAt),
    environment.CALENDAR_SYNC_STATE.prepare(
      `INSERT INTO calendar_channels
         (channel_id, tracker_user, calendar_id, resource_id, channel_token_sha256, expires_at, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)`,
    ).bind(
      channelId,
      trackerUser,
      calendarId,
      resourceId,
      await _sha256Hex(channelToken),
      expiresAt,
      recordedAt,
    ),
  ]);

  return createJsonResponse({ registered: true, channel_id: channelId }, 201);
}

async function _readLatestGoogleCalendarChannel(
  request: Request,
  environment: WorkerEnvironment,
): Promise<Response> {
  const authorisationFailure = _authoriseCalendarSyncStateAdministration(request, environment);
  if (authorisationFailure !== null) {
    return authorisationFailure;
  }
  const query = new URL(request.url).searchParams;
  const trackerUser = query.get("tracker_user");
  const calendarId = query.get("calendar_id");
  if (!trackerUser || !calendarId) {
    return createJsonResponse({ error: "tracker_user and calendar_id are required." }, 400);
  }
  const channel = await environment.CALENDAR_SYNC_STATE.prepare(
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
  if (channel === null) {
    return new Response(null, { status: 204 });
  }
  return createJsonResponse(channel, 200);
}

async function _advanceGoogleCalendarSyncCursor(
  request: Request,
  environment: WorkerEnvironment,
): Promise<Response> {
  if (request.method !== "PATCH") {
    return createJsonResponse({ error: "Use PATCH." }, 405, { Allow: "PATCH" });
  }
  const authorisationFailure = _authoriseCalendarSyncStateAdministration(request, environment);
  if (authorisationFailure !== null) {
    return authorisationFailure;
  }

  const cursorChange = await request.json<Record<string, unknown>>();
  const trackerUser = _readRequiredString(cursorChange, "tracker_user");
  const calendarId = _readRequiredString(cursorChange, "calendar_id");
  const previousSyncToken = _readRequiredString(cursorChange, "previous_sync_token");
  const nextSyncToken = _readRequiredString(cursorChange, "next_sync_token");
  const updateResult = await environment.CALENDAR_SYNC_STATE.prepare(
    `UPDATE calendar_sync_cursors
     SET sync_token = ?, revision = revision + 1, updated_at = ?
     WHERE tracker_user = ? AND calendar_id = ? AND sync_token = ?`,
  )
    .bind(nextSyncToken, new Date().toISOString(), trackerUser, calendarId, previousSyncToken)
    .run();

  if (updateResult.meta.changes !== 1) {
    return createJsonResponse({ error: "Calendar sync cursor has already advanced." }, 409);
  }
  return createJsonResponse({ advanced: true }, 200);
}

async function _dispatchGoogleCalendarChangeToGitHub(
  request: Request,
  environment: WorkerEnvironment,
): Promise<Response> {
  if (request.method !== "POST") {
    return createJsonResponse({ error: "Use POST." }, 405, { Allow: "POST" });
  }

  _assertGoogleCalendarEnvironmentIsComplete(environment);
  const requiredHeaderNames = [
    "X-Goog-Channel-ID",
    "X-Goog-Channel-Token",
    "X-Goog-Resource-ID",
    "X-Goog-Resource-State",
  ];
  const missingHeaderName = requiredHeaderNames.find(
    (headerName) => !request.headers.get(headerName),
  );
  if (missingHeaderName !== undefined) {
    return createJsonResponse(
      { error: `Missing Google Calendar notification header: ${missingHeaderName}` },
      400,
    );
  }
  const channelId = request.headers.get("X-Goog-Channel-ID")!;
  const channelToken = request.headers.get("X-Goog-Channel-Token")!;
  const resourceId = request.headers.get("X-Goog-Resource-ID")!;
  const resourceState = request.headers.get("X-Goog-Resource-State")!;
  const channelState = await environment.CALENDAR_SYNC_STATE
    .prepare(
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
    )
    .bind(channelId)
    .first<CalendarChannelState>();
  if (channelState === null) {
    return createJsonResponse({ error: "Unknown Google Calendar channel." }, 401);
  }
  const suppliedChannelTokenSha256 = await _sha256Hex(channelToken);
  if (
    channelState.channel_token_sha256 !== suppliedChannelTokenSha256
    || channelState.resource_id !== resourceId
  ) {
    return createJsonResponse({ error: "Google Calendar channel identity rejected." }, 401);
  }
  if (resourceState === "sync") {
    return new Response(null, { status: 204 });
  }
  if (!new Set(["exists", "not_exists"]).has(resourceState)) {
    return createJsonResponse({ error: "Unsupported Google Calendar resource state." }, 400);
  }

  const dispatchPayload = createGitHubDispatchPayload(
    environment.GITHUB_CALENDAR_DISPATCH_EVENT_TYPE,
    channelState.tracker_user,
    channelId,
    channelState.sync_token,
  );
  const githubResponse = await sendGitHubRepositoryDispatch(
    environment.GITHUB_OWNER,
    environment.GITHUB_REPOSITORY,
    environment.GITHUB_API_VERSION,
    environment.GITHUB_DISPATCH_TOKEN,
    dispatchPayload,
  );
  if (!githubResponse.ok) {
    return await createGitHubFailureResponse(githubResponse);
  }
  return createJsonResponse({
    dispatched: true,
    event_type: dispatchPayload.event_type,
    tracker_user: channelState.tracker_user,
    channel_id: channelId,
  }, 202);
}

async function _sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function _assertGoogleCalendarEnvironmentIsComplete(environment: WorkerEnvironment): void {
  requireEnvironmentVariables(environment, [
    "GITHUB_OWNER",
    "GITHUB_REPOSITORY",
    "GITHUB_API_VERSION",
    "GITHUB_CALENDAR_DISPATCH_EVENT_TYPE",
    "GITHUB_DISPATCH_TOKEN",
  ]);
  if (!environment.CALENDAR_SYNC_STATE) {
    throw new Error("Missing Worker environment binding: CALENDAR_SYNC_STATE");
  }
}

function _authoriseCalendarSyncStateAdministration(
  request: Request,
  environment: WorkerEnvironment,
): Response | null {
  _assertGoogleCalendarEnvironmentIsComplete(environment);
  if (!environment.CALENDAR_SYNC_ADMIN_TOKEN) {
    throw new Error("Missing Worker environment variable: CALENDAR_SYNC_ADMIN_TOKEN");
  }
  if (request.headers.get("Authorization") !== `Bearer ${environment.CALENDAR_SYNC_ADMIN_TOKEN}`) {
    return createJsonResponse({ error: "Calendar sync state administration rejected." }, 401);
  }
  return null;
}

function _readRequiredString(body: Record<string, unknown>, fieldName: string): string {
  const value = body[fieldName];
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${fieldName} must be a non-empty string`);
  }
  return value;
}

function _readRequiredNumber(body: Record<string, unknown>, fieldName: string): number {
  const value = body[fieldName];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${fieldName} must be a finite number`);
  }
  return value;
}
