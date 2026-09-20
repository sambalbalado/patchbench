# PatchBench

PatchBench is a reproducible evaluation harness for AI code reviewers. It answers a practical
question: **does an AI reviewer find real defects without inventing new ones?**

It runs labeled code patches through either saved predictions or a real OpenAI model, then measures
detection accuracy, category accuracy, location accuracy, false-positive rate, latency, token usage,
and estimated cost.

## Setup

PatchBench requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## Offline prediction mode

Offline mode is deterministic, free, and remains the default. It validates every saved prediction
against `ReviewResult` before scoring it.

```bash
patchbench
# Equivalent explicit command:
patchbench --benchmark benchmark --predictions examples/predictions.json
```

The prediction file must be a JSON object keyed by benchmark case ID. See
`examples/predictions.json` for the complete format.

## Real OpenAI review mode

Create an API key, choose a model that supports Structured Outputs, and export both values. The
example model can be replaced without changing code.

```bash
export OPENAI_API_KEY="your-api-key"
export PATCHBENCH_MODEL="gpt-5-mini"
patchbench --benchmark benchmark --openai --max-concurrency 4 --max-retries 1
```

You can copy `.env.example` as a reminder of the required variable names, but PatchBench does not
load `.env` files itself. The API key is read from the process environment, passed directly to the
OpenAI SDK, and is never written to results or printed.

Live mode sends each `patch.diff` to the OpenAI Responses API with bounded concurrency. Four
requests may run at once by default; `--max-concurrency` accepts values from 1 through 8. This
conservative ceiling speeds up experiments without allowing an accidental burst of unbounded paid
requests. The SDK constrains each response to the existing `ReviewResult` Pydantic schema, and
PatchBench validates it again before scoring. Requests set `store=False`, and each completed case
includes `latency_ms`, input tokens, cached input tokens, output tokens, and estimated cost.

The live JSON result records its concurrency, timeout, and retry configuration; the original
`case_order`; separate completed, failed, and skipped counts; structured per-case failures; skipped
case IDs; and an aggregate summary for completed cases. Workers may finish in any order, but
completed scores and failures are restored to benchmark order before output. One failed request
therefore does not discard successful reviews from other cases. The summary records the model,
prompt version, average latency, aggregate token counts, total estimated cost, and coverage counts
showing how many completed cases supplied usage and pricing data. Offline cases use `null` for
operational metrics because no model request occurred.

Each live request has a 60-second timeout and allows one retry by default. Retry selection
and exponential backoff are handled by the official OpenAI Python SDK: connection failures, request
timeouts, HTTP 408 and 409 responses, rate limits, and server errors are retryable. Invalid
structured responses, authentication failures, permission errors, and ordinary bad requests are
not retried. Use `--max-retries 0` for exactly one attempt per case, or `--max-retries 2` when
reliability matters more than the extra attempt. PatchBench caps this setting at two because retries
can increase runtime and may create additional paid requests.

Cost estimates use the standard per-million-token rates published in the
[official GPT-5 Mini model documentation](https://developers.openai.com/api/docs/models/gpt-5-mini),
recorded in the output with their source and an `as_of` date. PatchBench currently estimates cost
for `gpt-5-mini` and `gpt-5-mini-2025-08-07`. Other models still report token usage, but cost remains
`null` until a reviewed pricing entry is added; this avoids silently applying the wrong rate.

A timeout, API failure, refusal/missing structured output, or schema validation failure that remains
after the configured retry policy becomes a structured failure containing its case ID, error type,
message, and elapsed request time when available. Live mode makes at least one paid model request per
discovered benchmark case, so review the benchmark directory and retry setting before running it.

## Benchmark format

Each case contains a code patch and its expected finding:

```text
benchmark/
  division_by_zero/
    patch.diff
    expected.json
```

Safe patches are deliberately included. Without negative examples, a reviewer that reports a bug
for every change could appear successful.

The bundled benchmark now contains 24 Python patches, balanced between 12 defect-introducing and
12 safe changes. The positive cases cover distinct correctness, reliability, and security
categories including off-by-one behavior, mutable defaults, missing awaits, data loss, cache-key
collisions, SQL injection, path traversal, authorization bypass, sensitive-data exposure, unsafe
deserialization, and weak randomness. The safe cases include ordinary refactors as well as
security-hardening changes, which tests whether a reviewer understands the direction of a change
rather than merely reacting to security-sensitive code.

The [benchmark coverage matrix](docs/benchmark-coverage.md) classifies every case by technical
area and difficulty, records the exact expected finding, and defines deliberate targets for a
possible 30-case corpus. Its machine-readable source is
[`benchmark/coverage.json`](benchmark/coverage.json). Tests keep that metadata synchronized with
the case directories and `expected.json` labels.

The [2026-09-20 label audit](docs/label-audit-2026-09-20.md) independently reviews all 24 expected
answers. It also defines the canonical finding-category vocabulary used by the model response
schema and documents corrections made to ambiguous safe patches.

### Adding a benchmark case

Create a uniquely named directory under `benchmark/` and add both files. For a positive case,
`expected.json` must provide `category`, `file`, and `line`; the location must identify an added
line in `patch.diff`. For a safe case, all three fields must be `null`. Every patch must be a
well-formed unified diff with accurate hunk line counts.

The loader validates these rules before any prediction is scored or paid model request is made.
Add a matching entry to `examples/predictions.json` if the case should work with the default
offline demonstration.

## Development checks

All automated model tests use mocked clients and make no network or paid API calls.

```bash
pytest
ruff check .
```

## Design choices

- Offline and live execution are separate CLI modes but share the same loader, schema, evaluator,
  and output format.
- The bundled corpus is balanced between positive and negative cases and uses a distinct category
  for each current positive case.
- Ground-truth file and line labels are checked against parsed unified diffs during loading.
- Coverage metadata is schema-validated and checked against every bundled case and label.
- Finding categories are enum-constrained so wording differences cannot silently distort scores.
- Review results require complete finding details for bugs and prohibit contradictory details on
  safe decisions.
- `ReviewResult` is the single response contract. Extra fields and invalid field values are
  rejected rather than silently accepted.
- The model name is environment configuration so experiments can change models without code edits.
- Prompt and pricing versions are included in live summaries so benchmark runs remain interpretable.
- Latency uses a monotonic clock around every request and is retained even in raised request errors.
- Live requests use a bounded thread pool because model calls spend most of their time waiting for
  network I/O; result ordering is reconstructed after workers finish.
- The OpenAI SDK owns retry classification and backoff, while PatchBench limits the retry budget and
  turns exhausted failures into case-level records.
- The implementation remains in-memory; there is no frontend, database, or persistent worker system
  yet.

## First real baseline

The first complete live run evaluated all 24 bundled cases with `gpt-5-mini` and prompt
`review-v1`. It detected all 12 seeded bugs, produced four false positives across the 12 safe
patches, completed without API failures, and cost an estimated $0.04373. See the
[baseline report](docs/baseline-2026-09-11.md) and
[machine-readable result](results/gpt-5-mini-review-v1-baseline-2026-09-11.json) for the full
metrics and case-level scores.

## Roadmap

Milestones 1–2 are complete, and Milestone 3 now has a coverage matrix and an independent label
audit. One validation run remains before moving into experiment persistence. Next steps are:

1. Run a new `review-v2` baseline and compare it with the historical `review-v1` result.
2. Persist experiment runs through FastAPI and SQLite/Postgres.
3. Add a small dashboard for comparing configurations.

## License

PatchBench is available under the [MIT License](LICENSE).
