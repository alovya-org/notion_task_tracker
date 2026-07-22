import { createJsonResponse } from "../create_http_response";
import { WorkerEnvironment } from "../environment";
import { authenticateGoogleCalendarStateRequest } from "./authenticate_google_calendar_state_request";
import { findLatestGoogleCalendarNotificationChannel } from "./google_calendar_state_database";

export async function readLatestGoogleCalendarNotificationChannel(
  request: Request,
  environment: WorkerEnvironment,
): Promise<Response> {
  const authorisationFailure = authenticateGoogleCalendarStateRequest(request, environment);
  if (authorisationFailure !== null) {
    return authorisationFailure;
  }

  const query = new URL(request.url).searchParams;
  const trackerUser = query.get("tracker_user");
  const calendarId = query.get("calendar_id");
  if (!trackerUser || !calendarId) {
    return createJsonResponse({ error: "tracker_user and calendar_id are required." }, 400);
  }

  const channel = await findLatestGoogleCalendarNotificationChannel(
    environment.GOOGLE_CALENDAR_STATE_DATABASE,
    trackerUser,
    calendarId,
  );
  if (channel === null) {
    return new Response(null, { status: 204 });
  }
  return createJsonResponse(channel, 200);
}
