export function readRequiredString(
  body: Record<string, unknown>,
  fieldName: string,
): string {
  const value = body[fieldName];
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${fieldName} must be a non-empty string`);
  }
  return value;
}

export function readRequiredNumber(
  body: Record<string, unknown>,
  fieldName: string,
): number {
  const value = body[fieldName];
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${fieldName} must be a finite number`);
  }
  return value;
}
