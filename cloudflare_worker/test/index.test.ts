import worker from "../src/index";
import { afterEach, describe, expect, it, vi } from "vitest";

const workerEnvironment = {
  GITHUB_OWNER: "alovya",
  GITHUB_REPOSITORY: "notion_task_tracker",
  GITHUB_API_VERSION: "2022-11-28",
  GITHUB_NOTION_TASK_TRACKER_CHANGE_EVENT_TYPE: "refresh-notion-task-tracker",
  GITHUB_GOOGLE_CALENDAR_CHANGE_EVENT_TYPE: "apply-google-calendar-changes-to-notion-task-tracker",
  GITHUB_REPOSITORY_DISPATCH_TOKEN: "github-token",
  NOTION_WEBHOOK_SECRET: "notion-secret",
  NTT_GOOGLE_CALENDAR_STATE_API_TOKEN: "calendar-state-api-token",
  GOOGLE_CALENDAR_STATE_DATABASE: _googleCalendarStateDatabaseReturning(null),
};

describe("Cloudflare Worker refresh dispatcher", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns not found for an unknown path", async () => {
    const response = await worker.fetch(
      new Request("https://example.com/unknown", { method: "POST" }),
      workerEnvironment,
    );

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "Not found." });
  });

  it("rejects non-POST requests before calling GitHub", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await worker.fetch(
      new Request("https://example.com/notion-task-tracker-changes", { method: "GET" }),
      workerEnvironment,
    );

    expect(response.status).toBe(405);
    expect(await response.json()).toEqual({ error: "Use POST." });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fails fast when the Worker environment is incomplete", async () => {
    await expect(
      worker.fetch(
        new Request("https://example.com/notion-task-tracker-changes", { method: "POST" }),
        {
          ...workerEnvironment,
          GITHUB_REPOSITORY_DISPATCH_TOKEN: "",
        },
      ),
    ).rejects.toThrow(
      "Missing Worker environment variable: GITHUB_REPOSITORY_DISPATCH_TOKEN",
    );
  });

  it("rejects requests with the wrong Notion webhook secret", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    const response = await worker.fetch(
      new Request("https://example.com/notion-task-tracker-changes", {
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
        "https://example.com/notion-task-tracker-changes?notion_webhook_secret=notion-secret&tracker_user=al0vya",
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
      new Request("https://example.com/notion-task-tracker-changes", {
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
      new Request("https://example.com/notion-task-tracker-changes", {
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
      event_type: "refresh-notion-task-tracker",
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
          event_type: "refresh-notion-task-tracker",
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
      new Request("https://example.com/notion-task-tracker-changes", {
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

  it("verifies channel identity and dispatches Google Calendar changes", async () => {
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
      event_type: "apply-google-calendar-changes-to-notion-task-tracker",
      tracker_user: "al0vya",
      channel_id: "channel-one",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.github.com/repos/alovya/notion_task_tracker/dispatches",
      expect.objectContaining({
        body: JSON.stringify({
          event_type: "apply-google-calendar-changes-to-notion-task-tracker",
          client_payload: {
            tracker_user: "al0vya",
            google_change_cursor: "current-sync-token",
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
    GOOGLE_CALENDAR_STATE_DATABASE: _googleCalendarStateDatabaseReturning({
      channel_id: "channel-one",
      resource_id: "resource-one",
      notification_channel_token_sha256: "07aae475f67f53e5cef11ebee8a133038a448d23615ec60808577872155db76e",
      tracker_user: "al0vya",
      calendar_id: "calendar@example.com",
      expiration: 1785000000000,
      google_change_cursor: "current-sync-token",
    }),
  };
}

describe("Cloudflare Worker Google Calendar state API", () => {
  it("returns the latest channel and current sync token for renewal decisions", async () => {
    const environment = _environmentWithCalendarChannel();
    const response = await worker.fetch(
      new Request(
        "https://example.com/google-calendar/notification-channels?tracker_user=al0vya&calendar_id=calendar%40example.com",
        { headers: { Authorization: "Bearer calendar-state-api-token" } },
      ),
      environment,
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(expect.objectContaining({
      channel_id: "channel-one",
      google_change_cursor: "current-sync-token",
    }));
  });

  it("registers a channel while preserving an existing cursor", async () => {
    const preparedStatements: Array<{ query: string; values: unknown[] }> = [];
    const database = _googleCalendarStateDatabaseRecording(preparedStatements);
    const response = await worker.fetch(
      new Request("https://example.com/google-calendar/notification-channels", {
        method: "POST",
        headers: {
          Authorization: "Bearer calendar-state-api-token",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          channel_id: "channel-two",
          tracker_user: "al0vya",
          calendar_id: "calendar@example.com",
          resource_id: "resource-two",
          channel_token: "new-channel-secret",
          google_change_cursor: "initial-sync-token",
          expires_at: 1786000000000,
        }),
      }),
      { ...workerEnvironment, GOOGLE_CALENDAR_STATE_DATABASE: database },
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

  it("rejects channel registration without the state API token", async () => {
    const response = await worker.fetch(
      new Request("https://example.com/google-calendar/notification-channels", {
        method: "POST",
      }),
      workerEnvironment,
    );

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({
      error: "Google Calendar state API token rejected.",
    });
  });

  it("advances the cursor only from the token consumed by the caller", async () => {
    const runMock = vi.fn(() => Promise.resolve({ meta: { changes: 1 } }));
    const database = _googleCalendarStateDatabaseRunning(runMock);
    const response = await worker.fetch(
      _calendarCursorAdvancementRequest(),
      { ...workerEnvironment, GOOGLE_CALENDAR_STATE_DATABASE: database },
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ advanced: true });
    expect(runMock).toHaveBeenCalledOnce();
  });

  it("rejects a stale cursor advancement", async () => {
    const database = _googleCalendarStateDatabaseRunning(
      vi.fn(() => Promise.resolve({ meta: { changes: 0 } })),
    );
    const response = await worker.fetch(
      _calendarCursorAdvancementRequest(),
      { ...workerEnvironment, GOOGLE_CALENDAR_STATE_DATABASE: database },
    );

    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({
      error: "Google Calendar change cursor has already advanced.",
    });
  });

  it("reads the durable cursor and event ledger as one synchronisation state", async () => {
    const database = _googleCalendarSynchronisationStateDatabase();
    const response = await worker.fetch(
      new Request(
        "https://example.com/google-calendar/synchronisation-state?tracker_user=al0vya&calendar_id=calendar%40example.com",
        { headers: { Authorization: "Bearer calendar-state-api-token" } },
      ),
      { ...workerEnvironment, GOOGLE_CALENDAR_STATE_DATABASE: database },
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      tracker_user: "al0vya",
      calendar_id: "calendar@example.com",
      google_change_cursor: "current-sync-token",
      event_ledger: [
        {
          google_event_id: "event-one",
          ntt_task_id: "ALOVYA-42",
          lifecycle_state: "active",
        },
        {
          google_event_id: "event-two",
          ntt_task_id: "ALOVYA-43",
          lifecycle_state: "deleted_by_ntt",
        },
      ],
    });
  });

  it("records the current event identity without creating edit history", async () => {
    const recordedStatements: Array<{ query: string; values: unknown[] }> = [];
    const database = _googleCalendarStateDatabaseRecordingRuns(recordedStatements, 1);
    const response = await worker.fetch(
      _eventLedgerRequest("active-events"),
      { ...workerEnvironment, GOOGLE_CALENDAR_STATE_DATABASE: database },
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ recorded: true, google_event_id: "event-one" });
    expect(recordedStatements).toHaveLength(1);
    expect(recordedStatements[0].query).toContain(
      "ON CONFLICT (tracker_user, calendar_id, google_event_id) DO UPDATE",
    );
    expect(recordedStatements[0].values.slice(0, 4)).toEqual([
      "al0vya",
      "calendar@example.com",
      "event-one",
      "ALOVYA-42",
    ]);
  });

  it("marks an active event as deleted by NTT with matching event and task identity", async () => {
    const recordedStatements: Array<{ query: string; values: unknown[] }> = [];
    const database = _googleCalendarStateDatabaseRecordingRuns(recordedStatements, 1);
    const response = await worker.fetch(
      _eventLedgerRequest("ntt-deletions"),
      { ...workerEnvironment, GOOGLE_CALENDAR_STATE_DATABASE: database },
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      marked_deleted: true,
      google_event_id: "event-one",
    });
    expect(recordedStatements).toHaveLength(1);
    expect(recordedStatements[0].query).toContain("lifecycle_state = 'deleted_by_ntt'");
    expect(recordedStatements[0].values.slice(1)).toEqual([
      "al0vya",
      "calendar@example.com",
      "event-one",
      "ALOVYA-42",
    ]);
  });

  it("rejects an NTT deletion when the event identity does not exist", async () => {
    const database = _googleCalendarStateDatabaseRecordingRuns([], 0);
    const response = await worker.fetch(
      _eventLedgerRequest("ntt-deletions"),
      { ...workerEnvironment, GOOGLE_CALENDAR_STATE_DATABASE: database },
    );

    expect(response.status).toBe(409);
    expect(await response.json()).toEqual({
      error: "Google Calendar event mapping not found.",
    });
  });
});

describe("Cloudflare Worker daily Calendar recovery", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("dispatches incremental changes from every durable sync token", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })));
    vi.stubGlobal("fetch", fetchMock);
    const database = {
      prepare: vi.fn(() => ({
        all: vi.fn(() => Promise.resolve({
          results: [
            { tracker_user: "al0vya", google_change_cursor: "current-sync-token" },
          ],
        })),
      })),
    } as unknown as D1Database;

    await worker.scheduled(
      {} as ScheduledController,
      { ...workerEnvironment, GOOGLE_CALENDAR_STATE_DATABASE: database },
    );

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledWith(
      "https://api.github.com/repos/alovya/notion_task_tracker/dispatches",
      expect.objectContaining({
        body: JSON.stringify({
          event_type: "apply-google-calendar-changes-to-notion-task-tracker",
          client_payload: {
            tracker_user: "al0vya",
            google_change_cursor: "current-sync-token",
          },
        }),
      }),
    );
  });
});

function _googleCalendarStateDatabaseReturning(channelState: object | null) {
  return {
    prepare: vi.fn(() => ({
      bind: vi.fn(() => ({
        first: vi.fn(() => Promise.resolve(channelState)),
      })),
    })),
  } as unknown as D1Database;
}

function _googleCalendarStateDatabaseRecording(
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

function _googleCalendarStateDatabaseRunning(runMock: ReturnType<typeof vi.fn>) {
  return {
    prepare: vi.fn(() => ({
      bind: vi.fn(() => ({ run: runMock })),
    })),
  } as unknown as D1Database;
}

function _googleCalendarSynchronisationStateDatabase() {
  return {
    prepare: vi.fn((query: string) => ({
      bind: vi.fn(() => ({
        first: vi.fn(() => Promise.resolve({ google_change_cursor: "current-sync-token" })),
        all: vi.fn(() => Promise.resolve({
          results: query.includes("google_calendar_event_ledger")
            ? [
                {
                  google_event_id: "event-one",
                  ntt_task_id: "ALOVYA-42",
                  lifecycle_state: "active",
                },
                {
                  google_event_id: "event-two",
                  ntt_task_id: "ALOVYA-43",
                  lifecycle_state: "deleted_by_ntt",
                },
              ]
            : [],
        })),
      })),
    })),
  } as unknown as D1Database;
}

function _googleCalendarStateDatabaseRecordingRuns(
  recordedStatements: Array<{ query: string; values: unknown[] }>,
  changedRows: number,
) {
  return {
    prepare: vi.fn((query: string) => ({
      bind: vi.fn((...values: unknown[]) => {
        recordedStatements.push({ query, values });
        return {
          run: vi.fn(() => Promise.resolve({ meta: { changes: changedRows } })),
        };
      }),
    })),
  } as unknown as D1Database;
}

function _calendarCursorAdvancementRequest() {
  return new Request("https://example.com/google-calendar/change-cursors", {
    method: "PATCH",
    headers: {
      Authorization: "Bearer calendar-state-api-token",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      tracker_user: "al0vya",
      calendar_id: "calendar@example.com",
      previous_google_change_cursor: "previous-sync-token",
      next_google_change_cursor: "next-sync-token",
    }),
  });
}

function _eventLedgerRequest(resourceName: "active-events" | "ntt-deletions") {
  return new Request(`https://example.com/google-calendar/event-ledger/${resourceName}`, {
    method: "PUT",
    headers: {
      Authorization: "Bearer calendar-state-api-token",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      tracker_user: "al0vya",
      calendar_id: "calendar@example.com",
      google_event_id: "event-one",
      ntt_task_id: "ALOVYA-42",
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
