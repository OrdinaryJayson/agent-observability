-- V2 relational skeleton frozen by docs/14; 001 remains unchanged.
CREATE TABLE workflows (
  workflow_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name varchar(100) NOT NULL CHECK (length(btrim(name)) > 0),
  description text,
  draft jsonb NOT NULL CHECK (jsonb_typeof(draft) = 'object'),
  revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
  archived_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE workflow_versions (
  version_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workflow_id uuid NOT NULL REFERENCES workflows,
  version_no integer NOT NULL CHECK (version_no > 0),
  definition jsonb NOT NULL CHECK (jsonb_typeof(definition) = 'object'),
  definition_hash char(64) NOT NULL CHECK (definition_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(workflow_id, version_no)
);
CREATE TABLE run_executions (
  run_id uuid PRIMARY KEY REFERENCES runs ON DELETE RESTRICT,
  version_id uuid NOT NULL REFERENCES workflow_versions,
  config jsonb NOT NULL CHECK (jsonb_typeof(config) = 'object'),
  agent_bindings jsonb NOT NULL CHECK (jsonb_typeof(agent_bindings) = 'object'),
  execution_state varchar(16) NOT NULL DEFAULT 'QUEUED'
    CHECK (execution_state IN ('QUEUED','RUNNING','RECOVERING','FINALIZING','FINISHED')),
  priority smallint NOT NULL DEFAULT 0 CHECK (priority BETWEEN -10 AND 10),
  queued_at timestamptz NOT NULL DEFAULT now(),
  execution_started_at timestamptz,
  execution_ended_at timestamptz,
  deadline_at timestamptz NOT NULL,
  worker_id varchar(100),
  lease_epoch bigint NOT NULL DEFAULT 0 CHECK (lease_epoch >= 0),
  lease_expires_at timestamptz,
  heartbeat_at timestamptz,
  recovery_count integer NOT NULL DEFAULT 0 CHECK (recovery_count BETWEEN 0 AND 2),
  cancel_requested_at timestamptz,
  last_seq bigint NOT NULL DEFAULT 0 CHECK (last_seq >= 0),
  checkpoint jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(checkpoint) = 'object'),
  retry_of_run_id uuid REFERENCES runs,
  CHECK (retry_of_run_id IS NULL OR retry_of_run_id <> run_id),
  CHECK (execution_ended_at IS NULL OR execution_ended_at >= execution_started_at),
  CHECK ((worker_id IS NULL) = (lease_expires_at IS NULL))
);
CREATE TABLE run_journal (
  run_id uuid NOT NULL REFERENCES run_executions,
  seq bigint NOT NULL CHECK (seq > 0),
  batch_id uuid NOT NULL,
  batch_hash char(64) NOT NULL CHECK (batch_hash ~ '^[0-9a-f]{64}$'),
  producer_event_id uuid NOT NULL,
  kind varchar(40) NOT NULL,
  payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
  payload_hash char(64) NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
  lease_epoch bigint NOT NULL CHECK (lease_epoch >= 0),
  occurred_at timestamptz NOT NULL,
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(run_id, seq), UNIQUE(run_id, producer_event_id)
);
CREATE TABLE span_links (
  run_id uuid NOT NULL REFERENCES runs,
  source_span_id varchar(16) NOT NULL,
  target_span_id varchar(16) NOT NULL,
  link_type varchar(16) NOT NULL CHECK (link_type IN ('DEPENDS_ON','RETRY_OF','HANDOFF')),
  PRIMARY KEY(run_id, source_span_id, target_span_id, link_type),
  FOREIGN KEY(run_id,source_span_id) REFERENCES spans(run_id,span_id)
    DEFERRABLE INITIALLY DEFERRED,
  FOREIGN KEY(run_id,target_span_id) REFERENCES spans(run_id,span_id)
    DEFERRABLE INITIALLY DEFERRED,
  CHECK (source_span_id <> target_span_id)
);
CREATE TABLE run_summaries (
  run_id uuid PRIMARY KEY REFERENCES runs,
  summary_seq bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
  finalized_at timestamptz NOT NULL,
  run_started_at timestamptz NOT NULL,
  final_status varchar(12) NOT NULL CHECK (final_status IN ('SUCCESS','FAILED','CANCELLED')),
  execution_mode varchar(16) NOT NULL CHECK (execution_mode IN ('LEGACY','REALTIME','VIRTUAL')),
  span_count integer NOT NULL CHECK (span_count BETWEEN 0 AND 500),
  event_count integer NOT NULL CHECK (event_count BETWEEN 0 AND 2000),
  error_count integer NOT NULL CHECK (error_count >= 0 AND error_count <= span_count),
  input_tokens bigint NOT NULL CHECK (input_tokens >= 0),
  output_tokens bigint NOT NULL CHECK (output_tokens >= 0),
  wall_duration_ms double precision NOT NULL CHECK (wall_duration_ms >= 0),
  queue_duration_ms double precision,
  execution_duration_ms double precision,
  logical_duration_ms double precision,
  journal_seq bigint,
  CHECK (queue_duration_ms IS NULL OR queue_duration_ms >= 0),
  CHECK (execution_duration_ms IS NULL OR execution_duration_ms >= 0),
  CHECK (logical_duration_ms IS NULL OR logical_duration_ms >= 0)
);
CREATE TABLE analysis_reports (
  report_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES runs,
  journal_seq bigint NOT NULL CHECK (journal_seq >= 0),
  algorithm_version varchar(40) NOT NULL,
  report jsonb NOT NULL CHECK (jsonb_typeof(report) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(run_id,journal_seq,algorithm_version)
);
CREATE TABLE request_keys (
  scope varchar(200) NOT NULL, key varchar(100) NOT NULL,
  request_hash char(64) NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  resource_id uuid NOT NULL,
  response_status smallint NOT NULL CHECK (response_status IN (201,202)),
  response_body jsonb NOT NULL CHECK (jsonb_typeof(response_body) = 'object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(scope,key)
);
CREATE TABLE dataset_manifests (
  dataset_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name varchar(100) NOT NULL,
  purpose varchar(20) NOT NULL CHECK (purpose IN ('DEMO','BENCHMARK','LOAD')),
  state varchar(16) NOT NULL CHECK (state IN ('BUILDING','READY','FAILED')),
  seed bigint NOT NULL,
  config jsonb NOT NULL CHECK (jsonb_typeof(config) = 'object'),
  actual_counts jsonb NOT NULL CHECK (jsonb_typeof(actual_counts) = 'object'),
  content_hash char(64),
  generator_version varchar(80) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  CHECK (content_hash IS NULL OR content_hash ~ '^[0-9a-f]{64}$')
);
CREATE TABLE experiment_runs (
  experiment_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  dataset_id uuid NOT NULL REFERENCES dataset_manifests,
  case_code varchar(40) NOT NULL,
  status varchar(16) NOT NULL CHECK (status IN ('QUEUED','RUNNING','SUCCESS','FAILED','CANCELLED')),
  phase varchar(16) CHECK (phase IN ('PREPARING','WARMUP','MEASURING','VERIFYING','EXPORTING')),
  progress double precision CHECK (progress BETWEEN 0 AND 1),
  cancel_requested_at timestamptz,
  runner_id varchar(100),
  config jsonb NOT NULL CHECK (jsonb_typeof(config) = 'object'),
  environment jsonb NOT NULL CHECK (jsonb_typeof(environment) = 'object'),
  protocol_version varchar(40) NOT NULL,
  code_revision varchar(80) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  ended_at timestamptz,
  error_code varchar(80)
);
CREATE TABLE experiment_trials (
  trial_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  experiment_id uuid NOT NULL REFERENCES experiment_runs,
  ordinal integer NOT NULL CHECK (ordinal > 0),
  variant varchar(80) NOT NULL,
  parameters jsonb NOT NULL CHECK (jsonb_typeof(parameters) = 'object'),
  summary jsonb NOT NULL CHECK (jsonb_typeof(summary) = 'object'),
  UNIQUE(experiment_id,ordinal)
);
CREATE TABLE experiment_samples (
  trial_id uuid NOT NULL REFERENCES experiment_trials,
  repetition integer NOT NULL CHECK (repetition >= 0),
  is_warmup boolean NOT NULL,
  measured_at timestamptz NOT NULL,
  metrics jsonb NOT NULL CHECK (jsonb_typeof(metrics) = 'object'),
  plan jsonb,
  correctness jsonb NOT NULL CHECK (jsonb_typeof(correctness) = 'object'),
  PRIMARY KEY(trial_id,repetition),
  CHECK (plan IS NULL OR jsonb_typeof(plan) = 'object')
);
CREATE TABLE audit_log (
  audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  action varchar(80) NOT NULL,
  resource_type varchar(40) NOT NULL,
  resource_id uuid,
  actor varchar(100) NOT NULL,
  request_id uuid NOT NULL,
  details jsonb NOT NULL CHECK (jsonb_typeof(details) = 'object'),
  occurred_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
