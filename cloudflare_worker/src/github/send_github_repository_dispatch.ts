import { createJsonResponse } from "../create_http_response";

export interface GitHubDispatchPayload {
  event_type: string;
  client_payload: {
    tracker_user: string;
    channel_id?: string;
    sync_token?: string;
  };
}

export function createGitHubDispatchPayload(
  eventType: string,
  trackerUser: string,
  channelId?: string,
  syncToken?: string,
): GitHubDispatchPayload {
  const clientPayload: GitHubDispatchPayload["client_payload"] = {
    tracker_user: trackerUser,
  };
  if (channelId !== undefined) {
    clientPayload.channel_id = channelId;
  }
  if (syncToken !== undefined) {
    clientPayload.sync_token = syncToken;
  }
  return {
    event_type: eventType,
    client_payload: clientPayload,
  };
}

export async function sendGitHubRepositoryDispatch(
  githubOwner: string,
  githubRepository: string,
  githubApiVersion: string,
  githubDispatchToken: string,
  dispatchPayload: GitHubDispatchPayload,
): Promise<Response> {
  const dispatchUrl = `https://api.github.com/repos/${githubOwner}/${githubRepository}/dispatches`;

  return await fetch(dispatchUrl, {
    method: "POST",
    headers: {
      Accept: "application/vnd.github+json",
      Authorization: `Bearer ${githubDispatchToken}`,
      "Content-Type": "application/json",
      "User-Agent": "notion-task-tracker-cloudflare-worker",
      "X-GitHub-Api-Version": githubApiVersion,
    },
    body: JSON.stringify(dispatchPayload),
  });
}

export async function createGitHubFailureResponse(
  githubResponse: Response,
): Promise<Response> {
  const responseText = await githubResponse.text();
  return createJsonResponse(
    {
      error: "GitHub repository dispatch failed.",
      github_status: githubResponse.status,
      github_response: responseText,
    },
    502,
  );
}
