export function learningLink(strategy: string, ticker: string, version: string, view: string) {
  return `/playbooks?${new URLSearchParams({ strategy, ticker, version, view })}`;
}
