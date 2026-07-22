import { createJsonResponse } from "../create_http_response";
import { WorkerEnvironment } from "../environment";
import { readRequiredString } from "../read_http_request";
import { authenticateGoogleCalendarStateRequest } from "./authenticate_google_calendar_state_request";
import { deleteGoogleCalendarEventMapping } from "./google_calendar_state_database";

export async function deleteGoogleCalendarEventMappingRoute(
  request: Request,
  environment: WorkerEnvironment,
): Promise<Response> {
  if (request.method !== "DELETE") {
    return createJsonResponse({ error: "Use DELETE." }, 405, { Allow: "DELETE" });
  }
  const authorisationFailure = authenticateGoogleCalendarStateRequest(request, environment);
  if (authorisationFailure !== null) {
    return authorisationFailure;
  }

  const eventIdentity = await request.json<Record<string, unknown>>();
  const googleEventId = readRequiredString(eventIdentity, "google_event_id");
  const deleted = await deleteGoogleCalendarEventMapping(
    environment.GOOGLE_CALENDAR_STATE_DATABASE,
    readRequiredString(eventIdentity, "tracker_user"),
    readRequiredString(eventIdentity, "calendar_id"),
    googleEventId,
    readRequiredString(eventIdentity, "ntt_task_id"),
  );
  return createJsonResponse({ deleted, google_event_id: googleEventId }, 200);
}
