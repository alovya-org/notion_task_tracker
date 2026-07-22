import { createJsonResponse } from "./create_http_response";
import { WorkerEnvironment } from "./environment";
import { advanceGoogleCalendarChangeCursor } from "./google_calendar/advance_google_calendar_change_cursor";
import { dispatchDailyGoogleCalendarRecovery } from "./google_calendar/dispatch_daily_google_calendar_recovery";
import { readLatestGoogleCalendarNotificationChannel } from "./google_calendar/read_latest_google_calendar_notification_channel";
import { receiveGoogleCalendarNotification } from "./google_calendar/receive_google_calendar_notification";
import { recordGoogleCalendarNotificationChannel } from "./google_calendar/record_google_calendar_notification_channel";
import { dispatchNotionTaskChangeToGitHub } from "./notion/dispatch_notion_task_change_to_github";

const GOOGLE_CALENDAR_NOTIFICATION_PATH = "/google-calendar-notifications";
const CALENDAR_CHANNEL_REGISTRATION_PATH = "/calendar-sync-state/channels";
const CALENDAR_CURSOR_ADVANCEMENT_PATH = "/calendar-sync-state/cursors";
const NOTION_TASK_CHANGES_PATH = "/notion-task-changes";

export default {
  async fetch(request: Request, environment: WorkerEnvironment): Promise<Response> {
    const requestPath = new URL(request.url).pathname;

    if (requestPath === GOOGLE_CALENDAR_NOTIFICATION_PATH) {
      return await receiveGoogleCalendarNotification(request, environment);
    }
    if (requestPath === CALENDAR_CHANNEL_REGISTRATION_PATH) {
      if (request.method === "GET") {
        return await readLatestGoogleCalendarNotificationChannel(request, environment);
      }
      if (request.method === "POST") {
        return await recordGoogleCalendarNotificationChannel(request, environment);
      }
      return createJsonResponse({ error: "Use GET or POST." }, 405, { Allow: "GET, POST" });
    }
    if (requestPath === CALENDAR_CURSOR_ADVANCEMENT_PATH) {
      return await advanceGoogleCalendarChangeCursor(request, environment);
    }
    if (requestPath === NOTION_TASK_CHANGES_PATH) {
      return await dispatchNotionTaskChangeToGitHub(request, environment);
    }
    return createJsonResponse({ error: "Not found." }, 404);
  },

  async scheduled(
    _controller: ScheduledController,
    environment: WorkerEnvironment,
  ): Promise<void> {
    await dispatchDailyGoogleCalendarRecovery(environment);
  },
};
