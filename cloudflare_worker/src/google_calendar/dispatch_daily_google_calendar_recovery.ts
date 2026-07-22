import { WorkerEnvironment } from "../environment";
import {
  createGitHubDispatchPayload,
  sendGitHubRepositoryDispatch,
} from "../github/send_github_repository_dispatch";
import { requireGoogleCalendarEnvironment } from "./authenticate_google_calendar_state_request";
import { listGoogleCalendarChangeCursors } from "./google_calendar_state_database";

export async function dispatchDailyGoogleCalendarRecovery(
  environment: WorkerEnvironment,
): Promise<void> {
  requireGoogleCalendarEnvironment(environment);
  const cursors = await listGoogleCalendarChangeCursors(environment.CALENDAR_SYNC_STATE);

  for (const cursor of cursors) {
    const dispatchPayload = createGitHubDispatchPayload(
      environment.GITHUB_CALENDAR_DISPATCH_EVENT_TYPE,
      cursor.tracker_user,
      undefined,
      cursor.sync_token,
    );
    const githubResponse = await sendGitHubRepositoryDispatch(
      environment.GITHUB_OWNER,
      environment.GITHUB_REPOSITORY,
      environment.GITHUB_API_VERSION,
      environment.GITHUB_DISPATCH_TOKEN,
      dispatchPayload,
    );
    if (!githubResponse.ok) {
      throw new Error(
        `Daily Calendar recovery dispatch failed for ${cursor.tracker_user}: ${githubResponse.status}`,
      );
    }
  }
}
