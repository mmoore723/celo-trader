import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const page = readFileSync(new URL("../src/pages/ScannerOpportunities.tsx", import.meta.url), "utf8");
const api = readFileSync(new URL("../src/lib/api.ts", import.meta.url), "utf8");

test("filter transitions expose loading rather than mislabeling old rows", () => {
  assert.match(page, /role="status"/);
  assert.match(page, /Loading your selection/);
  assert.match(page, /resultsQuery\.isPlaceholderData \? <PageLoader/);
  assert.match(page, /\|\| analyticsPending \? <PageLoader/);
  assert.match(page, /disabled=\{resultsQuery\.isFetching\}/);
});

test("research requests cancel superseded selections and poll refreshing snapshots", () => {
  assert.match(page, /queryFn: \(\{ pageParam, signal \}\)/);
  assert.match(api, /research-results\?\$\{params\}`, \{ signal \}/);
  assert.match(api, /research-analytics\?\$\{params\}`, \{ signal \}/);
  assert.equal((page.match(/snapshot\?\.refreshing \? 5_000 : 60_000/g) || []).length, 2);
  assert.match(page, /Results updated/);
});
