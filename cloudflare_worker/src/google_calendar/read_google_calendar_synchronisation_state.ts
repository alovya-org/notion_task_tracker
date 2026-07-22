import { createJsonResponse } from "../create_http_response";
import { WorkerEnvironment } from "../environment";
import { authenticateGoogleCalendarStateRequest } from "./authenticate_google_calendar_state_request";
import {
  listGoogleCalendarEventLedgerEntries,
  readGoogleCalendarChangeCursor,
} from "./google_calendar_state_database";

export async function readGoogleCalendarSynchronisationState(
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

  const googleChangeCursor = await readGoogleCalendarChangeCursor(
    environment.GOOGLE_CALENDAR_STATE_DATABASE,
    trackerUser,
    calendarId,
  );
  if (googleChangeCursor === null) {
    return new Response(null, { status: 204 });
  }
  const eventLedger = await listGoogleCalendarEventLedgerEntries(
    environment.GOOGLE_CALENDAR_STATE_DATABASE,
    trackerUser,
    calendarId,
  );
  return createJsonResponse({
    tracker_user: trackerUser,
    calendar_id: calendarId,
    google_change_cursor: googleChangeCursor,
    event_ledger: eventLedger,
  }, 200);
}
