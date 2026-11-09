-- Canonical five-table schema from docs/02, plus its core indexes.

CREATE TABLE agents (
    agent_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    name VARCHAR(100) NOT NULL,
    role VARCHAR(50) NOT NULL,

    provider VARCHAR(80),
    model_name VARCHAR(120),

    status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'DISABLED')),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


CREATE TABLE tasks (
    task_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    title VARCHAR(200) NOT NULL,
    description TEXT,

    scenario_type VARCHAR(50) NOT NULL DEFAULT 'GENERAL',

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


CREATE TABLE runs (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    task_id UUID NOT NULL
        REFERENCES tasks(task_id) ON DELETE RESTRICT,

    trace_id VARCHAR(32) NOT NULL UNIQUE
        CHECK (trace_id ~ '^[0-9a-f]{32}$'),

    source_type VARCHAR(12) NOT NULL
        CHECK (source_type IN ('SIMULATED', 'REAL')),

    status VARCHAR(12) NOT NULL DEFAULT 'RUNNING'
        CHECK (
            status IN (
                'RUNNING',
                'SUCCESS',
                'FAILED',
                'CANCELLED'
            )
        ),

    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,

    error_summary TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (
        ended_at IS NULL OR ended_at >= started_at
    ),

    CHECK (
        (status = 'RUNNING' AND ended_at IS NULL)
        OR
        (status IN ('SUCCESS', 'FAILED', 'CANCELLED')
         AND ended_at IS NOT NULL)
    )
);


CREATE TABLE spans (
    span_pk BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    run_id UUID NOT NULL
        REFERENCES runs(run_id) ON DELETE CASCADE,

    span_id VARCHAR(16) NOT NULL
        CHECK (span_id ~ '^[0-9a-f]{16}$'),

    parent_span_id VARCHAR(16),

    agent_id UUID
        REFERENCES agents(agent_id) ON DELETE SET NULL,

    operation_type VARCHAR(20) NOT NULL
        CHECK (
            operation_type IN (
                'AGENT',
                'LLM',
                'TOOL',
                'RETRIEVAL',
                'WORKFLOW',
                'OTHER'
            )
        ),

    span_name VARCHAR(200) NOT NULL,

    status VARCHAR(10) NOT NULL
        CHECK (status IN ('SUCCESS', 'ERROR')),

    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,

    provider VARCHAR(80),
    model_name VARCHAR(120),
    tool_name VARCHAR(120),

    input_tokens INTEGER
        CHECK (input_tokens IS NULL OR input_tokens >= 0),

    output_tokens INTEGER
        CHECK (output_tokens IS NULL OR output_tokens >= 0),

    error_type VARCHAR(100),
    error_message TEXT,

    attributes JSONB NOT NULL DEFAULT '{}'::JSONB
        CHECK (jsonb_typeof(attributes) = 'object'),

    CONSTRAINT uq_run_span UNIQUE (run_id, span_id),

    CONSTRAINT fk_span_parent
        FOREIGN KEY (run_id, parent_span_id)
        REFERENCES spans(run_id, span_id)
        ON DELETE CASCADE
        DEFERRABLE INITIALLY DEFERRED,

    CHECK (end_time >= start_time),

    CHECK (
        parent_span_id IS NULL
        OR parent_span_id <> span_id
    )
);


CREATE TABLE span_events (
    event_id UUID PRIMARY KEY,

    run_id UUID NOT NULL,
    span_id VARCHAR(16) NOT NULL,

    event_name VARCHAR(100) NOT NULL,

    severity VARCHAR(10) NOT NULL DEFAULT 'INFO'
        CHECK (
            severity IN (
                'TRACE',
                'DEBUG',
                'INFO',
                'WARN',
                'ERROR'
            )
        ),

    message TEXT,

    occurred_at TIMESTAMPTZ NOT NULL,

    attributes JSONB NOT NULL DEFAULT '{}'::JSONB
        CHECK (jsonb_typeof(attributes) = 'object'),

    CONSTRAINT fk_event_span
        FOREIGN KEY (run_id, span_id)
        REFERENCES spans(run_id, span_id)
        ON DELETE CASCADE
);


-- 查询某个任务的执行历史
CREATE INDEX idx_runs_task_started
ON runs(task_id, started_at DESC);

-- 按执行状态和时间筛选
CREATE INDEX idx_runs_status_started
ON runs(status, started_at DESC);

-- 查询某条 Trace 中的全部 Span
CREATE INDEX idx_spans_run_start
ON spans(run_id, start_time);

-- 根据父 Span 查询子 Span
CREATE INDEX idx_spans_run_parent
ON spans(run_id, parent_span_id);

-- 查询某个 Agent 的执行历史
CREATE INDEX idx_spans_agent_start
ON spans(agent_id, start_time DESC);

-- 查询异常 Span
CREATE INDEX idx_spans_error_time
ON spans(start_time DESC)
WHERE status = 'ERROR';

-- 查询工具调用
CREATE INDEX idx_spans_tool_time
ON spans(tool_name, start_time DESC)
WHERE operation_type = 'TOOL';

-- 查询某条 Trace 的事件
CREATE INDEX idx_events_run_time
ON span_events(run_id, occurred_at);
