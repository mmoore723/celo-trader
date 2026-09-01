/** Format a signed dollar amount without ever hiding a negative sign. */
export function formatSignedCurrency(value, decimals = 2) {
  const numeric = Number(value) || 0;
  const sign = numeric < 0 ? "-" : "+";
  return `${sign}$${Math.abs(numeric).toFixed(decimals)}`;
}
