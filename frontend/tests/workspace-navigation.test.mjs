import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const sidebar = readFileSync(new URL("../src/components/layout/Sidebar.tsx", import.meta.url), "utf8");
const opportunities = readFileSync(new URL("../src/pages/ScannerOpportunities.tsx", import.meta.url), "utf8");
const admin = readFileSync(new URL("../src/pages/Admin.tsx", import.meta.url), "utf8");
const journal = readFileSync(new URL("../src/pages/Journal.tsx", import.meta.url), "utf8");
const dailyBrief = readFileSync(new URL("../src/pages/DailyBrief.tsx", import.meta.url), "utf8");
const performance = readFileSync(new URL("../src/pages/Performance.tsx", import.meta.url), "utf8");

test("bot decisions live inside the journal while research remains separate", () => {
  assert.match(app, /path="\/opportunities"[^\n]+Navigate to="\/journal\?tab=decisions"/);
  assert.match(app, /path="\/research"[^\n]+<Research/);
  const research = readFileSync(new URL("../src/pages/Research.tsx", import.meta.url), "utf8");
  assert.match(research, /<Results view="research" embedded/);
  assert.match(research, /Exit Lab/);
  assert.match(sidebar, /label: "Research Results", to: "\/research"/);
  assert.doesNotMatch(sidebar, /label: "Today's Decisions"/);
  assert.match(journal, /Bot Decisions/);
  assert.match(journal, /ScannerOpportunities view="decisions" embedded/);
  assert.match(opportunities, /See why the bot entered, could not fill, or skipped each setup/);
});

test("post-market history uses the selected trade ledger and performance stats share one row", () => {
  assert.match(dailyBrief, /const grade = dayGrade\(totalPnl\)/);
  assert.doesNotMatch(dailyBrief, /scorecard\.session_result\.grade/);
  assert.match(dailyBrief, /📊 Post-Market/);
  assert.doesNotMatch(dailyBrief, /Live Review/);
  assert.match(performance, /grid grid-cols-2 sm:grid-cols-4 gap-2/);
  assert.doesNotMatch(performance, /gridTemplateColumns: "repeat\(2,1fr\)"/);
});

test("admin keeps unrebuilt saved strategy ideas compact and searchable", () => {
  assert.match(admin, /Strategies not rebuilt/);
  assert.match(admin, /!strategy\.research_supported/);
  assert.match(admin, /placeholder="Find a strategy"/);
  assert.match(admin, /<details className="card p-4">/);
});
