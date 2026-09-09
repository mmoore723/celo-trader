import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const sidebar = readFileSync(new URL("../src/components/layout/Sidebar.tsx", import.meta.url), "utf8");
const opportunities = readFileSync(new URL("../src/pages/ScannerOpportunities.tsx", import.meta.url), "utf8");
const admin = readFileSync(new URL("../src/pages/Admin.tsx", import.meta.url), "utf8");

test("decisions and research have separate routes and plain-language purposes", () => {
  assert.match(app, /path="\/opportunities"[^\n]+view="decisions"/);
  assert.match(app, /path="\/research"[^\n]+view="research"/);
  assert.match(sidebar, /label: "Research Results", to: "\/research"/);
  assert.match(opportunities, /The Trade Journal starts after an order becomes a position/);
});

test("admin keeps unrebuilt saved strategy ideas compact and searchable", () => {
  assert.match(admin, /Strategies not rebuilt/);
  assert.match(admin, /!strategy\.research_supported/);
  assert.match(admin, /placeholder="Find a strategy"/);
  assert.match(admin, /<details className="card p-4">/);
});
