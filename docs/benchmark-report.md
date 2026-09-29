# PatchBench benchmark report

## Executive summary

PatchBench evaluates whether an AI code reviewer detects real defects without inventing defects in
safe changes. Its current corpus contains 24 labeled Python patches: 12 defect-introducing and 12
safe. The public comparison covers two complete `gpt-5-mini` runs.

The audited `review-v2` run detected all 12 seeded bugs, classified 10 of 12 safe patches correctly,
and raised no API or parsing failures. Compared with the historical `review-v1` run, its
false-positive rate fell from 33.3% to 16.7% and overall rubric accuracy rose from 83.3% to 96.7%.

## Experimental setup

| Property | Historical baseline | Audited candidate |
| --- | --- | --- |
| Date | 2026-09-11 | 2026-09-22 |
| Model | `gpt-5-mini` | `gpt-5-mini` |
| Prompt | `review-v1` | `review-v2` |
| Cases | 24 (12 buggy, 12 safe) | 24 (12 buggy, 12 safe) |
| Concurrency | 1 | 4 |
| Timeout | 60 seconds | 60 seconds |
| Retries | 0 | 0 |
| API/parsing failures | 0 | 0 |

The candidate began with `division_by_zero` as a smoke case. Its successful result was reused before
the remaining 23 cases ran with bounded concurrency, so the smoke case was not purchased twice.

## Scoring

A defect-introducing case has four equally weighted checks: correct detection, category, file, and
line. Line matches allow a ±2-line tolerance around the curated label. A safe case has one check:
the reviewer must report no bug. This asymmetry reflects the additional evidence required to make a
useful positive finding.

Detection accuracy covers all cases. False-positive rate uses only safe cases. Overall rubric
accuracy divides all earned checks by all possible checks. Execution failures are reported
separately and never converted into incorrect model answers.

## Results

| Metric | `review-v1` | `review-v2` | Change |
| --- | ---: | ---: | ---: |
| Completed cases | 24 / 24 | 24 / 24 | — |
| Seeded bugs detected | 12 / 12 | 12 / 12 | — |
| Safe patches classified correctly | 8 / 12 | 10 / 12 | +2 |
| Detection accuracy | 83.3% | 91.7% | +8.4 pp |
| False-positive rate | 33.3% | 16.7% | -16.6 pp |
| Positive-case category accuracy | 50.0% | 100.0% | +50.0 pp |
| Positive-case file accuracy | 100.0% | 100.0% | — |
| Positive-case line accuracy | 100.0% | 100.0% | — |
| Overall rubric accuracy | 83.3% | 96.7% | +13.4 pp |
| Average latency per case | 16.59 s | 10.62 s | -5.97 s |
| Input / output tokens | 7,607 / 20,914 | 9,736 / 21,399 | +2,129 / +485 |
| Estimated cost | $0.04372975 | $0.04523200 | +$0.00150225 |

Percentage-point changes use the displayed rounded rates. The machine-readable values remain in the
versioned result files.

## What improved

Both runs found every seeded defect and localized each positive finding to the correct file and an
accepted line. `review-v2` matched the canonical category on all 12 positive cases, compared with 6
of 12 in `review-v1`. False positives fell from four safe cases to two.

The remaining `review-v2` false positives were:

- `safe_constant_time_compare`
- `safe_membership_refactor`

These remain visible in the public dashboard as evaluation findings rather than being removed from
the corpus or hidden behind an aggregate score.

## Interpretation and limitations

The result shows that the audited configuration performed well on this specific balanced corpus.
It does not establish general code-review accuracy. The two runs are also not a controlled
prompt-only experiment: the category schema, expected labels, and some safe patches were clarified
between versions in addition to changing the prompt.

The corpus is small, synthetic, and Python-only. Each configuration has one recorded run, so this
report does not estimate stochastic variance or confidence intervals. It does not test multi-file
repository context, suggested-fix correctness, maintainability feedback, or whether a human accepts
the model's explanation. Latency and pricing are point-in-time observations.

PatchBench should therefore be used to compare explicitly versioned reviewer configurations and to
surface failure modes—not to justify autonomous approval or rejection of production changes.

## Reproducibility and evidence

- [Live comparison dashboard](https://patchbench-demo.onrender.com/)
- [`review-v1` raw result](../results/gpt-5-mini-review-v1-baseline-2026-09-11.json)
- [`review-v2` raw result](../results/gpt-5-mini-review-v2-baseline-2026-09-22.json)
- [`review-v1` run notes](baseline-2026-09-11.md)
- [`review-v2` run notes](baseline-review-v2-2026-09-22.md)
- [Coverage matrix](benchmark-coverage.md)
- [Independent label audit](label-audit-2026-09-20.md)

Automated tests use mocked model clients and make no paid requests. Re-run the deterministic offline
path with `patchbench`; run a paid live evaluation only after reviewing the corpus, model, smoke
case, retry budget, and current provider pricing.
