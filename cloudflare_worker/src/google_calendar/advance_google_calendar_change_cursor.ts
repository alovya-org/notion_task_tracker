import { createJsonResponse } from "../create_http_response";
import { WorkerEnvironment } from "../environment";
import { readRequiredString } from "../read_http_request";
import { authenticateGoogleCalendarStateRequest } from "./authenticate_google_calendar_state_request";
import { advanceGoogleCalendarChangeCursorInDatabase } from "./google_calendar_state_database";

export async function advanceGoogleCalendarChangeCursor(
  request: Request,
  environment: WorkerEnvironment,
): Promise<Response> {
  if (request.method !== "PATCH") {
    return createJsonResponse({ error: "Use PATCH." }, 405, { Allow: "PATCH" });
  }
  const authorisationFailure = authenticateGoogleCalendarStateRequest(request, environment);
  if (authorisationFailure !== null) {
    return authorisationFailure;
  }

  const cursorChange = await request.json<Record<string, unknown>>();
  const cursorAdvanced = await advanceGoogleCalendarChangeCursorInDatabase(
    environment.CALENDAR_SYNC_STATE,
    readRequiredString(cursorChange, "tracker_user"),
    readRequiredString(cursorChange, "calendar_id"),
    readRequiredString(cursorChange, "previous_google_change_cursor"),
    readRequiredString(cursorChange, "next_google_change_cursor"),
  );
  if (!cursorAdvanced) {
    return createJsonResponse({ error: "Google Calendar change cursor has already advanced." }, 409);
  }
  return createJsonResponse({ advanced: true }, 200);
}
