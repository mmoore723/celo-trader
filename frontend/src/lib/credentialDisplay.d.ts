export function maskCredentialForDisplay(value: unknown): string;

export function loadCredentialDisplay<K extends string>(
  fields: readonly K[],
  secretFields: readonly K[],
  response: Partial<Record<K, unknown>>,
): {
  values: Record<K, string>;
  savedMasks: Partial<Record<K, string>>;
};
