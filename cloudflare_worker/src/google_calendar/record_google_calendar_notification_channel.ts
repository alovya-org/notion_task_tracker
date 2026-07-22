import { createJsonResponse } from "../create_http_response";
import { WorkerEnvironment } from "../environment";
import { readRequiredNumber, readRequiredString } from "../read_http_request";
import { authenticateGoogleCalendarStateRequest } from "./authenticate_google_calendar_state_request";
import { saveGoogleCalendarNotificationChannel } from "./google_calendar_state_database";

export async function recordGoogleCalendarNotificationChannel(
  request: Request,
  environment: WorkerEnvironment,
): Promise<Response> {
  const authorisationFailure = authenticateGoogleCalendarStateRequest(request, environment);
  if (authorisationFailure !== null) {
    return authorisationFailure;
  }

  const channel = await request.json<Record<string, unknown>>();
  const channelId = readRequiredString(channel, "channel_id");
  await saveGoogleCalendarNotificationChannel(
    environment.CALENDAR_SYNC_STATE,
    {
      channelId,
      trackerUser: readRequiredString(channel, "tracker_user"),
      calendarId: readRequiredString(channel, "calendar_id"),
      resourceId: readRequiredString(channel, "resource_id"),
      channelToken: readRequiredString(channel, "channel_token"),
      syncToken: readRequiredString(channel, "google_change_cursor"),
      expiresAt: readRequiredNumber(channel, "expires_at"),
    },
  );
  return createJsonResponse({ registered: true, channel_id: channelId }, 201);
}
