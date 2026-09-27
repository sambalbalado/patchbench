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

## Repository contract

`HistoryRepository` is the only application layer that translates between SQLite rows and the
existing benchmark models. Saving a terminal run inserts its metadata and every completed, failed,
or skipped case in one transaction. If any case violates a database constraint, SQLite rolls back
the run row and all preceding case rows.

`get_run` reconstructs the ordered `BenchmarkRun` and its typed `RunMetadata`. It uses
`run_summaries` for aggregate values instead of trusting a copied summary. `get_summary` exposes the
same derived metrics directly for future API consumers. Missing run IDs return `None`.

Persistence remains opt-in: neither offline scoring nor live model execution opens a database. The
caller owns the SQLite connection and decides when a completed run should be stored.

## Next integration boundary

FastAPI handlers can now call `HistoryRepository` rather than embedding SQL. The API layer still
needs to create run identifiers and timezone-aware timestamps, execute work outside request
handlers, and expose run status and stored results.
