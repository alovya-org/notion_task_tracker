import worker from "../src/index";
import { afterEach, describe, expect, it, vi } from "vitest";

const workerEnvironment = {
  GITHUB_OWNER: "alovya",
  GITHUB_REPOSITORY: "notion_task_tracker",
  GITHUB_API_VERSION: "2022-11-28",
  GITHUB_DISPATCH_EVENT_TYPE: "refresh-notion-tracker",
  GITHUB_DISPATCH_TOKEN: "github-token",
  NOTION_WEBHOOK_SECRET: "notion-secret",
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
