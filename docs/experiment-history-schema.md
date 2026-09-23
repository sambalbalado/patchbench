# Experiment history schema

PatchBench stores experiment history in SQLite so later API and dashboard work can compare runs
without treating generated JSON files as a database. The first schema migration creates two source
tables and one derived view.

## Data model

### `runs`

One row represents one benchmark experiment. It records:

- identity, lifecycle status, and UTC timestamps;
- execution mode, model, prompt version, and concurrency/retry/timeout settings;
- benchmark name and version plus the source Git commit;
- the exact pricing snapshot used for cost estimates; and
- `configuration_json` for additional versioned settings that do not yet deserve first-class
  columns.

OpenAI runs require a model and prompt version. Pricing is stored as a complete snapshot or not at
all, which prevents a later rate change from rewriting historical cost meaning.

### `case_results`

One row represents a requested benchmark case within a run. The `(run_id, case_id)` primary key
prevents duplicates, while `(run_id, position)` preserves deterministic benchmark order. Each row
has exactly one outcome:

- `completed`: scoring fields are required; latency, usage, and cost remain optional for offline or
  unpriced runs;
- `failed`: error type and message are required, and failure latency may be recorded; or
- `skipped`: no score, error, or operational metrics are allowed.

Check constraints keep boolean values, scoring dimensions, token counts, and expected safe/buggy
shape consistent. Deleting a run cascades to its case rows.

### `run_summaries`

The view derives requested/completed/failed/skipped counts, detection and false-positive rates,
category/file/line accuracy, rubric accuracy, average latency, token totals, and estimated cost from
`case_results`. These values are intentionally not copied into `runs`, so aggregate data cannot
drift away from its source rows.

## Migration contract

Migration files use contiguous, zero-padded names such as `001_initial_history.sql`. The
`initialize_history` function:

1. enables SQLite foreign-key enforcement;
2. creates the `schema_migrations` ledger;
3. rejects gaps or unknown applied versions; and
4. applies each pending migration and its ledger entry in one transaction.

The SQL files ship as package data, so installed builds and source checkouts use the same schema.
Future changes should add `002_*.sql`, never edit an already released migration.

## Next integration boundary

The next roadmap task can build a small repository/service layer that maps `BenchmarkRun`,
`CaseScore`, and `CaseFailure` into these tables. FastAPI handlers should call that layer instead of
embedding SQL, and should read aggregate metrics from `run_summaries`.
