/** Match execution precedence without rewriting stored values on panel open. */
export function effectiveExecution(defaults, overrides, selected, replacement = false) {
  const result = Object.fromEntries(Object.entries(defaults).map(([section, fields]) => [section, {
    ...fields,
    ...(section === 'contract' && selected?.contract_policy ? {primary_policy: selected.contract_policy} : {}),
    ...(section === 'native_exit' && selected?.exit_minutes != null ? {hold_minutes: selected.exit_minutes} : {}),
    ...overrides[section],
  }]));
  if (replacement) result.native_exit = {};
  return result;
}
