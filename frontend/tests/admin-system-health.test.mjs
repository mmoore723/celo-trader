import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const admin = readFileSync(new URL("../src/pages/Admin.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8");

test("admin shows compact storage and CPU health together", () => {
  assert.match(admin, /aria-label="Server health"/);
  assert.match(admin, /Server storage/);
  assert.match(admin, /GB free/);
  assert.match(admin, /Server CPU/);
  assert.match(admin, /% busy/);
  assert.match(api, /cpu:\s*\{/);
  assert.match(api, /cores: number/);
});
