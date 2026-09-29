# Deploying the PatchBench demo

PatchBench's public deployment is intentionally read-only. Visitors can inspect and compare the
two versioned benchmark baselines, but `POST /runs` returns `403 Forbidden`. This boundary matters:
the live-run endpoint creates paid OpenAI requests and currently has no user authentication or
per-user budget control.

**Live service:** [https://patchbench-demo.onrender.com/](https://patchbench-demo.onrender.com/)

## Deployment record

The first public deployment was verified on 2026-09-29 from Git commit `65f9bae`. The smoke test
confirmed:

- `GET /`, `GET /health`, and `GET /runs?status=completed&limit=2` return `200`.
- History contains the seeded `review-v1` and `review-v2` baseline runs.
- Both result endpoints reconstruct all 24 completed cases.
- The health response reports `database: ready` and `live_runs_enabled: false`.
- `POST /runs` returns `403`, so public traffic cannot create paid OpenAI requests.

## Deployment model

The repository includes a Render Blueprint in `render.yaml`. It creates one free Python web
service in Singapore, binds PatchBench to Render's assigned `PORT`, monitors `/health`, and waits
for GitHub checks to pass before automatically deploying a new commit.

No `OPENAI_API_KEY` is configured or required. At startup, `patchbench-seed-demo` imports the two
committed baseline JSON files into SQLite. Seeding is idempotent, so service restarts do not create
duplicate history rows.

Render's free web-service filesystem is ephemeral and free services spin down after periods of
inactivity. That is acceptable for this read-only demonstration because the database is rebuilt
from versioned repository data on every start. It is not suitable for retaining newly executed
runs. See [Render's free-instance limitations](https://render.com/docs/free) before changing this
storage model.

## First deployment

1. Confirm the GitHub `Continuous integration` workflow passes on `main`.
2. In Render, create a new Blueprint and connect the PatchBench repository.
3. Review the Blueprint values and choose **Apply**. Keep the free plan selected.
4. Do not add `OPENAI_API_KEY`; the public demo does not need it.
5. Wait for the service health check to pass, then copy its public URL.

Render documents the account-side flow in [Deploy for Free](https://render.com/docs/free) and the
configuration format in the [Blueprint specification](https://render.com/docs/blueprint-spec).

## Public smoke test

Replace `$PATCHBENCH_URL` with the Render service URL and verify:

```bash
curl --fail "$PATCHBENCH_URL/health"
curl --fail "$PATCHBENCH_URL/runs?status=completed&limit=2"
curl --fail "$PATCHBENCH_URL/"
curl -i -X POST "$PATCHBENCH_URL/runs" \
  -H 'content-type: application/json' \
  -d '{"model":"gpt-5-mini"}'
```

The first three requests should return `200`. The run list should contain the `review-v1` and
`review-v2` baselines. The final request must return `403`; this confirms that a visitor cannot
trigger API spending.

## Rollback

If a deployment is unhealthy, open the service's **Events** page in Render, select the last known
good deploy, and redeploy it. Then repeat the smoke test. Render retains deploy history separately
from PatchBench's ephemeral SQLite file, while the selected Git revision supplies the matching
baseline files and seed code.

## Enabling live runs later

Do not enable live runs on a public service until authentication, rate limits, and a spending
budget are implemented. For a private environment, store `OPENAI_API_KEY` only in the host's secret
environment settings and set `PATCHBENCH_ALLOW_LIVE_RUNS=true`. Never put the key in `render.yaml`,
GitHub, a browser bundle, logs, or a committed `.env` file.
