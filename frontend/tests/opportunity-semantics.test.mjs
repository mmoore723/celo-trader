import test from "node:test";
import assert from "node:assert/strict";
import {
  collapseOpportunityEpisodes, dedupeLatestEpisodes, isOperationalOpportunity, lifecycleCopy,
  opportunityDecisionTitle, opportunityLifecycle, opportunityReason,
} from "../src/lib/opportunitySemantics.js";

test("research observations cannot enter the operational feed", () => {
  const entry = { outcome: "observed_only", plan_status: "observation_only" };
  assert.equal(opportunityLifecycle(entry), "research");
  assert.equal(isOperationalOpportunity(entry), false);
});

test("full audit keeps the furthest lifecycle reached in each episode", () => {
  const rows = [
    { id: "new", episode_id: "episode-a", observed_at: "2026-08-14T10:02", lifecycle: "watching" },
    { id: "entered", episode_id: "episode-a", observed_at: "2026-08-14T10:01", lifecycle: "entered" },
  ];
  assert.deepEqual(collapseOpportunityEpisodes(rows).map((row) => row.id), ["entered"]);
});

test("contract progress is distinguished from a completed entry", () => {
  assert.equal(opportunityLifecycle({ outcome: "pending", plan_status: "contract_preview" }), "pricing");
  assert.equal(opportunityLifecycle({ outcome: "pending", plan_status: "contract_selected" }), "ready");
  assert.equal(lifecycleCopy({ outcome: "entered" }).badge, "ENTERED");
});

test("past entry cards show closed rather than implying an open position", () => {
  assert.equal(lifecycleCopy({ lifecycle: "entered", trade: { status: "CLOSED" } }).badge, "CLOSED");
  assert.equal(lifecycleCopy({ lifecycle: "entered", trade: { exit_time: "2026-10-12T14:30:00" } }).badge, "CLOSED");
  assert.equal(lifecycleCopy({ lifecycle: "entered", trade: { status: "OPEN" } }).badge, "OPEN");
  assert.equal(lifecycleCopy({ lifecycle: "entered" }).title, "Past Entry");
});

test("live preview collapses repeated detections from one episode", () => {
  const rows = [
    { id: "3", episode_id: "episode-b", outcome: "pending", plan_status: "contract_selected" },
    { id: "2", episode_id: "episode-a", outcome: "pending", plan_status: "contract_preview" },
    { id: "1", episode_id: "episode-a", outcome: "pending", plan_status: "not_priced" },
    { id: "r", episode_id: "research", outcome: "observed_only", plan_status: "observation_only" },
  ];
  assert.deepEqual(dedupeLatestEpisodes(rows, 3).map((row) => row.id), ["3", "2"]);
});

test("stale quote explanations do not invent a feed cause or threshold", () => {
  const entry = {
    outcome: "blocked",
    reason_code: "stale_entry_quote",
    reason_detail: "Tradier exact-contract quote was 904.1s old",
  };
  assert.equal(opportunityDecisionTitle(entry), "Skipped: option price was delayed");
  assert.match(opportunityReason(entry), /904\.1 seconds old/);
  assert.match(opportunityReason(entry), /rejected it as too old/);
  assert.doesNotMatch(opportunityReason(entry), /sandbox|120/);
});

test("SPY trend context blocks name the nearby price wall", () => {
  const entry = {
    outcome: "blocked",
    reason_code: "spy_trend_level_too_close",
    reason_detail: "The next resistance level was only 0.32 ATR away.",
  };
  assert.equal(opportunityDecisionTitle(entry), "Skipped: next price wall was too close");
  assert.match(opportunityReason(entry), /0\.32 ATR/);
});

test("saved premarket rejection is named plainly", () => {
 assert.equal(opportunityDecisionTitle({reason_code:"premarket_screen_rejected"}), "Not entered: premarket check failed");
});
