export function evidencePeriod(evidence: {period_start?: unknown; period_end?: unknown}) {
  const format = (value: unknown) => {
    const date = new Date(String(value ?? ''));
    return Number.isNaN(date.getTime()) ? null : date.toLocaleDateString('en-US', {timeZone: 'America/New_York', month: 'short', day: 'numeric', year: 'numeric'});
  };
  const start = format(evidence.period_start), end = format(evidence.period_end);
  return start && end ? `${start} to ${end}` : 'Test dates not recorded';
}
