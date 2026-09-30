# PatchBench screenshot walkthrough

PatchBench asks one practical question: **does an AI reviewer find real defects without inventing
problems in safe code?**

![PatchBench dashboard comparing two saved benchmark runs](patchbench-dashboard.png)

## 1. Compare equivalent runs

The screenshot selects two real GPT-5 Mini results from the same `default` benchmark at
`coverage-v1`:

- Baseline: `baseline-review-v1-2026-09-11`
- Candidate: `baseline-review-v2-2026-09-22`

Keeping the benchmark version fixed makes the prompt comparison meaningful. Both runs completed all
24 cases: 12 patches with seeded defects and 12 safe patches.

## 2. Read the measured change

| Metric | `review-v1` | `review-v2` | Change |
| --- | ---: | ---: | ---: |
| Overall rubric accuracy | 83.3% | 96.7% | +13.3 percentage points |
| Detection accuracy | 83.3% | 91.7% | +8.3 percentage points |
| False-positive rate | 33.3% | 16.7% | -16.7 percentage points |
| Average latency | 16.59 s | 10.62 s | -5.97 s |
| Estimated cost | $0.0437 | $0.0452 | +$0.0015 |

The candidate was more accurate and faster on this corpus. Its estimated total cost increased by
about one tenth of a cent.

## 3. Inspect the evidence

The live dashboard continues below the screenshot with a case-level table. It aligns results by
case ID, identifies improvements and regressions, and expands each case to show scoring, latency,
cost, or execution-error evidence. This prevents a strong aggregate score from hiding individual
failures.

## Try the safe public demo

[Open the live PatchBench dashboard](https://patchbench-demo.onrender.com/). It uses saved results,
contains no OpenAI API key, and rejects attempts to create paid runs.

