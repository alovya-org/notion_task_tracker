import { createJsonResponse } from "../create_http_response";
import { WorkerEnvironment } from "../environment";
import { readRequiredString } from "../read_http_request";
import { authenticateGoogleCalendarStateRequest } from "./authenticate_google_calendar_state_request";
import { markGoogleCalendarEventDeletedByNtt } from "./google_calendar_state_database";

export async function markGoogleCalendarEventDeletedByNttRoute(
  request: Request,
  environment: WorkerEnvironment,
): Promise<Response> {
  if (request.method !== "PUT") {
    return createJsonResponse({ error: "Use PUT." }, 405, { Allow: "PUT" });
  }
  const authorisationFailure = authenticateGoogleCalendarStateRequest(request, environment);
  if (authorisationFailure !== null) {
    return authorisationFailure;
  }

  const eventIdentity = await request.json<Record<string, unknown>>();
  const googleEventId = readRequiredString(eventIdentity, "google_event_id");
  const markedDeleted = await markGoogleCalendarEventDeletedByNtt(
    environment.GOOGLE_CALENDAR_STATE_DATABASE,
    readRequiredString(eventIdentity, "tracker_user"),
    readRequiredString(eventIdentity, "calendar_id"),
    googleEventId,
    readRequiredString(eventIdentity, "ntt_task_id"),
  );
  if (!markedDeleted) {
    return createJsonResponse({ error: "Google Calendar event mapping not found." }, 409);
  }
  return createJsonResponse({ marked_deleted: true, google_event_id: googleEventId }, 200);
}
