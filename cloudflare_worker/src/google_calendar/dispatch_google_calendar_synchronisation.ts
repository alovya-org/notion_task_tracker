import { createJsonResponse } from "../create_http_response";
import { WorkerEnvironment } from "../environment";
import {
  createGitHubDispatchPayload,
  createGitHubFailureResponse,
  sendGitHubRepositoryDispatch,
} from "../github/send_github_repository_dispatch";
import { readRequiredString } from "../read_http_request";
import { authenticateGoogleCalendarStateRequest } from "./authenticate_google_calendar_state_request";

export async function dispatchGoogleCalendarSynchronisation(
  request: Request,
  environment: WorkerEnvironment,
): Promise<Response> {
  if (request.method !== "POST") {
    return createJsonResponse({ error: "Use POST." }, 405, { Allow: "POST" });
  }
  const authorisationFailure = authenticateGoogleCalendarStateRequest(request, environment);
  if (authorisationFailure !== null) {
    return authorisationFailure;
  }

  const requestedDispatch = await request.json<Record<string, unknown>>();
  const trackerUser = readRequiredString(requestedDispatch, "tracker_user");
  const dispatchPayload = createGitHubDispatchPayload(
    environment.GITHUB_GOOGLE_CALENDAR_CHANGE_EVENT_TYPE,
    trackerUser,
  );
  const githubResponse = await sendGitHubRepositoryDispatch(
    environment.GITHUB_OWNER,
    environment.GITHUB_REPOSITORY,
    environment.GITHUB_API_VERSION,
    environment.GITHUB_REPOSITORY_DISPATCH_TOKEN,
    dispatchPayload,
  );
  if (!githubResponse.ok) {
    return await createGitHubFailureResponse(githubResponse);
  }
  return createJsonResponse({ dispatched: true, tracker_user: trackerUser }, 202);
}
