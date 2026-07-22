import { createJsonResponse } from "../create_http_response";
import { WorkerEnvironment } from "../environment";
import { readRequiredNumber } from "../read_http_request";
import { authenticateGoogleCalendarStateRequest } from "./authenticate_google_calendar_state_request";
import { deleteExpiredGoogleCalendarNotificationChannels } from "./google_calendar_state_database";

export async function pruneExpiredGoogleCalendarNotificationChannels(
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

  const retentionBoundary = await request.json<Record<string, unknown>>();
  const deletedChannelCount = await deleteExpiredGoogleCalendarNotificationChannels(
    environment.GOOGLE_CALENDAR_STATE_DATABASE,
    readRequiredNumber(retentionBoundary, "expired_before"),
  );
  return createJsonResponse({ deleted_channel_count: deletedChannelCount }, 200);
}
