# Run comparison experience

Status: selected for Milestone 5 implementation on 2026-09-28.

## Product decision

The first dashboard will answer one question: **did a candidate run improve on a baseline run, and
which cases changed?** It will compare exactly two persisted runs. The left run is the baseline and
the right run is the candidate, so every displayed delta is `candidate - baseline`.

This scope keeps PatchBench centered on evaluation quality. It does not add authentication,
experiment editing, arbitrary charts, live log streaming, or a general analytics system.

## User workflow

1. Open the comparison page.
2. PatchBench preselects the two most recent comparable completed runs when they exist.
3. Choose a different baseline or candidate from the run selectors.
4. Review headline quality, reliability, latency, and cost metrics with explicit deltas.
5. Filter the case table to regressions, improvements, unchanged cases, or unavailable outcomes.
6. Inspect a changed case's scoring dimensions and execution outcome.

The same run cannot occupy both selectors. Changing the baseline narrows the candidate selector to
runs with the same benchmark name and version. Model, prompt version, source commit, concurrency,
retry count, and smoke-case configuration are allowed to differ because those are the variables an
experiment is intended to compare.

Only terminal runs with saved case results appear in selectors. Queued and running experiments stay
on the run-status screen. Runs that failed before producing case results are not comparable.

## Layout

The desktop layout uses one reading column. On a narrow screen, selector cards and metric columns
stack without changing their order.

```text
+--------------------------------------------------------------------------+
| PatchBench                                      [Start another run]      |
| Compare two completed benchmark runs                                      |
+-----------------------------------+--------------------------------------+
| BASELINE                          | CANDIDATE                            |
| [review-v1 · 2026-09-11       v]  | [review-v2 · 2026-09-22        v]   |
| model · prompt · commit · cases   | model · prompt · commit · cases      |
+-----------------------------------+--------------------------------------+
| Overall rubric   83.3%  ->  96.7%    +13.4 pp   Improved                |
| Detection        83.3%  ->  91.7%     +8.4 pp   Improved                |
| False positives  33.3%  ->  16.7%    -16.6 pp   Improved                |
| File / line      100%   ->  100%       0.0 pp   No change               |
| Avg latency      16.59s ->  10.62s     -5.97s   Improved                |
| Est. cost        $0.0437 -> $0.0452    +$0.0015 Higher                  |
| Completion       24/24  ->  24/24       0       No change               |
+--------------------------------------------------------------------------+
| Cases  [Regressions] [Improvements] [Unchanged] [Unavailable]            |
| case                         baseline        candidate        change       |
| safe_path_validation         incorrect       correct          Improved    |
| safe_constant_time_compare   correct         incorrect        Regressed   |
+--------------------------------------------------------------------------+
```

The direction label is always written in text and is not communicated by color alone. Quality
metrics use percentage-point deltas. Latency, cost, and case counts use their native units.

## Metric definitions

Aggregate metrics use completed case scores only. Completion counts must remain visible beside the
quality metrics so a partial run cannot look better merely because difficult cases failed or were
skipped.

| Metric | Definition | Better direction | Unavailable when |
| --- | --- | --- | --- |
| Overall rubric accuracy | `sum(points_earned) / sum(points_possible)` across completed cases | Higher | No completed cases |
| Detection accuracy | Correct bug-present decisions divided by completed cases | Higher | No completed cases |
| False-positive rate | Safe completed cases incorrectly reported as buggy divided by safe completed cases | Lower | No safe completed cases |
| Category accuracy | Correct categories divided by completed buggy cases | Higher | No completed buggy cases |
| File accuracy | Correct files divided by completed buggy cases | Higher | No completed buggy cases |
| Line accuracy | Lines within the evaluator's accepted tolerance divided by completed buggy cases | Higher | No completed buggy cases |
| Average latency | Mean request latency among completed cases with latency data | Lower | No completed case has latency data |
| Estimated cost | Sum of case estimates that have a pricing snapshot | Lower, with context | No case has a cost estimate |
| Completion | Completed, failed, and skipped counts over requested cases | More completed and fewer failed/skipped | Never |

File and line accuracy remain separate because a model can identify the correct file but the wrong
line. The compact card may display them together as `file / line`, but both values and deltas remain
independently readable.

For every metric, the comparison shows both raw values before the delta. A missing value is rendered
as `Not available`, never as zero. Cost is labeled `Estimated cost` and retains enough decimal
precision to make small benchmark runs meaningful.

## Per-case change rules

Cases are aligned by `case_id`, not by list position. Each run contributes one of four outcomes:
completed, failed, skipped, or absent.

For two completed outcomes, compare `points_earned / points_possible`:

- **Improved**: candidate accuracy is greater than baseline accuracy.
- **Regressed**: candidate accuracy is lower than baseline accuracy.
- **Unchanged**: the two accuracies are equal.

The expanded row shows detection, category, file, and line correctness, plus latency and estimated
cost when available. This makes a category improvement visible even when detection was already
correct.

Outcome transitions use an explicit precedence instead of inventing scores for missing data:

- failed or skipped baseline to completed candidate: improved reliability;
- completed baseline to failed or skipped candidate: regression;
- failed/skipped/absent on both sides: unavailable;
- a case present on only one side: unavailable and labeled as a corpus mismatch.

The default filter shows regressions first, followed by improvements. Unchanged and unavailable
cases remain accessible but collapsed from the initial view.

## Comparison states

### Loading

- Disable selectors while the run list loads.
- After selection, keep the selector labels visible while both result payloads load.
- Do not show temporary zero values.

### Empty history

Explain that at least two completed, compatible runs are required. Offer a link to start a run; do
not present empty metric cards.

### No compatible candidate

Keep the selected baseline visible and explain that another run of the same benchmark name and
version is needed.

### Partial run

Show the comparison, but place a warning above the metrics and emphasize completed/failed/skipped
counts. Aggregate metrics continue to use only completed cases.

### Request or orchestration error

Show which run failed to load and allow retrying that request. Preserve the other selection. A run
that failed before producing cases remains available on its status page but not in comparison
selectors.

### Incompatible or corrupt data

If two selected runs have different benchmark identities, disable metric deltas and ask for a
compatible selection. If the benchmark name and version match but case sets differ, show the corpus
mismatch, compare their intersection only at the case level, and suppress aggregate deltas.

## Minimal data contract

The current result endpoint already provides every selected-run value needed for metrics and
case-level comparison:

```text
GET /runs/{run_id}/results
```

The dashboard will derive category, file, and line accuracy from `benchmark_run.summary.cases`.
This avoids storing a second copy of aggregates or adding a dedicated server-side comparison
endpoint.

Selectable runs are discovered through:

```text
GET /runs?status=completed&limit=50
```

The response contains `RunRecord` values ordered by creation time, newest first, with run ID as a
deterministic tie-breaker. The first version supports a `limit` from 1 through 100 and an optional
exact status filter; cursor pagination and free-text search are out of scope. The repository, not
the HTTP handler, owns the query and ordering.

The browser then:

1. loads the run list;
2. chooses two compatible records;
3. fetches the existing result endpoint for each selection; and
4. computes presentation-only deltas without additional API calls.

## Accessibility and formatting

- Selector labels include model, prompt version, completion timestamp, and short run ID.
- Every status and delta has a text label in addition to color or an icon.
- Percentages show one decimal place; currency shows at least four decimal places; latency uses
  milliseconds below one second and seconds otherwise.
- Tables remain keyboard navigable, and expanded case details follow their owning row in focus order.
- Raw error messages are shown as text and never interpreted as markup.

## Out of scope for the first dashboard

- More than two runs at once.
- Editing, deleting, or rerunning historical experiments.
- Live progress logs or per-case streaming.
- Statistical significance claims.
- Authentication and multi-user history.
- Charts that duplicate the metric table without adding information.
- A new server-side comparison or aggregate-storage layer.

## Implementation sequence

1. ~~Add the bounded run-list repository method and `GET /runs` endpoint.~~ Complete.
2. Build the baseline/candidate selectors and headline metric comparison.
3. Add the filterable per-case change table and complete the defined interface states.

Each step is independently testable and should remain a separate development-day commit.

## Acceptance checklist

- [x] The user can select a baseline and candidate run.
- [x] Accuracy, false positives, location quality, latency, cost, and completion have exact formulas.
- [x] Per-case improvements, regressions, unchanged cases, and unavailable outcomes are defined.
- [x] Loading, empty, partial, error, and incompatibility states are specified.
- [x] The written wireframe fixes information hierarchy without prescribing a heavy visual system.
- [x] The bounded run-list backend dependency is implemented and tested.
