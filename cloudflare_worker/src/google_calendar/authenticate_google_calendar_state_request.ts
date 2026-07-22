import { createJsonResponse } from "../create_http_response";
import { requireEnvironmentVariables, WorkerEnvironment } from "../environment";

export function requireGoogleCalendarEnvironment(environment: WorkerEnvironment): void {
  requireEnvironmentVariables(environment, [
    "GITHUB_OWNER",
    "GITHUB_REPOSITORY",
    "GITHUB_API_VERSION",
    "GITHUB_GOOGLE_CALENDAR_CHANGE_EVENT_TYPE",
    "GITHUB_REPOSITORY_DISPATCH_TOKEN",
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
  if (!environment.NTT_GOOGLE_CALENDAR_STATE_API_TOKEN) {
    throw new Error(
      "Missing Worker environment variable: NTT_GOOGLE_CALENDAR_STATE_API_TOKEN",
    );
  }
  if (
    request.headers.get("Authorization")
    !== `Bearer ${environment.NTT_GOOGLE_CALENDAR_STATE_API_TOKEN}`
  ) {
    return createJsonResponse({ error: "Google Calendar state API token rejected." }, 401);
  }
  return null;
}
