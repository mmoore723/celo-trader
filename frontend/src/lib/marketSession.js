const ET = "America/New_York";

function newYorkParts(value) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: ET,
    weekday: "short",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(value instanceof Date ? value : new Date(value));
  return Object.fromEntries(parts.map((part) => [part.type, part.value]));
}

/** Calendar key for the New York trading day, independent of browser locale. */
export function newYorkDateKey(value = new Date()) {
  const parts = newYorkParts(value);
  return `${parts.year}-${parts.month}-${parts.day}`;
}

/** A weekday session becomes final only at 4:00 p.m. New York time. */
export function isTradingDayFinal(value = new Date()) {
  const parts = newYorkParts(value);
  if (parts.weekday === "Sat" || parts.weekday === "Sun") return true;
  return Number(parts.hour) * 60 + Number(parts.minute) >= 16 * 60;
}
