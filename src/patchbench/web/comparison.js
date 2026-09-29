"use strict";

(function exposeComparisonLogic(factory) {
  const comparison = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = comparison;
  }
  if (typeof window !== "undefined") {
    window.PatchBenchComparison = comparison;
  }
})(function createComparisonLogic() {
  const COMPLETED = "completed";
  const FAILED = "failed";
  const SKIPPED = "skipped";
  const ABSENT = "absent";

  function scoreRatio(score) {
    const earned = Number(score.points_earned);
    const possible = Number(score.points_possible);
    if (!Number.isFinite(earned) || !Number.isFinite(possible) || possible <= 0) {
      return null;
    }
    return earned / possible;
  }

  function indexOutcomes(storedRun) {
    const benchmark = storedRun.benchmark_run;
    const outcomes = new Map();
    for (const score of benchmark.summary?.cases || []) {
      outcomes.set(score.case_id, {
        status: COMPLETED,
        score,
        ratio: scoreRatio(score),
      });
    }
    for (const failure of benchmark.failures || []) {
      outcomes.set(failure.case_id, { status: FAILED, failure });
    }
    for (const caseId of benchmark.skipped_case_ids || []) {
      outcomes.set(caseId, { status: SKIPPED });
    }
    return outcomes;
  }

  function unavailable(reason, corpusMismatch = false) {
    return { status: "unavailable", reason, corpusMismatch };
  }

  function classifyChange(baseline, candidate) {
    if (baseline.status === ABSENT || candidate.status === ABSENT) {
      return unavailable("Corpus mismatch", true);
    }

    if (baseline.status === COMPLETED && candidate.status === COMPLETED) {
      if (baseline.ratio === null || candidate.ratio === null) {
        return unavailable("Score unavailable");
      }
      const delta = candidate.ratio - baseline.ratio;
      if (Math.abs(delta) < 1e-12) {
        return { status: "unchanged", reason: "Same rubric score", delta };
      }
      return {
        status: delta > 0 ? "improved" : "regressed",
        reason: delta > 0 ? "Higher rubric score" : "Lower rubric score",
        delta,
      };
    }

    if (
      candidate.status === COMPLETED &&
      (baseline.status === FAILED || baseline.status === SKIPPED)
    ) {
      return {
        status: "improved",
        reason: `Recovered from ${baseline.status}`,
        delta: null,
      };
    }

    if (
      baseline.status === COMPLETED &&
      (candidate.status === FAILED || candidate.status === SKIPPED)
    ) {
      return {
        status: "regressed",
        reason: `Candidate ${candidate.status}`,
        delta: null,
      };
    }

    return unavailable("No completed result to compare");
  }

  function compareCases(baselineRun, candidateRun) {
    const baselineOutcomes = indexOutcomes(baselineRun);
    const candidateOutcomes = indexOutcomes(candidateRun);
    const orderedIds = [...baselineRun.benchmark_run.case_order];
    for (const caseId of candidateRun.benchmark_run.case_order) {
      if (!baselineOutcomes.has(caseId)) orderedIds.push(caseId);
    }

    return orderedIds.map((caseId, originalIndex) => {
      const baseline = baselineOutcomes.get(caseId) || { status: ABSENT };
      const candidate = candidateOutcomes.get(caseId) || { status: ABSENT };
      return {
        caseId,
        baseline,
        candidate,
        change: classifyChange(baseline, candidate),
        originalIndex,
      };
    });
  }

  return {
    compareCases,
    classifyChange,
    indexOutcomes,
    scoreRatio,
  };
});
