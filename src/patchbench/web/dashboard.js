"use strict";

const { compareCases } = window.PatchBenchComparison;

const elements = {
  baselineSelect: document.querySelector("#baseline-select"),
  candidateSelect: document.querySelector("#candidate-select"),
  statusPanel: document.querySelector("#status-panel"),
  statusTitle: document.querySelector("#status-title"),
  statusMessage: document.querySelector("#status-message"),
  retryButton: document.querySelector("#retry-button"),
  comparisonView: document.querySelector("#comparison-view"),
  warning: document.querySelector("#comparison-warning"),
  baselineName: document.querySelector("#baseline-name"),
  candidateName: document.querySelector("#candidate-name"),
  baselineDetails: document.querySelector("#baseline-details"),
  candidateDetails: document.querySelector("#candidate-details"),
  metricRows: document.querySelector("#metric-rows"),
  caseFilters: document.querySelector("#case-filters"),
  caseSummary: document.querySelector("#case-summary"),
  caseTableWrap: document.querySelector(".case-table-wrap"),
  caseRows: document.querySelector("#case-rows"),
  caseEmpty: document.querySelector("#case-empty"),
};

const state = {
  runs: [],
  comparisonController: null,
  retryAction: null,
  caseComparisons: [],
  caseFilter: "changes",
};

const changeLabels = {
  improved: "Improved",
  regressed: "Regressed",
  unchanged: "Unchanged",
  unavailable: "Unavailable",
};

const changeOrder = {
  regressed: 0,
  improved: 1,
  unchanged: 2,
  unavailable: 3,
};

const metricDefinitions = [
  {
    label: "Overall rubric accuracy",
    note: "All available scoring dimensions",
    intent: "higher",
    unit: "percentage",
    value: (run) => run.benchmark_run.summary?.total_accuracy ?? null,
  },
  {
    label: "Detection accuracy",
    note: "Correct safe-versus-buggy decisions",
    intent: "higher",
    unit: "percentage",
    value: (run) => run.benchmark_run.summary?.detection_accuracy ?? null,
  },
  {
    label: "False-positive rate",
    note: "Safe patches incorrectly flagged",
    intent: "lower",
    unit: "percentage",
    value: (run) => run.benchmark_run.summary?.false_positive_rate ?? null,
  },
  {
    label: "Category accuracy",
    note: "Completed buggy cases only",
    intent: "higher",
    unit: "percentage",
    value: (run) => averageBoolean(run, "category_correct"),
  },
  {
    label: "File accuracy",
    note: "Completed buggy cases only",
    intent: "higher",
    unit: "percentage",
    value: (run) => averageBoolean(run, "file_correct"),
  },
  {
    label: "Line accuracy",
    note: "Within the accepted line tolerance",
    intent: "higher",
    unit: "percentage",
    value: (run) => averageBoolean(run, "line_correct"),
  },
  {
    label: "Average latency",
    note: "Completed cases with timing data",
    intent: "lower",
    unit: "duration",
    value: (run) => run.benchmark_run.summary?.average_latency_ms ?? null,
  },
  {
    label: "Estimated cost",
    note: "Cases with a recorded pricing snapshot",
    intent: "context",
    unit: "currency",
    value: (run) => run.benchmark_run.summary?.total_estimated_cost_usd ?? null,
  },
  {
    label: "Completion",
    note: "Completed cases over requested cases",
    intent: "higher",
    unit: "completion",
    value: (run) => completionRatio(run),
  },
];

async function requestJson(path, signal) {
  const response = await fetch(path, {
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch {
      // The HTTP status remains a useful fallback when the body is not JSON.
    }
    throw new Error(detail);
  }
  return response.json();
}

function runId(record) {
  return record.metadata.run_id;
}

function compatible(left, right) {
  return (
    left.metadata.benchmark_name === right.metadata.benchmark_name &&
    left.metadata.benchmark_version === right.metadata.benchmark_version
  );
}

function runLabel(record) {
  const metadata = record.metadata;
  const when = formatDate(metadata.completed_at || metadata.created_at);
  const model = metadata.model || metadata.mode;
  const prompt = metadata.prompt_version || "no prompt version";
  return `${model} · ${prompt} · ${when} · ${runId(record).slice(0, 8)}`;
}

function formatDate(value) {
  if (!value) return "time unavailable";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function findDefaultPair(runs) {
  for (let candidateIndex = 0; candidateIndex < runs.length; candidateIndex += 1) {
    for (let baselineIndex = candidateIndex + 1; baselineIndex < runs.length; baselineIndex += 1) {
      if (compatible(runs[candidateIndex], runs[baselineIndex])) {
        return {
          baseline: runs[baselineIndex],
          candidate: runs[candidateIndex],
        };
      }
    }
  }
  return null;
}

function setOptions(select, runs, selectedId, placeholder) {
  select.replaceChildren();
  if (runs.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = placeholder;
    select.append(option);
    return;
  }
  for (const run of runs) {
    const option = document.createElement("option");
    option.value = runId(run);
    option.textContent = runLabel(run);
    option.selected = option.value === selectedId;
    select.append(option);
  }
}

function updateCandidateOptions(preferredId = null) {
  const baseline = state.runs.find((run) => runId(run) === elements.baselineSelect.value);
  if (!baseline) {
    setOptions(elements.candidateSelect, [], null, "Choose a baseline first");
    elements.candidateSelect.disabled = true;
    return;
  }
  const candidates = state.runs.filter(
    (run) => runId(run) !== runId(baseline) && compatible(run, baseline),
  );
  const selectedId = candidates.some((run) => runId(run) === preferredId)
    ? preferredId
    : candidates.length > 0
      ? runId(candidates[0])
      : null;
  setOptions(elements.candidateSelect, candidates, selectedId, "No compatible candidate");
  elements.candidateSelect.disabled = candidates.length === 0;
}

function showStatus(kind, title, message, retryAction = null) {
  elements.statusPanel.hidden = false;
  elements.statusPanel.dataset.kind = kind;
  elements.statusTitle.textContent = title;
  elements.statusMessage.textContent = message;
  elements.retryButton.hidden = retryAction === null;
  state.retryAction = retryAction;
}

function hideStatus() {
  elements.statusPanel.hidden = true;
  state.retryAction = null;
}

function showWarning(messages) {
  elements.warning.hidden = messages.length === 0;
  elements.warning.textContent = messages.join(" ");
}

function averageBoolean(run, key) {
  const cases = run.benchmark_run.summary?.cases || [];
  const values = cases
    .map((score) => score[key])
    .filter((value) => typeof value === "boolean");
  if (values.length === 0) return null;
  return values.filter(Boolean).length / values.length;
}

function completionRatio(run) {
  const benchmark = run.benchmark_run;
  if (benchmark.requested_cases === 0) return null;
  return benchmark.completed_cases / benchmark.requested_cases;
}

function sameCorpus(baseline, candidate) {
  const left = [...baseline.benchmark_run.case_order].sort();
  const right = [...candidate.benchmark_run.case_order].sort();
  return left.length === right.length && left.every((caseId, index) => caseId === right[index]);
}

function isPartial(run) {
  const benchmark = run.benchmark_run;
  return benchmark.failed_cases > 0 || benchmark.skipped_cases > 0;
}

function signed(value, digits) {
  const rounded = Math.abs(value) < 10 ** -digits / 2 ? 0 : value;
  return `${rounded > 0 ? "+" : ""}${rounded.toFixed(digits)}`;
}

function formatDuration(milliseconds) {
  if (milliseconds < 1000) return `${milliseconds.toFixed(0)} ms`;
  return `${(milliseconds / 1000).toFixed(2)} s`;
}

function formatValue(metric, value, run) {
  if (value === null || !Number.isFinite(value)) return "Not available";
  if (metric.unit === "percentage") return `${(value * 100).toFixed(1)}%`;
  if (metric.unit === "duration") return formatDuration(value);
  if (metric.unit === "currency") return `$${value.toFixed(4)}`;
  if (metric.unit === "completion") {
    return `${run.benchmark_run.completed_cases}/${run.benchmark_run.requested_cases}`;
  }
  return String(value);
}

function formatDelta(metric, delta, baseline, candidate) {
  if (metric.unit === "percentage") return `${signed(delta * 100, 1)} pp`;
  if (metric.unit === "duration") {
    return `${delta > 0 ? "+" : delta < 0 ? "−" : ""}${formatDuration(Math.abs(delta))}`;
  }
  if (metric.unit === "currency") {
    return `${delta > 0 ? "+" : delta < 0 ? "−" : ""}$${Math.abs(delta).toFixed(4)}`;
  }
  if (metric.unit === "completion") {
    const countDelta =
      candidate.benchmark_run.completed_cases - baseline.benchmark_run.completed_cases;
    return `${countDelta > 0 ? "+" : ""}${countDelta} cases`;
  }
  return signed(delta, 2);
}

function direction(metric, delta) {
  if (Math.abs(delta) < 1e-12) return { label: "No change", className: "neutral" };
  if (metric.intent === "context") {
    return {
      label: delta > 0 ? "Higher cost" : "Lower cost",
      className: "neutral",
    };
  }
  const improved = metric.intent === "higher" ? delta > 0 : delta < 0;
  return {
    label: improved ? "Improved" : "Regressed",
    className: improved ? "positive" : "negative",
  };
}

function metricRow(metric, baseline, candidate, allowDelta) {
  const baselineValue = metric.value(baseline);
  const candidateValue = metric.value(candidate);
  const hasValues =
    baselineValue !== null &&
    candidateValue !== null &&
    Number.isFinite(baselineValue) &&
    Number.isFinite(candidateValue);
  const delta = hasValues && allowDelta ? candidateValue - baselineValue : null;
  const outcome =
    delta === null
      ? { label: hasValues ? "Incompatible" : "Unavailable", className: "neutral" }
      : direction(metric, delta);

  const row = document.createElement("tr");
  row.innerHTML = `
    <td>
      <span class="metric-name"></span>
      <span class="metric-note"></span>
    </td>
    <td class="baseline-value"></td>
    <td class="candidate-value"></td>
    <td class="delta-value"></td>
    <td><span class="direction-pill"></span></td>
  `;
  row.querySelector(".metric-name").textContent = metric.label;
  row.querySelector(".metric-note").textContent = metric.note;
  row.querySelector(".baseline-value").textContent = formatValue(
    metric,
    baselineValue,
    baseline,
  );
  row.querySelector(".candidate-value").textContent = formatValue(
    metric,
    candidateValue,
    candidate,
  );
  row.querySelector(".delta-value").textContent =
    delta === null ? "—" : formatDelta(metric, delta, baseline, candidate);
  const pill = row.querySelector(".direction-pill");
  pill.textContent = outcome.label;
  pill.classList.add(outcome.className);
  return row;
}

function formatCorrectness(value) {
  if (value === null || value === undefined) return "Not applicable";
  return value ? "Correct" : "Incorrect";
}

function formatCaseScore(outcome) {
  if (outcome.status !== "completed") return null;
  const score = outcome.score;
  const percentage = outcome.ratio === null ? "Not available" : `${(outcome.ratio * 100).toFixed(1)}%`;
  return `${percentage} (${score.points_earned}/${score.points_possible})`;
}

function outcomeSummary(outcome) {
  if (outcome.status === "completed") return `Completed · ${formatCaseScore(outcome)}`;
  if (outcome.status === "failed") return `Failed · ${outcome.failure.error_type}`;
  if (outcome.status === "skipped") return "Skipped";
  return "Absent from run";
}

function changeSummary(change) {
  if (typeof change.delta === "number") {
    return `${change.reason} · ${signed(change.delta * 100, 1)} pp`;
  }
  return change.reason;
}

function addDefinition(list, term, value) {
  const group = document.createElement("div");
  const dt = document.createElement("dt");
  const dd = document.createElement("dd");
  dt.textContent = term;
  dd.textContent = value;
  group.append(dt, dd);
  list.append(group);
}

function evidenceFields(outcome) {
  if (outcome.status === "completed") {
    const score = outcome.score;
    return [
      ["Execution", "Completed"],
      ["Rubric score", formatCaseScore(outcome)],
      ["Detection", formatCorrectness(score.detection_correct)],
      ["Category", formatCorrectness(score.category_correct)],
      ["File", formatCorrectness(score.file_correct)],
      ["Line", formatCorrectness(score.line_correct)],
      ["False positive", score.false_positive ? "Yes" : "No"],
      ["Latency", score.latency_ms == null ? "Not available" : formatDuration(score.latency_ms)],
      [
        "Estimated cost",
        score.estimated_cost_usd == null
          ? "Not available"
          : `$${score.estimated_cost_usd.toFixed(4)}`,
      ],
    ];
  }
  if (outcome.status === "failed") {
    return [
      ["Execution", "Failed"],
      ["Error type", outcome.failure.error_type],
      ["Message", outcome.failure.message],
      [
        "Latency",
        outcome.failure.latency_ms == null
          ? "Not available"
          : formatDuration(outcome.failure.latency_ms),
      ],
    ];
  }
  if (outcome.status === "skipped") {
    return [
      ["Execution", "Skipped"],
      ["Evidence", "No model result was recorded for this case."],
    ];
  }
  return [
    ["Execution", "Absent"],
    ["Evidence", "This case is not part of this run's benchmark corpus."],
  ];
}

function evidencePanel(label, outcome) {
  const panel = document.createElement("article");
  panel.className = "case-evidence";
  const heading = document.createElement("h4");
  heading.textContent = label;
  const status = document.createElement("span");
  status.className = `outcome-pill ${outcome.status}`;
  status.textContent = outcome.status === "absent" ? "Absent" : outcome.status;
  const list = document.createElement("dl");
  for (const [term, value] of evidenceFields(outcome)) addDefinition(list, term, value);
  panel.append(heading, status, list);
  return panel;
}

function caseRows(comparison, index) {
  const row = document.createElement("tr");
  row.className = "case-row";

  const caseCell = document.createElement("th");
  caseCell.scope = "row";
  const caseName = document.createElement("code");
  caseName.textContent = comparison.caseId;
  caseCell.append(caseName);

  const baselineCell = document.createElement("td");
  baselineCell.textContent = outcomeSummary(comparison.baseline);
  const candidateCell = document.createElement("td");
  candidateCell.textContent = outcomeSummary(comparison.candidate);

  const changeCell = document.createElement("td");
  const changePill = document.createElement("span");
  changePill.className = `case-change ${comparison.change.status}`;
  changePill.textContent = changeLabels[comparison.change.status];
  const changeNote = document.createElement("span");
  changeNote.className = "case-change-note";
  changeNote.textContent = changeSummary(comparison.change);
  changeCell.append(changePill, changeNote);

  const actionCell = document.createElement("td");
  const detailId = `case-details-${index}`;
  const button = document.createElement("button");
  button.className = "case-detail-button";
  button.type = "button";
  button.setAttribute("aria-expanded", "false");
  button.setAttribute("aria-controls", detailId);
  button.textContent = "View evidence";
  actionCell.append(button);
  row.append(caseCell, baselineCell, candidateCell, changeCell, actionCell);

  const detailRow = document.createElement("tr");
  detailRow.id = detailId;
  detailRow.className = "case-detail-row";
  detailRow.hidden = true;
  const detailCell = document.createElement("td");
  detailCell.colSpan = 5;
  const grid = document.createElement("div");
  grid.className = "case-detail-grid";
  grid.append(
    evidencePanel("Baseline evidence", comparison.baseline),
    evidencePanel("Candidate evidence", comparison.candidate),
  );
  detailCell.append(grid);
  detailRow.append(detailCell);

  button.addEventListener("click", () => {
    const expanded = button.getAttribute("aria-expanded") === "true";
    button.setAttribute("aria-expanded", String(!expanded));
    button.textContent = expanded ? "View evidence" : "Hide evidence";
    detailRow.hidden = expanded;
  });

  return [row, detailRow];
}

function matchesCaseFilter(comparison, filter) {
  if (filter === "all") return true;
  if (filter === "changes") {
    return comparison.change.status === "regressed" || comparison.change.status === "improved";
  }
  return comparison.change.status === filter;
}

function renderCaseComparisons() {
  const counts = {
    all: state.caseComparisons.length,
    changes: 0,
    regressed: 0,
    improved: 0,
    unchanged: 0,
    unavailable: 0,
  };
  for (const comparison of state.caseComparisons) {
    counts[comparison.change.status] += 1;
    if (comparison.change.status === "regressed" || comparison.change.status === "improved") {
      counts.changes += 1;
    }
  }

  for (const button of elements.caseFilters.querySelectorAll("button[data-filter]")) {
    const filter = button.dataset.filter;
    button.setAttribute("aria-pressed", String(filter === state.caseFilter));
    button.querySelector("[data-count]").textContent = counts[filter];
  }

  const visible = state.caseComparisons
    .filter((comparison) => matchesCaseFilter(comparison, state.caseFilter))
    .sort(
      (left, right) =>
        changeOrder[left.change.status] - changeOrder[right.change.status] ||
        left.originalIndex - right.originalIndex,
    );
  elements.caseSummary.textContent = `${visible.length} of ${counts.all} cases shown · ${counts.regressed} regressed · ${counts.improved} improved`;
  elements.caseRows.replaceChildren(...visible.flatMap(caseRows));
  elements.caseTableWrap.hidden = visible.length === 0;
  elements.caseEmpty.hidden = visible.length !== 0;
}

function renderCases(baseline, candidate) {
  state.caseComparisons = compareCases(baseline, candidate);
  state.caseFilter = "changes";
  renderCaseComparisons();
}

function renderRunCard(run, nameElement, detailsElement) {
  const metadata = run.metadata;
  nameElement.textContent = `${metadata.model || metadata.mode} · ${metadata.prompt_version || "—"}`;
  const details = [
    ["Completed", formatDate(metadata.completed_at)],
    ["Run ID", metadata.run_id],
    ["Benchmark", `${metadata.benchmark_name} · ${metadata.benchmark_version}`],
    ["Source", metadata.source_commit || "Not recorded"],
  ];
  detailsElement.replaceChildren();
  for (const [term, value] of details) {
    const group = document.createElement("div");
    const dt = document.createElement("dt");
    const dd = document.createElement("dd");
    dt.textContent = term;
    dd.textContent = value;
    dd.title = value;
    group.append(dt, dd);
    detailsElement.append(group);
  }
}

function renderComparison(baseline, candidate) {
  const identityMatches = compatible(baseline, candidate);
  const corpusMatches = sameCorpus(baseline, candidate);
  const allowDelta = identityMatches && corpusMatches;
  const warnings = [];
  if (isPartial(baseline) || isPartial(candidate)) {
    warnings.push(
      "At least one run is partial. Quality metrics include completed cases only; review completion before trusting the delta.",
    );
  }
  if (!identityMatches) {
    warnings.push("These runs use different benchmark names or versions, so deltas are disabled.");
  } else if (!corpusMatches) {
    warnings.push("The case sets differ despite matching benchmark versions, so deltas are disabled.");
  }
  showWarning(warnings);
  renderRunCard(baseline, elements.baselineName, elements.baselineDetails);
  renderRunCard(candidate, elements.candidateName, elements.candidateDetails);
  elements.metricRows.replaceChildren(
    ...metricDefinitions.map((metric) => metricRow(metric, baseline, candidate, allowDelta)),
  );
  renderCases(baseline, candidate);
  elements.comparisonView.hidden = false;
  elements.comparisonView.setAttribute("aria-busy", "false");
}

async function compareSelections() {
  const baselineId = elements.baselineSelect.value;
  const candidateId = elements.candidateSelect.value;
  if (!baselineId || !candidateId) {
    elements.comparisonView.hidden = true;
    showStatus(
      "empty",
      "Choose two compatible runs",
      "A baseline and a different candidate are required before PatchBench can compare results.",
    );
    return;
  }

  state.comparisonController?.abort();
  const controller = new AbortController();
  state.comparisonController = controller;
  elements.comparisonView.setAttribute("aria-busy", "true");
  showStatus("loading", "Loading run results", "Keeping both selections visible while results load.");
  try {
    const [baseline, candidate] = await Promise.all([
      requestJson(`/runs/${encodeURIComponent(baselineId)}/results`, controller.signal),
      requestJson(`/runs/${encodeURIComponent(candidateId)}/results`, controller.signal),
    ]);
    renderComparison(baseline, candidate);
    hideStatus();
  } catch (error) {
    if (error.name === "AbortError") return;
    elements.comparisonView.hidden = true;
    showStatus(
      "error",
      "Could not load this comparison",
      error.message,
      compareSelections,
    );
  }
}

async function loadRuns() {
  elements.baselineSelect.disabled = true;
  elements.candidateSelect.disabled = true;
  elements.comparisonView.hidden = true;
  showStatus("loading", "Loading completed runs", "Reading experiment history from PatchBench.");
  try {
    state.runs = await requestJson("/runs?status=completed&limit=50");
    const pair = findDefaultPair(state.runs);
    if (!pair) {
      setOptions(elements.baselineSelect, state.runs, null, "No completed runs");
      setOptions(elements.candidateSelect, [], null, "No compatible candidate");
      elements.baselineSelect.disabled = state.runs.length === 0;
      showStatus(
        "empty",
        "Two compatible completed runs are required",
        "Complete another run with the same benchmark name and version, then return to compare it.",
        loadRuns,
      );
      return;
    }

    setOptions(elements.baselineSelect, state.runs, runId(pair.baseline), "No completed runs");
    elements.baselineSelect.disabled = false;
    updateCandidateOptions(runId(pair.candidate));
    await compareSelections();
  } catch (error) {
    showStatus("error", "Could not load experiment history", error.message, loadRuns);
  }
}

elements.baselineSelect.addEventListener("change", () => {
  updateCandidateOptions();
  compareSelections();
});
elements.candidateSelect.addEventListener("change", compareSelections);
elements.retryButton.addEventListener("click", () => state.retryAction?.());
elements.caseFilters.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-filter]");
  if (!button) return;
  state.caseFilter = button.dataset.filter;
  renderCaseComparisons();
});

loadRuns();
