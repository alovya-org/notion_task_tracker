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
  CALENDAR_SYNC_ADMIN_TOKEN: "calendar-admin-token",
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
            sync_token: "current-sync-token",
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
      sync_token: "current-sync-token",
    }),
  };
}

describe("Cloudflare Worker calendar sync state administration", () => {
  it("returns the latest channel and current sync token for renewal decisions", async () => {
    const environment = _environmentWithCalendarChannel();
    const response = await worker.fetch(
      new Request(
        "https://example.com/calendar-sync-state/channels?tracker_user=al0vya&calendar_id=calendar%40example.com",
        { headers: { Authorization: "Bearer calendar-admin-token" } },
      ),
      environment,
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(expect.objectContaining({
      channel_id: "channel-one",
      sync_token: "current-sync-token",
    }));
  });

  it("registers a channel while preserving an existing cursor", async () => {
    const preparedStatements: Array<{ query: string; values: unknown[] }> = [];
    const database = _calendarSyncDatabaseRecording(preparedStatements);
    const response = await worker.fetch(
      new Request("https://example.com/calendar-sync-state/channels", {
        method: "POST",
        headers: {
          Authorization: "Bearer calendar-admin-token",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          channel_id: "channel-two",
          tracker_user: "al0vya",
          calendar_id: "calendar@example.com",
          resource_id: "resource-two",
          channel_token: "new-channel-secret",
          sync_token: "initial-sync-token",
          expires_at: 1786000000000,
        }),
      }),
      { ...workerEnvironment, CALENDAR_SYNC_STATE: database },
    );

    expect(response.status).toBe(201);
    expect(await response.json()).toEqual({ registered: true, channel_id: "channel-two" });
    expect(preparedStatements).toHaveLength(2);
    expect(preparedStatements[0].query).toContain("ON CONFLICT (tracker_user, calendar_id) DO NOTHING");
    expect(preparedStatements[0].values.slice(0, 3)).toEqual([
      "al0vya",
      "calendar@example.com",
      "initial-sync-token",
    ]);
    expect(preparedStatements[1].values.slice(0, 4)).toEqual([
      "channel-two",
      "al0vya",
      "calendar@example.com",
      "resource-two",
    ]);
    expect(preparedStatements[1].values[4]).not.toBe("new-channel-secret");
  });

  it("rejects channel registration without the administrative token", async () => {
    const response = await worker.fetch(
      new Request("https://example.com/calendar-sync-state/channels", { method: "POST" }),
      workerEnvironment,
    );

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({
      error: "Calendar sync state administration rejected.",
    });
  });

  it("advances the cursor only from the token consumed by the caller", async () => {
    const runMock = vi.fn(() => Promise.resolve({ meta: { changes: 1 } }));
    const database = _calendarSyncDatabaseRunning(runMock);
    const response = await worker.fetch(
      _calendarCursorAdvancementRequest(),
      { ...workerEnvironment, CALENDAR_SYNC_STATE: database },
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ advanced: true });
    expect(runMock).toHaveBeenCalledOnce();
  });

  it("rejects a stale cursor advancement", async () => {
    const database = _calendarSyncDatabaseRunning(
      vi.fn(() => Promise.resolve({ meta: { changes: 0 } })),
    );
    const response = await worker.fetch(
      _calendarCursorAdvancementRequest(),
      { ...workerEnvironment, CALENDAR_SYNC_STATE: database },
    );

    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({
      error: "Calendar sync cursor has already advanced.",
    });
  });
});

describe("Cloudflare Worker daily Calendar recovery", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("dispatches incremental reconciliation from every durable sync token", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })));
    vi.stubGlobal("fetch", fetchMock);
    const database = {
      prepare: vi.fn(() => ({
        all: vi.fn(() => Promise.resolve({
          results: [
            { tracker_user: "al0vya", sync_token: "current-sync-token" },
          ],
        })),
      })),
    } as unknown as D1Database;

    await worker.scheduled(
      {} as ScheduledController,
      { ...workerEnvironment, CALENDAR_SYNC_STATE: database },
    );

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.github.com/repos/alovya/notion_task_tracker/dispatches",
      expect.objectContaining({
        body: JSON.stringify({
          event_type: "reconcile-google-calendar",
          client_payload: {
            tracker_user: "al0vya",
            sync_token: "current-sync-token",
          },
        }),
      }),
    );
  });
});

function _calendarSyncDatabaseReturning(channelState: object | null) {
  return {
    prepare: vi.fn(() => ({
      bind: vi.fn(() => ({
        first: vi.fn(() => Promise.resolve(channelState)),
      })),
    })),
  } as unknown as D1Database;
}

function _calendarSyncDatabaseRecording(
  preparedStatements: Array<{ query: string; values: unknown[] }>,
) {
  return {
    prepare: vi.fn((query: string) => ({
      bind: vi.fn((...values: unknown[]) => {
        const statement = { query, values };
        preparedStatements.push(statement);
        return statement;
      }),
    })),
    batch: vi.fn(() => Promise.resolve([])),
  } as unknown as D1Database;
}

function _calendarSyncDatabaseRunning(runMock: ReturnType<typeof vi.fn>) {
  return {
    prepare: vi.fn(() => ({
      bind: vi.fn(() => ({ run: runMock })),
    })),
  } as unknown as D1Database;
}

function _calendarCursorAdvancementRequest() {
  return new Request("https://example.com/calendar-sync-state/cursors", {
    method: "PATCH",
    headers: {
      Authorization: "Bearer calendar-admin-token",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      tracker_user: "al0vya",
      calendar_id: "calendar@example.com",
      previous_sync_token: "previous-sync-token",
      next_sync_token: "next-sync-token",
    }),
  });
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
