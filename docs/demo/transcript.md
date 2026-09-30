# PatchBench demo transcript

This transcript accompanies the short portfolio demonstration linked from the project README.
The dashboard shown in the video is the public, read-only deployment backed by the two versioned
baseline result files in this repository.

## Voiceover

AI code reviewers can look impressive while still missing real defects or inventing problems in
safe code. PatchBench turns that uncertainty into a reproducible benchmark. It runs a balanced set
of twelve buggy and twelve safe Python patches through a reviewer, validates every structured
response, and scores detection, category, file, and line accuracy separately from false positives.

Here, I am comparing two real saved GPT-5 Mini runs from the same benchmark version. The baseline
uses the `review-v1` prompt, and the candidate uses the audited `review-v2` prompt.

The headline result is clear. Overall rubric accuracy rises from 83.3 to 96.7 percent. Detection
accuracy improves by 8.3 percentage points, while the false-positive rate is cut in half, from 33.3
to 16.7 percent. Average latency also falls by almost six seconds, while estimated cost increases
by only about one tenth of a cent.

PatchBench also keeps the individual cases visible, so improvements and regressions cannot hide
behind one aggregate number. The public demo is read only, uses saved results, and cannot spend API
credits. Open the link in the README to explore every comparison.

## Evidence shown

- Baseline: `baseline-review-v1-2026-09-11`
- Candidate: `baseline-review-v2-2026-09-22`
- Benchmark: `default` at `coverage-v1`
- Public dashboard: <https://patchbench-demo.onrender.com/>

