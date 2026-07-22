import { createJsonResponse } from "../create_http_response";
import { WorkerEnvironment } from "../environment";
import {
  createGitHubDispatchPayload,
  createGitHubFailureResponse,
  sendGitHubRepositoryDispatch,
} from "../github/send_github_repository_dispatch";
import { requireGoogleCalendarEnvironment } from "./authenticate_google_calendar_state_request";
import {
  findGoogleCalendarNotificationChannelById,
  hashGoogleCalendarNotificationChannelToken,
} from "./google_calendar_state_database";

export async function receiveGoogleCalendarNotification(
  request: Request,
  environment: WorkerEnvironment,
): Promise<Response> {
  if (request.method !== "POST") {
    return createJsonResponse({ error: "Use POST." }, 405, { Allow: "POST" });
  }

  requireGoogleCalendarEnvironment(environment);
  const requiredHeaderNames = [
    "X-Goog-Channel-ID",
    "X-Goog-Channel-Token",
    "X-Goog-Resource-ID",
    "X-Goog-Resource-State",
  ];
  const missingHeaderName = requiredHeaderNames.find(
    (headerName) => !request.headers.get(headerName),
  );
  if (missingHeaderName !== undefined) {
    return createJsonResponse(
      { error: `Missing Google Calendar notification header: ${missingHeaderName}` },
      400,
    );
  }

  const channelId = request.headers.get("X-Goog-Channel-ID")!;
  const channelToken = request.headers.get("X-Goog-Channel-Token")!;
  const resourceId = request.headers.get("X-Goog-Resource-ID")!;
  const resourceState = request.headers.get("X-Goog-Resource-State")!;
  const channelState = await findGoogleCalendarNotificationChannelById(
    environment.CALENDAR_SYNC_STATE,
    channelId,
  );
  if (channelState === null) {
    return createJsonResponse({ error: "Unknown Google Calendar channel." }, 401);
  }

  const suppliedChannelTokenSha256 = await hashGoogleCalendarNotificationChannelToken(
    channelToken,
  );
  if (
    channelState.channel_token_sha256 !== suppliedChannelTokenSha256
    || channelState.resource_id !== resourceId
  ) {
    return createJsonResponse({ error: "Google Calendar channel identity rejected." }, 401);
  }
  if (resourceState === "sync") {
    return new Response(null, { status: 204 });
  }
  if (!new Set(["exists", "not_exists"]).has(resourceState)) {
    return createJsonResponse({ error: "Unsupported Google Calendar resource state." }, 400);
  }

  const dispatchPayload = createGitHubDispatchPayload(
    environment.GITHUB_CALENDAR_DISPATCH_EVENT_TYPE,
    channelState.tracker_user,
    channelId,
    channelState.sync_token,
  );
  const githubResponse = await sendGitHubRepositoryDispatch(
    environment.GITHUB_OWNER,
    environment.GITHUB_REPOSITORY,
    environment.GITHUB_API_VERSION,
    environment.GITHUB_DISPATCH_TOKEN,
    dispatchPayload,
  );
  if (!githubResponse.ok) {
    return await createGitHubFailureResponse(githubResponse);
  }
  return createJsonResponse({
    dispatched: true,
    event_type: dispatchPayload.event_type,
    tracker_user: channelState.tracker_user,
    channel_id: channelId,
  }, 202);
}
