import { createJsonResponse } from "../create_http_response";
import { requireEnvironmentVariables, WorkerEnvironment } from "../environment";

export function requireGoogleCalendarEnvironment(environment: WorkerEnvironment): void {
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

export function authenticateGoogleCalendarStateRequest(
  request: Request,
  environment: WorkerEnvironment,
): Response | null {
  requireGoogleCalendarEnvironment(environment);
  if (!environment.CALENDAR_SYNC_ADMIN_TOKEN) {
    throw new Error("Missing Worker environment variable: CALENDAR_SYNC_ADMIN_TOKEN");
  }
  if (request.headers.get("Authorization") !== `Bearer ${environment.CALENDAR_SYNC_ADMIN_TOKEN}`) {
    return createJsonResponse({ error: "Calendar sync state administration rejected." }, 401);
  }
  return null;
}
