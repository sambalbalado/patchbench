# GPT-5 Mini `review-v2` baseline — 2026-09-22

PatchBench ran all 24 audited cases against `gpt-5-mini` with prompt `review-v2`. The corpus was
balanced between 12 defect-introducing patches and 12 safe patches. The run used four-request
concurrency after a single smoke case, a 60-second timeout, and zero retries.

The complete machine-readable result is in
[`results/gpt-5-mini-review-v2-baseline-2026-09-22.json`](../results/gpt-5-mini-review-v2-baseline-2026-09-22.json).

## Results

| Metric | `review-v1` (2026-09-11) | `review-v2` (2026-09-22) | Change |
| --- | ---: | ---: | ---: |
| Completed cases | 24 / 24 | 24 / 24 | — |
| API or parsing failures | 0 | 0 | — |
| Seeded bugs detected | 12 / 12 (100%) | 12 / 12 (100%) | — |
| Safe patches classified correctly | 8 / 12 (66.7%) | 10 / 12 (83.3%) | +16.6 pp |
| Detection accuracy | 20 / 24 (83.3%) | 22 / 24 (91.7%) | +8.4 pp |
| False-positive rate | 4 / 12 (33.3%) | 2 / 12 (16.7%) | -16.6 pp |
| Positive-case category accuracy | 6 / 12 (50%) | 12 / 12 (100%) | +50.0 pp |
| Positive-case file accuracy | 12 / 12 (100%) | 12 / 12 (100%) | — |
| Positive-case line accuracy | 12 / 12 (100%) | 12 / 12 (100%) | — |
| Overall rubric accuracy | 50 / 60 (83.3%) | 58 / 60 (96.7%) | +13.4 pp |
| Average latency | 16.59 seconds | 10.62 seconds | -5.97 seconds |
| Input tokens | 7,607 | 9,736 | +2,129 |
| Cached input tokens | 0 | 0 | — |
| Output tokens | 20,914 | 21,399 | +485 |
| Estimated cost | $0.04372975 | $0.04523200 | +$0.00150225 |

Percentage-point changes use the displayed rounded percentages, so some values differ by 0.1 from
changes calculated with the unrounded rates.

## Incorrect answers versus execution failures

There were no API, timeout, parsing, or schema-validation failures. Every seeded bug was detected,
and every positive finding used the canonical category, correct file, and an accepted line. The two
incorrect answers were false positives on safe changes:

- `safe_constant_time_compare`
- `safe_membership_refactor`

The historical `review-v1` run produced four false positives and six category mismatches. The
audited category contract removed those mismatches, while the revised prompt and cases reduced the
false-positive count by half.

## Interpretation

This is a representative completion run for Milestone 3: all 24 audited cases completed, the model
found every seeded bug, positive labels were stable, and false positives improved materially. The
remaining selectivity errors should stay visible as benchmark findings rather than block the next
milestone.

This is a versioned baseline comparison, not a controlled prompt-only experiment. Between the runs,
PatchBench constrained the category schema, audited expected labels, and clarified several safe
patches in addition to changing the prompt from `review-v1` to `review-v2`.

## Cost-control procedure

`division_by_zero` ran first as the smoke case. It completed successfully for an estimated
$0.00338750, after which PatchBench ran the other 23 cases with bounded concurrency. The smoke score
was reused in the aggregate and was not purchased twice. Retries were disabled, so the complete run
made exactly one request attempt per case and cost an estimated $0.04523200.

The estimate uses the repository's GPT-5 Mini pricing snapshot dated 2026-09-22: $0.25 per million
input tokens, $0.025 per million cached input tokens, and $2.00 per million output tokens.
