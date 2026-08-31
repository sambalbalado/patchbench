# PatchBench

PatchBench is a reproducible evaluation harness for AI code reviewers. It answers a practical question: **does an AI reviewer find real defects without inventing new ones?**

Instead of judging an AI from a polished demo, PatchBench runs it against labeled code patches and measures detection accuracy, category accuracy, location accuracy, false-positive rate, latency, and cost.

## Why this project exists

AI-generated reviews are nondeterministic and can sound convincing when they are wrong. Teams need repeatable evidence before trusting them in a development workflow. PatchBench treats prompts and models as replaceable experiment configurations while keeping benchmark cases and scoring rules versioned.

## Current milestone

The starter version provides:

- A validated JSON contract for AI review results
- A version-controlled benchmark format
- Deterministic scoring with line-number tolerance
- False-positive measurement using safe code changes
- A command-line benchmark runner
- Unit tests that do not require paid model calls

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
patchbench --benchmark benchmark --predictions examples/predictions.json
pytest
```

The included prediction file simulates a model response so the complete evaluation loop can run offline.

## Benchmark case format

Each case contains a code patch and its expected finding:

```text
benchmark/
  division_by_zero/
    patch.diff
    expected.json
```

Safe patches are deliberately included. Without negative examples, a reviewer that reports a bug for every change could appear successful.

## Roadmap

1. Add an adapter for a real model with schema-constrained output.
2. Expand to 20–30 labeled Python patches.
3. Record prompt version, model, latency, token usage, and estimated cost.
4. Execute cases concurrently with bounded retries and timeouts.
5. Persist experiment runs through FastAPI and SQLite/Postgres.
6. Add a small dashboard for comparing configurations.

## Engineering principles

- Model providers are replaceable dependencies.
- Every response is validated before scoring.
- Evaluation is reproducible and version controlled.
- Deterministic checks are preferred when possible.
- Paid network calls are excluded from ordinary unit tests.

## License

Choose a license before accepting external contributions. MIT is a common option for portfolio projects.
