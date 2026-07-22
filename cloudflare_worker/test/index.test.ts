import worker from "../src/index";
import { afterEach, describe, expect, it, vi } from "vitest";

const workerEnvironment = {
  GITHUB_OWNER: "alovya",
  GITHUB_REPOSITORY: "notion_task_tracker",
  GITHUB_API_VERSION: "2022-11-28",
  GITHUB_DISPATCH_EVENT_TYPE: "refresh-notion-tracker",
  GITHUB_CALENDAR_DISPATCH_EVENT_TYPE: "reconcile-google-calendar",
  GITHUB_DISPATCH_TOKEN: "github-token",
  NOTION_WEBHOOK_SECRET: "notion-secret",
  CALENDAR_SYNC_STATE: _calendarSyncDatabaseReturning(null),
};

describe("Cloudflare Worker refresh dispatcher", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("rejects non-POST requests before calling GitHub", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await worker.fetch(
      new Request("https://example.com", { method: "GET" }),
      workerEnvironment,
    );

    expect(response.status).toBe(405);
    expect(await response.json()).toEqual({ error: "Use POST." });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fails fast when the Worker environment is incomplete", async () => {
    await expect(
      worker.fetch(
        new Request("https://example.com", { method: "POST" }),
        {
          ...workerEnvironment,
          GITHUB_DISPATCH_TOKEN: "",
        },
      ),
    ).rejects.toThrow("Missing Worker environment variable: GITHUB_DISPATCH_TOKEN");
  });

  it("rejects requests with the wrong Notion webhook secret", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await worker.fetch(
      new Request("https://example.com", {
        method: "POST",
        headers: {
          notion_webhook_secret: "wrong-secret",
          tracker_user: "al0vya",
        },
      }),
      workerEnvironment,
    );

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: "Webhook secret rejected." });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects credentials outside the required Notion headers", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await worker.fetch(
      new Request(
        "https://example.com?notion_webhook_secret=notion-secret&tracker_user=al0vya",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            notion_webhook_secret: "notion-secret",
            tracker_user: "al0vya",
          }),
        },
      ),
      workerEnvironment,
    );

    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({
      error: "Missing notion_webhook_secret header.",
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects requests without a tracker user before calling GitHub", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await worker.fetch(
      new Request("https://example.com", {
        method: "POST",
        headers: {
          notion_webhook_secret: "notion-secret",
        },
      }),
      workerEnvironment,
    );

    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ error: "Missing tracker_user header." });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("dispatches GitHub refresh from Notion custom headers", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })));
    vi.stubGlobal("fetch", fetchMock);

    const response = await worker.fetch(
      new Request("https://example.com", {
        method: "POST",
        headers: {
          notion_webhook_secret: "notion-secret",
          tracker_user: "al0vya",
        },
      }),
      workerEnvironment,
    );

    expect(response.status).toBe(202);
    expect(await response.json()).toEqual({
      dispatched: true,
      event_type: "refresh-notion-tracker",
      tracker_user: "al0vya",
    });
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.github.com/repos/alovya/notion_task_tracker/dispatches",
      {
        method: "POST",
        headers: {
          Accept: "application/vnd.github+json",
          Authorization: "Bearer github-token",
          "Content-Type": "application/json",
          "User-Agent": "notion-task-tracker-cloudflare-worker",
          "X-GitHub-Api-Version": "2022-11-28",
        },
        body: JSON.stringify({
          event_type: "refresh-notion-tracker",
          client_payload: {
            tracker_user: "al0vya",
          },
        }),
      },
    );
  });

  it("returns GitHub failure details when dispatch is rejected", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(new Response("bad credentials", { status: 401 })),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await worker.fetch(
      new Request("https://example.com", {
        method: "POST",
        headers: {
          notion_webhook_secret: "notion-secret",
          tracker_user: "al0vya",
        },
      }),
      workerEnvironment,
    );

    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({
      error: "GitHub repository dispatch failed.",
      github_status: 401,
      github_response: "bad credentials",
    });
  });
});

describe("Cloudflare Worker Google Calendar dispatcher", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("rejects notifications for unknown channels", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await worker.fetch(
      _googleCalendarNotificationRequest("exists"),
      workerEnvironment,
    );

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: "Unknown Google Calendar channel." });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("accepts the initial Google sync message without dispatching", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const environment = _environmentWithCalendarChannel();

    const response = await worker.fetch(
      _googleCalendarNotificationRequest("sync"),
      environment,
    );

    expect(response.status).toBe(204);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("verifies channel identity and dispatches a calendar reconciliation", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })));
    vi.stubGlobal("fetch", fetchMock);
    const environment = _environmentWithCalendarChannel();

    const response = await worker.fetch(
      _googleCalendarNotificationRequest("exists"),
      environment,
    );

    expect(response.status).toBe(202);
    expect(await response.json()).toEqual({
      dispatched: true,
      event_type: "reconcile-google-calendar",
      tracker_user: "al0vya",
      channel_id: "channel-one",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.github.com/repos/alovya/notion_task_tracker/dispatches",
      expect.objectContaining({
        body: JSON.stringify({
          event_type: "reconcile-google-calendar",
          client_payload: {
            tracker_user: "al0vya",
            channel_id: "channel-one",
          },
        }),
      }),
    );
  });

  it("rejects a notification whose token does not match durable channel state", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const environment = _environmentWithCalendarChannel();
    const request = _googleCalendarNotificationRequest("exists", "wrong-token");

    const response = await worker.fetch(request, environment);

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({
      error: "Google Calendar channel identity rejected.",
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

function _environmentWithCalendarChannel() {
  return {
    ...workerEnvironment,
    CALENDAR_SYNC_STATE: _calendarSyncDatabaseReturning({
      channel_id: "channel-one",
      resource_id: "resource-one",
      channel_token_sha256: "07aae475f67f53e5cef11ebee8a133038a448d23615ec60808577872155db76e",
      tracker_user: "al0vya",
      calendar_id: "calendar@example.com",
      expiration: 1785000000000,
    }),
  };
}

function _calendarSyncDatabaseReturning(channelState: object | null) {
  return {
    prepare: vi.fn(() => ({
      bind: vi.fn(() => ({
        first: vi.fn(() => Promise.resolve(channelState)),
      })),
    })),
  } as unknown as D1Database;
}

function _googleCalendarNotificationRequest(
  resourceState: string,
  channelToken = "channel-secret",
) {
  return new Request("https://example.com/google-calendar-notifications", {
    method: "POST",
    headers: {
      "X-Goog-Channel-ID": "channel-one",
      "X-Goog-Channel-Token": channelToken,
      "X-Goog-Resource-ID": "resource-one",
      "X-Goog-Resource-State": resourceState,
    },
  });
}
