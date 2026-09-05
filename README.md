# PatchBench

PatchBench is a reproducible evaluation harness for AI code reviewers. It answers a practical
question: **does an AI reviewer find real defects without inventing new ones?**

It runs labeled code patches through either saved predictions or a real OpenAI model, then measures
detection accuracy, category accuracy, location accuracy, false-positive rate, and per-request
latency.

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
patchbench --benchmark benchmark --openai
```

You can copy `.env.example` as a reminder of the required variable names, but PatchBench does not
load `.env` files itself. The API key is read from the process environment, passed directly to the
OpenAI SDK, and is never written to results or printed.

Live mode sends each `patch.diff` to the OpenAI Responses API synchronously. The SDK constrains the
response to the existing `ReviewResult` Pydantic schema, and PatchBench validates it again before
scoring. Requests set `store=False`, and each case in the JSON summary includes `latency_ms`;
offline cases use `null` because no model request occurred.

The request timeout is 60 seconds. A timeout, API failure, refusal/missing structured output, or
schema validation failure stops the run with the case ID, a clear error, and elapsed request time.
There are intentionally no retries or concurrent workers in this milestone, so paid calls are
predictable and failures are visible. Live mode makes one paid model request per discovered
benchmark case, so review the benchmark directory before running it.

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
- `ReviewResult` is the single response contract. Extra fields and invalid field values are
  rejected rather than silently accepted.
- The model name is environment configuration so experiments can change models without code edits.
- Latency uses a monotonic clock around every request and is retained even in raised request errors.
- The implementation is deliberately synchronous and in-memory; there is no frontend, database,
  or worker system yet.

## Roadmap

The first dataset milestone is complete: PatchBench includes 24 validated and balanced labeled
Python patches. Next steps are:

1. Record prompt version, token usage, and estimated cost.
2. Execute cases concurrently with bounded retries and timeouts.
3. Persist experiment runs through FastAPI and SQLite/Postgres.
4. Add a small dashboard for comparing configurations.

## License

PatchBench is available under the [MIT License](LICENSE).
