"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
  classifyChange,
  compareCases,
  indexOutcomes,
  scoreRatio,
} = require("../src/patchbench/web/comparison.js");

function score(caseId, earned, possible = 4) {
  return {
    case_id: caseId,
    points_earned: earned,
    points_possible: possible,
  };
}

function storedRun({ completed = [], failures = [], skipped = [], order = null }) {
  const caseOrder = order || [
    ...completed.map((item) => item.case_id),
    ...failures.map((item) => item.case_id),
    ...skipped,
  ];
  return {
    benchmark_run: {
      case_order: caseOrder,
      failures,
      skipped_case_ids: skipped,
      summary: { cases: completed },
    },
  };
}

test("case outcomes align by case_id instead of result position", () => {
  const baseline = storedRun({
    completed: [score("alpha", 1), score("beta", 4)],
    order: ["alpha", "beta"],
  });
  const candidate = storedRun({
    completed: [score("beta", 2), score("alpha", 4)],
    order: ["beta", "alpha"],
  });

  const comparisons = compareCases(baseline, candidate);

  assert.deepEqual(
    comparisons.map(({ caseId, change }) => [caseId, change.status]),
    [
      ["alpha", "improved"],
      ["beta", "regressed"],
    ],
  );
});

test("completed outcomes classify higher, lower, and equal rubric scores", () => {
  assert.equal(
    classifyChange(
      { status: "completed", ratio: 0.25 },
      { status: "completed", ratio: 0.75 },
    ).status,
    "improved",
  );
  assert.equal(
    classifyChange(
      { status: "completed", ratio: 0.75 },
      { status: "completed", ratio: 0.25 },
    ).status,
    "regressed",
  );
  assert.equal(
    classifyChange(
      { status: "completed", ratio: 0.5 },
      { status: "completed", ratio: 0.5 },
    ).status,
    "unchanged",
  );
});

test("execution recovery and loss classify as reliability changes", () => {
  assert.deepEqual(
    classifyChange({ status: "failed" }, { status: "completed", ratio: 1 }),
    { status: "improved", reason: "Recovered from failed", delta: null },
  );
  assert.deepEqual(
    classifyChange({ status: "completed", ratio: 1 }, { status: "skipped" }),
    { status: "regressed", reason: "Candidate skipped", delta: null },
  );
  assert.equal(classifyChange({ status: "failed" }, { status: "skipped" }).status, "unavailable");
});

test("one-sided cases stay visible as unavailable corpus mismatches", () => {
  const baseline = storedRun({ completed: [score("shared", 4)] });
  const candidate = storedRun({ completed: [score("shared", 4), score("new-case", 4)] });

  const comparisons = compareCases(baseline, candidate);
  const mismatch = comparisons.find(({ caseId }) => caseId === "new-case");

  assert.equal(mismatch.baseline.status, "absent");
  assert.deepEqual(mismatch.change, {
    status: "unavailable",
    reason: "Corpus mismatch",
    corpusMismatch: true,
  });
});

test("outcome indexing preserves failure evidence and rejects invalid score ratios", () => {
  const failure = {
    case_id: "failed-case",
    error_type: "TimeoutError",
    message: "request timed out",
    latency_ms: 60000,
  };
  const outcomes = indexOutcomes(storedRun({ failures: [failure] }));

  assert.equal(outcomes.get("failed-case").failure, failure);
  assert.equal(scoreRatio(score("invalid", 0, 0)), null);
});
