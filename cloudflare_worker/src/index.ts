interface Environment {
  GITHUB_OWNER: string;
  GITHUB_REPOSITORY: string;
  GITHUB_API_VERSION: string;
  GITHUB_DISPATCH_EVENT_TYPE: string;
  GITHUB_DISPATCH_TOKEN: string;
  NOTION_WEBHOOK_SECRET: string;
}

interface GitHubDispatchPayload {
  event_type: string;
  client_payload: {
    tracker_user: string;
  };
}

export default {
  async fetch(request: Request, environment: Environment): Promise<Response> {
    return await _dispatchNotionRefreshRequestToGitHub(request, environment);
  },
};

async function _dispatchNotionRefreshRequestToGitHub(
  request: Request,
  environment: Environment,
): Promise<Response> {
  if (request.method !== "POST") {
    console.log("Rejected request because the method was not POST.", {
      method: request.method,
    });
    return _createJsonResponse({ error: "Use POST." }, 405, { Allow: "POST" });
  }

  _assertWorkerEnvironmentIsComplete(environment);

  const suppliedSecret = request.headers.get("notion_webhook_secret");
  if (suppliedSecret === null || suppliedSecret.length === 0) {
    return _createJsonResponse({ error: "Missing notion_webhook_secret header." }, 400);
  }

  if (suppliedSecret !== environment.NOTION_WEBHOOK_SECRET) {
    console.log("Rejected request because the webhook secret did not match.");
    return _createJsonResponse({ error: "Webhook secret rejected." }, 401);
  }

  const trackerUser = request.headers.get("tracker_user");
  if (trackerUser === null || trackerUser.length === 0) {
    return _createJsonResponse({ error: "Missing tracker_user header." }, 400);
  }

  const dispatchPayload = _createGitHubDispatchPayload(
    environment.GITHUB_DISPATCH_EVENT_TYPE,
    trackerUser,
  );

  const githubResponse = await _sendGitHubRepositoryDispatch(
    environment.GITHUB_OWNER,
    environment.GITHUB_REPOSITORY,
    environment.GITHUB_API_VERSION,
    environment.GITHUB_DISPATCH_TOKEN,
    dispatchPayload,
  );

  if (!githubResponse.ok) {
    console.log("GitHub repository dispatch failed.", {
      githubStatus: githubResponse.status,
      trackerUser: dispatchPayload.client_payload.tracker_user,
    });
    return await _createGitHubFailureResponse(githubResponse);
  }

  console.log("GitHub repository dispatch succeeded.", {
    eventType: dispatchPayload.event_type,
    trackerUser: dispatchPayload.client_payload.tracker_user,
  });

  return _createJsonResponse(
    {
      dispatched: true,
      event_type: dispatchPayload.event_type,
      tracker_user: dispatchPayload.client_payload.tracker_user,
    },
    202,
  );
}

function _assertWorkerEnvironmentIsComplete(environment: Environment): void {
  const requiredEnvironmentVariableNames = [
    "GITHUB_OWNER",
    "GITHUB_REPOSITORY",
    "GITHUB_API_VERSION",
    "GITHUB_DISPATCH_EVENT_TYPE",
    "GITHUB_DISPATCH_TOKEN",
    "NOTION_WEBHOOK_SECRET",
  ] as const;

  const missingEnvironmentVariableName = requiredEnvironmentVariableNames.find(
    (environmentVariableName) => {
      const environmentVariableValue = environment[environmentVariableName];
      return typeof environmentVariableValue !== "string" || environmentVariableValue.length === 0;
    },
  );

  if (missingEnvironmentVariableName !== undefined) {
    throw new Error(`Missing Worker environment variable: ${missingEnvironmentVariableName}`);
  }
}

function _createGitHubDispatchPayload(
  eventType: string,
  trackerUser: string,
): GitHubDispatchPayload {
  return {
    event_type: eventType,
    client_payload: {
      tracker_user: trackerUser,
    },
  };
}

async function _sendGitHubRepositoryDispatch(
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

async function _createGitHubFailureResponse(githubResponse: Response): Promise<Response> {
  const responseText = await githubResponse.text();
  return _createJsonResponse(
    {
      error: "GitHub repository dispatch failed.",
      github_status: githubResponse.status,
      github_response: responseText,
    },
    502,
  );
}

function _createJsonResponse(
  body: Record<string, unknown>,
  status: number,
  headers: HeadersInit = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
  });
}
