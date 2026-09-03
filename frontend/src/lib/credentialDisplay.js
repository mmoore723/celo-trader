export function maskCredentialForDisplay(value) {
  const text = String(value ?? "").trim();
  if (!text) return "";
  return text.length >= 10 ? `${text.slice(0, 4)}…${text.slice(-4)}` : "set";
}

export function loadCredentialDisplay(fields, secretFields, response) {
  const secrets = new Set(secretFields);
  const values = {};
  const savedMasks = {};

  for (const field of fields) {
    const value = String(response?.[field] ?? "");
    if (secrets.has(field)) {
      // GET /credentials deliberately returns only a display mask. Never put
      // that mask into an editable input where it could be submitted later.
      values[field] = "";
      savedMasks[field] = value;
    } else {
      values[field] = value;
    }
  }
  return { values, savedMasks };
}
