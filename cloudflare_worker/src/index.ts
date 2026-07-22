interface Environment {
  GITHUB_OWNER: string;
  GITHUB_REPOSITORY: string;
  GITHUB_API_VERSION: string;
  GITHUB_DISPATCH_EVENT_TYPE: string;
  GITHUB_CALENDAR_DISPATCH_EVENT_TYPE: string;
  GITHUB_DISPATCH_TOKEN: string;
  NOTION_WEBHOOK_SECRET: string;
  CALENDAR_SYNC_STATE: D1Database;
}

interface GitHubDispatchPayload {
  event_type: string;
  client_payload: {
    tracker_user: string;
    channel_id?: string;
  };
}

interface CalendarChannelState {
  channel_id: string;
  resource_id: string;
  channel_token_sha256: string;
  tracker_user: string;
  calendar_id: string;
  expiration: number;
}

const GOOGLE_CALENDAR_NOTIFICATION_PATH = "/google-calendar-notifications";

export default {
  async fetch(request: Request, environment: Environment): Promise<Response> {
    if (new URL(request.url).pathname === GOOGLE_CALENDAR_NOTIFICATION_PATH) {
      return await _dispatchGoogleCalendarChangeToGitHub(request, environment);
    }
    return await _dispatchNotionRefreshRequestToGitHub(request, environment);
  },
};

async function _dispatchGoogleCalendarChangeToGitHub(
  request: Request,
  environment: Environment,
): Promise<Response> {
  if (request.method !== "POST") {
    return _createJsonResponse({ error: "Use POST." }, 405, { Allow: "POST" });
  }

  _assertGoogleCalendarEnvironmentIsComplete(environment);
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
    return _createJsonResponse(
      { error: `Missing Google Calendar notification header: ${missingHeaderName}` },
      400,
    );
  }
  const channelId = request.headers.get("X-Goog-Channel-ID")!;
  const channelToken = request.headers.get("X-Goog-Channel-Token")!;
  const resourceId = request.headers.get("X-Goog-Resource-ID")!;
  const resourceState = request.headers.get("X-Goog-Resource-State")!;
  const channelState = await environment.CALENDAR_SYNC_STATE
    .prepare(
      `SELECT channel_id, resource_id, channel_token_sha256, tracker_user, calendar_id, expires_at AS expiration
       FROM calendar_channels
       WHERE channel_id = ?`,
    )
    .bind(channelId)
    .first<CalendarChannelState>();
  if (channelState === null) {
    return _createJsonResponse({ error: "Unknown Google Calendar channel." }, 401);
  }
  const suppliedChannelTokenSha256 = await _sha256Hex(channelToken);
  if (
    channelState.channel_token_sha256 !== suppliedChannelTokenSha256
    || channelState.resource_id !== resourceId
  ) {
    return _createJsonResponse({ error: "Google Calendar channel identity rejected." }, 401);
  }
  if (resourceState === "sync") {
    return new Response(null, { status: 204 });
  }
  if (!new Set(["exists", "not_exists"]).has(resourceState)) {
    return _createJsonResponse({ error: "Unsupported Google Calendar resource state." }, 400);
  }

  const dispatchPayload = _createGitHubDispatchPayload(
    environment.GITHUB_CALENDAR_DISPATCH_EVENT_TYPE,
    channelState.tracker_user,
    channelId,
  );
  const githubResponse = await _sendGitHubRepositoryDispatch(
    environment.GITHUB_OWNER,
    environment.GITHUB_REPOSITORY,
    environment.GITHUB_API_VERSION,
    environment.GITHUB_DISPATCH_TOKEN,
    dispatchPayload,
  );
  if (!githubResponse.ok) {
    return await _createGitHubFailureResponse(githubResponse);
  }
  return _createJsonResponse({
    dispatched: true,
    event_type: dispatchPayload.event_type,
    tracker_user: channelState.tracker_user,
    channel_id: channelId,
  }, 202);
}

async function _sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

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

function _assertGoogleCalendarEnvironmentIsComplete(environment: Environment): void {
  _assertWorkerEnvironmentIsComplete(environment);
  if (!environment.GITHUB_CALENDAR_DISPATCH_EVENT_TYPE) {
    throw new Error("Missing Worker environment variable: GITHUB_CALENDAR_DISPATCH_EVENT_TYPE");
  }
  if (!environment.CALENDAR_SYNC_STATE) {
    throw new Error("Missing Worker environment binding: CALENDAR_SYNC_STATE");
  }
}

function _createGitHubDispatchPayload(
  eventType: string,
  trackerUser: string,
  channelId?: string,
): GitHubDispatchPayload {
  const clientPayload: GitHubDispatchPayload["client_payload"] = {
    tracker_user: trackerUser,
  };
  if (channelId !== undefined) {
    clientPayload.channel_id = channelId;
  }
  return {
    event_type: eventType,
    client_payload: clientPayload,
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
