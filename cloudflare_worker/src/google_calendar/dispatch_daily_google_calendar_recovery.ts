import { WorkerEnvironment } from "../environment";
import {
  createGitHubDispatchPayload,
  sendGitHubRepositoryDispatch,
} from "../github/send_github_repository_dispatch";
import { requireGoogleCalendarEnvironment } from "./authenticate_google_calendar_state_request";
import { listGoogleCalendarTrackerIdentities } from "./google_calendar_state_database";

export async function dispatchDailyGoogleCalendarRecovery(
  environment: WorkerEnvironment,
): Promise<void> {
  requireGoogleCalendarEnvironment(environment);
  const trackers = await listGoogleCalendarTrackerIdentities(
    environment.GOOGLE_CALENDAR_STATE_DATABASE,
  );

  for (const tracker of trackers) {
    const dispatchPayload = createGitHubDispatchPayload(
      environment.GITHUB_GOOGLE_CALENDAR_CHANGE_EVENT_TYPE,
      tracker.tracker_user,
    );
    const githubResponse = await sendGitHubRepositoryDispatch(
      environment.GITHUB_OWNER,
      environment.GITHUB_REPOSITORY,
      environment.GITHUB_API_VERSION,
      environment.GITHUB_REPOSITORY_DISPATCH_TOKEN,
      dispatchPayload,
    );
    if (!githubResponse.ok) {
      throw new Error(
        `Daily Calendar recovery dispatch failed for ${tracker.tracker_user}: ${githubResponse.status}`,
      );
    }
  }
}
