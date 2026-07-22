import { createJsonResponse } from "../create_http_response";
import { WorkerEnvironment } from "../environment";
import { readRequiredString } from "../read_http_request";
import { authenticateGoogleCalendarStateRequest } from "./authenticate_google_calendar_state_request";
import { replaceGoogleCalendarEventLedgerFromSnapshot } from "./google_calendar_state_database";

export async function replaceGoogleCalendarEventLedgerSnapshot(
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

  const snapshot = await request.json<Record<string, unknown>>();
  const trackerUser = readRequiredString(snapshot, "tracker_user");
  const calendarId = readRequiredString(snapshot, "calendar_id");
  const activeEvents = _readActiveGoogleCalendarEvents(snapshot);
  await replaceGoogleCalendarEventLedgerFromSnapshot(
    environment.GOOGLE_CALENDAR_STATE_DATABASE,
    trackerUser,
    calendarId,
    activeEvents,
  );
  return createJsonResponse({ replaced: true, active_event_count: activeEvents.length }, 200);
}

function _readActiveGoogleCalendarEvents(
  snapshot: Record<string, unknown>,
): Array<{ googleEventId: string; nttTaskId: string }> {
  const activeEvents = snapshot.active_events;
  if (!Array.isArray(activeEvents)) {
    throw new Error("active_events must be an array");
  }
  return activeEvents.map((event) => {
    if (typeof event !== "object" || event === null || Array.isArray(event)) {
      throw new Error("Each active event must be an object");
    }
    const eventIdentity = event as Record<string, unknown>;
    return {
      googleEventId: readRequiredString(eventIdentity, "google_event_id"),
      nttTaskId: readRequiredString(eventIdentity, "ntt_task_id"),
    };
  });
}
