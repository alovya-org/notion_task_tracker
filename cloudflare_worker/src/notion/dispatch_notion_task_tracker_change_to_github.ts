import { createJsonResponse } from "../create_http_response";
import { requireEnvironmentVariables, WorkerEnvironment } from "../environment";
import {
  createGitHubDispatchPayload,
  createGitHubFailureResponse,
  sendGitHubRepositoryDispatch,
} from "../github/send_github_repository_dispatch";

export async function dispatchNotionTaskTrackerChangeToGitHub(
  request: Request,
  environment: WorkerEnvironment,
): Promise<Response> {
  if (request.method !== "POST") {
    console.log("Rejected request because the method was not POST.", {
      method: request.method,
    });
    return createJsonResponse({ error: "Use POST." }, 405, { Allow: "POST" });
  }

  requireEnvironmentVariables(environment, [
    "GITHUB_OWNER",
    "GITHUB_REPOSITORY",
    "GITHUB_API_VERSION",
    "GITHUB_NOTION_TASK_TRACKER_CHANGE_EVENT_TYPE",
    "GITHUB_REPOSITORY_DISPATCH_TOKEN",
    "NOTION_WEBHOOK_SECRET",
  ]);

  const suppliedSecret = request.headers.get("notion_webhook_secret");
  if (suppliedSecret === null || suppliedSecret.length === 0) {
    return createJsonResponse({ error: "Missing notion_webhook_secret header." }, 400);
  }

  if (suppliedSecret !== environment.NOTION_WEBHOOK_SECRET) {
    console.log("Rejected request because the webhook secret did not match.");
    return createJsonResponse({ error: "Webhook secret rejected." }, 401);
  }

  const trackerUser = request.headers.get("tracker_user");
  if (trackerUser === null || trackerUser.length === 0) {
    return createJsonResponse({ error: "Missing tracker_user header." }, 400);
  }

  const dispatchPayload = createGitHubDispatchPayload(
    environment.GITHUB_NOTION_TASK_TRACKER_CHANGE_EVENT_TYPE,
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
    console.log("GitHub repository dispatch failed.", {
      githubStatus: githubResponse.status,
      trackerUser: dispatchPayload.client_payload.tracker_user,
    });
    return await createGitHubFailureResponse(githubResponse);
  }

  console.log("GitHub repository dispatch succeeded.", {
    eventType: dispatchPayload.event_type,
    trackerUser: dispatchPayload.client_payload.tracker_user,
  });
  return createJsonResponse(
    {
      dispatched: true,
      event_type: dispatchPayload.event_type,
      tracker_user: dispatchPayload.client_payload.tracker_user,
    },
    202,
  );
}
