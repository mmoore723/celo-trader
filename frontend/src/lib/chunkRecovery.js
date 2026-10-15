export function isChunkLoadError(error) {
  const message = String(error?.message ?? error ?? "");
  return /Failed to fetch dynamically imported module|Importing a module script failed|Loading chunk .* failed|Unable to preload CSS/i.test(message);
}

export function recoverPage(error, reload, reset) {
  if (isChunkLoadError(error)) reload();
  else reset();
}
