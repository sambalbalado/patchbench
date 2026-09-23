CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    mode TEXT NOT NULL CHECK (mode IN ('offline', 'openai')),
    benchmark_name TEXT NOT NULL,
    benchmark_version TEXT NOT NULL,
    source_commit TEXT,
    model TEXT,
    prompt_version TEXT,
    max_concurrency INTEGER CHECK (max_concurrency IS NULL OR max_concurrency >= 1),
    timeout_seconds REAL CHECK (timeout_seconds IS NULL OR timeout_seconds > 0),
    max_retries INTEGER CHECK (max_retries IS NULL OR max_retries >= 0),
    input_usd_per_million REAL CHECK (
        input_usd_per_million IS NULL OR input_usd_per_million >= 0
    ),
    cached_input_usd_per_million REAL CHECK (
        cached_input_usd_per_million IS NULL OR cached_input_usd_per_million >= 0
    ),
    output_usd_per_million REAL CHECK (
        output_usd_per_million IS NULL OR output_usd_per_million >= 0
    ),
    pricing_source TEXT,
    pricing_as_of TEXT,
    configuration_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    started_at TEXT,
    completed_at TEXT,
    CHECK (
        mode = 'offline'
        OR (mode = 'openai' AND model IS NOT NULL AND prompt_version IS NOT NULL)
    ),
    CHECK (
        (
            input_usd_per_million IS NULL
            AND cached_input_usd_per_million IS NULL
            AND output_usd_per_million IS NULL
            AND pricing_source IS NULL
            AND pricing_as_of IS NULL
        )
        OR (
            input_usd_per_million IS NOT NULL
            AND cached_input_usd_per_million IS NOT NULL
            AND output_usd_per_million IS NOT NULL
            AND pricing_source IS NOT NULL
            AND pricing_as_of IS NOT NULL
        )
    ),
    CHECK (
        (status IN ('queued', 'running') AND completed_at IS NULL)
        OR (status IN ('completed', 'failed') AND completed_at IS NOT NULL)
    )
);

CREATE TABLE case_results (
    run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    case_id TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    outcome TEXT NOT NULL CHECK (outcome IN ('completed', 'failed', 'skipped')),
    expected_bug_present INTEGER NOT NULL CHECK (expected_bug_present IN (0, 1)),
    detection_correct INTEGER CHECK (detection_correct IN (0, 1)),
    category_correct INTEGER CHECK (category_correct IN (0, 1)),
    file_correct INTEGER CHECK (file_correct IN (0, 1)),
    line_correct INTEGER CHECK (line_correct IN (0, 1)),
    false_positive INTEGER CHECK (false_positive IN (0, 1)),
    points_earned INTEGER CHECK (points_earned >= 0),
    points_possible INTEGER CHECK (points_possible >= 1),
    latency_ms REAL CHECK (latency_ms IS NULL OR latency_ms >= 0),
    input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
    cached_input_tokens INTEGER CHECK (
        cached_input_tokens IS NULL OR cached_input_tokens >= 0
    ),
    output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
    estimated_cost_usd REAL CHECK (estimated_cost_usd IS NULL OR estimated_cost_usd >= 0),
    error_type TEXT,
    error_message TEXT,
    PRIMARY KEY (run_id, case_id),
    UNIQUE (run_id, position),
    CHECK (
        (
            outcome = 'completed'
            AND detection_correct IS NOT NULL
            AND false_positive IS NOT NULL
            AND points_earned IS NOT NULL
            AND points_possible IS NOT NULL
            AND error_type IS NULL
            AND error_message IS NULL
        )
        OR (
            outcome = 'failed'
            AND detection_correct IS NULL
            AND category_correct IS NULL
            AND file_correct IS NULL
            AND line_correct IS NULL
            AND false_positive IS NULL
            AND points_earned IS NULL
            AND points_possible IS NULL
            AND input_tokens IS NULL
            AND cached_input_tokens IS NULL
            AND output_tokens IS NULL
            AND estimated_cost_usd IS NULL
            AND error_type IS NOT NULL
            AND error_message IS NOT NULL
        )
        OR (
            outcome = 'skipped'
            AND detection_correct IS NULL
            AND category_correct IS NULL
            AND file_correct IS NULL
            AND line_correct IS NULL
            AND false_positive IS NULL
            AND points_earned IS NULL
            AND points_possible IS NULL
            AND latency_ms IS NULL
            AND input_tokens IS NULL
            AND cached_input_tokens IS NULL
            AND output_tokens IS NULL
            AND estimated_cost_usd IS NULL
            AND error_type IS NULL
            AND error_message IS NULL
        )
    ),
    CHECK (
        outcome != 'completed'
        OR (
            (expected_bug_present = 1 AND category_correct IS NOT NULL
                AND file_correct IS NOT NULL AND line_correct IS NOT NULL
                AND points_possible = 4)
            OR (expected_bug_present = 0 AND category_correct IS NULL
                AND file_correct IS NULL AND line_correct IS NULL
                AND points_possible = 1)
        )
    ),
    CHECK (
        false_positive IS NULL
        OR false_positive = 0
        OR (expected_bug_present = 0 AND detection_correct = 0)
    ),
    CHECK (points_earned IS NULL OR points_earned <= points_possible),
    CHECK (
        (input_tokens IS NULL AND cached_input_tokens IS NULL AND output_tokens IS NULL)
        OR (input_tokens IS NOT NULL AND cached_input_tokens IS NOT NULL
            AND output_tokens IS NOT NULL AND cached_input_tokens <= input_tokens)
    )
);

CREATE VIEW run_summaries AS
SELECT
    runs.run_id,
    COUNT(case_results.case_id) AS requested_cases,
    SUM(CASE WHEN case_results.outcome = 'completed' THEN 1 ELSE 0 END) AS completed_cases,
    SUM(CASE WHEN case_results.outcome = 'failed' THEN 1 ELSE 0 END) AS failed_cases,
    SUM(CASE WHEN case_results.outcome = 'skipped' THEN 1 ELSE 0 END) AS skipped_cases,
    AVG(
        CASE WHEN case_results.outcome = 'completed' THEN case_results.detection_correct END
    ) AS detection_accuracy,
    AVG(
        CASE
            WHEN case_results.outcome = 'completed'
                AND case_results.expected_bug_present = 0
            THEN case_results.false_positive
        END
    ) AS false_positive_rate,
    AVG(
        CASE
            WHEN case_results.outcome = 'completed'
                AND case_results.expected_bug_present = 1
            THEN case_results.category_correct
        END
    ) AS category_accuracy,
    AVG(
        CASE
            WHEN case_results.outcome = 'completed'
                AND case_results.expected_bug_present = 1
            THEN case_results.file_correct
        END
    ) AS file_accuracy,
    AVG(
        CASE
            WHEN case_results.outcome = 'completed'
                AND case_results.expected_bug_present = 1
            THEN case_results.line_correct
        END
    ) AS line_accuracy,
    SUM(
        CASE WHEN case_results.outcome = 'completed' THEN case_results.points_earned END
    ) * 1.0 / NULLIF(SUM(
        CASE WHEN case_results.outcome = 'completed' THEN case_results.points_possible END
    ), 0) AS total_accuracy,
    AVG(
        CASE WHEN case_results.outcome = 'completed' THEN case_results.latency_ms END
    ) AS average_latency_ms,
    SUM(
        CASE WHEN case_results.outcome = 'completed' THEN case_results.input_tokens END
    ) AS total_input_tokens,
    SUM(
        CASE WHEN case_results.outcome = 'completed' THEN case_results.cached_input_tokens END
    ) AS total_cached_input_tokens,
    SUM(
        CASE WHEN case_results.outcome = 'completed' THEN case_results.output_tokens END
    ) AS total_output_tokens,
    SUM(
        CASE WHEN case_results.outcome = 'completed' THEN case_results.estimated_cost_usd END
    ) AS total_estimated_cost_usd,
    SUM(
        CASE
            WHEN case_results.outcome = 'completed'
                AND case_results.input_tokens IS NOT NULL
                AND case_results.output_tokens IS NOT NULL
            THEN 1 ELSE 0
        END
    ) AS usage_available_cases,
    SUM(
        CASE
            WHEN case_results.outcome = 'completed'
                AND case_results.estimated_cost_usd IS NOT NULL
            THEN 1 ELSE 0
        END
    ) AS cost_estimated_cases
FROM runs
LEFT JOIN case_results ON case_results.run_id = runs.run_id
GROUP BY runs.run_id;
