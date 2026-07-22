export interface WorkerEnvironment {
  GITHUB_OWNER: string;
  GITHUB_REPOSITORY: string;
  GITHUB_API_VERSION: string;
  GITHUB_DISPATCH_EVENT_TYPE: string;
  GITHUB_CALENDAR_DISPATCH_EVENT_TYPE: string;
  GITHUB_DISPATCH_TOKEN: string;
  NOTION_WEBHOOK_SECRET: string;
  CALENDAR_SYNC_ADMIN_TOKEN: string;
  CALENDAR_SYNC_STATE: D1Database;
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
