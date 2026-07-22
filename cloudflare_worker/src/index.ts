import { createJsonResponse } from "./create_http_response";
import { WorkerEnvironment } from "./environment";
import { advanceGoogleCalendarChangeCursor } from "./google_calendar/advance_google_calendar_change_cursor";
import { dispatchDailyGoogleCalendarRecovery } from "./google_calendar/dispatch_daily_google_calendar_recovery";
import { dispatchGoogleCalendarSynchronisation } from "./google_calendar/dispatch_google_calendar_synchronisation";
import { deleteGoogleCalendarEventMappingRoute } from "./google_calendar/delete_google_calendar_event_mapping";
import { markGoogleCalendarEventDeletedByNttRoute } from "./google_calendar/mark_google_calendar_event_deleted_by_ntt";
import { readGoogleCalendarSynchronisationState } from "./google_calendar/read_google_calendar_synchronisation_state";
import { readLatestGoogleCalendarNotificationChannel } from "./google_calendar/read_latest_google_calendar_notification_channel";
import { receiveGoogleCalendarNotification } from "./google_calendar/receive_google_calendar_notification";
import { recordActiveGoogleCalendarEvent } from "./google_calendar/record_active_google_calendar_event";
import { replaceGoogleCalendarEventLedgerSnapshot } from "./google_calendar/replace_google_calendar_event_ledger_snapshot";
import { recordGoogleCalendarNotificationChannel } from "./google_calendar/record_google_calendar_notification_channel";
import { dispatchNotionTaskTrackerChangeToGitHub } from "./notion/dispatch_notion_task_tracker_change_to_github";

const GOOGLE_CALENDAR_NOTIFICATION_PATH = "/google-calendar-notifications";
const GOOGLE_CALENDAR_NOTIFICATION_CHANNELS_PATH = "/google-calendar/notification-channels";
const GOOGLE_CALENDAR_CHANGE_CURSORS_PATH = "/google-calendar/change-cursors";
const GOOGLE_CALENDAR_SYNCHRONISATION_STATE_PATH = "/google-calendar/synchronisation-state";
const GOOGLE_CALENDAR_ACTIVE_EVENTS_PATH = "/google-calendar/event-ledger/active-events";
const GOOGLE_CALENDAR_NTT_DELETIONS_PATH = "/google-calendar/event-ledger/ntt-deletions";
const GOOGLE_CALENDAR_EVENT_MAPPINGS_PATH = "/google-calendar/event-ledger/events";
const GOOGLE_CALENDAR_EVENT_LEDGER_SNAPSHOT_PATH = "/google-calendar/event-ledger/snapshot";
const GOOGLE_CALENDAR_SYNCHRONISATION_DISPATCHES_PATH = "/google-calendar/synchronisation-dispatches";
const NOTION_TASK_TRACKER_CHANGES_PATH = "/notion-task-tracker-changes";

export default {
  async fetch(request: Request, environment: WorkerEnvironment): Promise<Response> {
    const requestPath = new URL(request.url).pathname;

    if (requestPath === GOOGLE_CALENDAR_NOTIFICATION_PATH) {
      return await receiveGoogleCalendarNotification(request, environment);
    }
    if (requestPath === GOOGLE_CALENDAR_NOTIFICATION_CHANNELS_PATH) {
      if (request.method === "GET") {
        return await readLatestGoogleCalendarNotificationChannel(request, environment);
      }
      if (request.method === "POST") {
        return await recordGoogleCalendarNotificationChannel(request, environment);
      }
      return createJsonResponse({ error: "Use GET or POST." }, 405, { Allow: "GET, POST" });
    }
    if (requestPath === GOOGLE_CALENDAR_CHANGE_CURSORS_PATH) {
      return await advanceGoogleCalendarChangeCursor(request, environment);
    }
    if (requestPath === GOOGLE_CALENDAR_SYNCHRONISATION_STATE_PATH) {
      return await readGoogleCalendarSynchronisationState(request, environment);
    }
    if (requestPath === GOOGLE_CALENDAR_ACTIVE_EVENTS_PATH) {
      return await recordActiveGoogleCalendarEvent(request, environment);
    }
    if (requestPath === GOOGLE_CALENDAR_NTT_DELETIONS_PATH) {
      return await markGoogleCalendarEventDeletedByNttRoute(request, environment);
    }
    if (requestPath === GOOGLE_CALENDAR_EVENT_MAPPINGS_PATH) {
      return await deleteGoogleCalendarEventMappingRoute(request, environment);
    }
    if (requestPath === GOOGLE_CALENDAR_EVENT_LEDGER_SNAPSHOT_PATH) {
      return await replaceGoogleCalendarEventLedgerSnapshot(request, environment);
    }
    if (requestPath === GOOGLE_CALENDAR_SYNCHRONISATION_DISPATCHES_PATH) {
      return await dispatchGoogleCalendarSynchronisation(request, environment);
    }
    if (requestPath === NOTION_TASK_TRACKER_CHANGES_PATH) {
      return await dispatchNotionTaskTrackerChangeToGitHub(request, environment);
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
