export interface WorkerEnvironment {
  GITHUB_OWNER: string;
  GITHUB_REPOSITORY: string;
  GITHUB_API_VERSION: string;
  GITHUB_NOTION_TASK_TRACKER_CHANGE_EVENT_TYPE: string;
  GITHUB_GOOGLE_CALENDAR_CHANGE_EVENT_TYPE: string;
  GITHUB_REPOSITORY_DISPATCH_TOKEN: string;
  NOTION_WEBHOOK_SECRET: string;
  NTT_GOOGLE_CALENDAR_STATE_API_TOKEN: string;
  GOOGLE_CALENDAR_STATE_DATABASE: D1Database;
}

export function requireEnvironmentVariables(
  environment: WorkerEnvironment,
  requiredEnvironmentVariableNames: Array<keyof WorkerEnvironment>,
): void {
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
