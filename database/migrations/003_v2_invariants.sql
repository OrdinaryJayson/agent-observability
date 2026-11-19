CREATE INDEX executions_queue ON run_executions(priority DESC, queued_at, run_id)
 WHERE execution_state='QUEUED';
CREATE INDEX executions_expiry ON run_executions(lease_expires_at,run_id)
 WHERE execution_state IN ('RUNNING','RECOVERING','FINALIZING');
CREATE INDEX executions_version ON run_executions(version_id,queued_at DESC,run_id);
CREATE INDEX journal_batch ON run_journal(run_id,batch_id,seq);
CREATE INDEX links_target ON span_links(run_id,target_span_id);
CREATE INDEX events_cursor ON span_events(occurred_at DESC,event_id DESC);
CREATE INDEX spans_attributes ON spans USING gin(attributes jsonb_path_ops);
CREATE INDEX spans_error_search ON spans USING gin(to_tsvector('simple',coalesce(error_message,'')));
CREATE INDEX summaries_time ON run_summaries(run_started_at,run_id);
CREATE INDEX experiments_history ON experiment_runs(created_at DESC,experiment_id DESC);
CREATE INDEX audit_history ON audit_log(occurred_at DESC,audit_id DESC);
CREATE INDEX audit_resource ON audit_log(resource_type,resource_id,audit_id);

ALTER TABLE run_journal ADD CONSTRAINT journal_kind CHECK (kind IN (
 'run.queued','run.started','span.started','span.finished','span.event','link.created',
 'node.skipped','checkpoint.saved','cancel.requested','run.recovering','run.finished'));
ALTER TABLE run_executions ADD CONSTRAINT finished_clears_owner CHECK
 (execution_state <> 'FINISHED' OR worker_id IS NULL);
ALTER TABLE run_summaries ADD CONSTRAINT durations_finite CHECK (
 wall_duration_ms < 'Infinity'::float8 AND
 (queue_duration_ms IS NULL OR queue_duration_ms < 'Infinity'::float8) AND
 (execution_duration_ms IS NULL OR execution_duration_ms < 'Infinity'::float8) AND
 (logical_duration_ms IS NULL OR logical_duration_ms < 'Infinity'::float8));
ALTER TABLE experiment_runs ADD CONSTRAINT progress_finite CHECK
 (progress IS NULL OR progress < 'Infinity'::float8);

CREATE FUNCTION v2_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'Published versions and audit records are immutable' USING ERRCODE='55000'; END $$;
CREATE TRIGGER versions_immutable BEFORE UPDATE OR DELETE ON workflow_versions
 FOR EACH ROW EXECUTE FUNCTION v2_immutable();
CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE ON audit_log
 FOR EACH ROW EXECUTE FUNCTION v2_immutable();

CREATE FUNCTION v2_run_consistency() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF EXISTS(SELECT 1 FROM run_executions e JOIN runs r USING(run_id)
   WHERE e.run_id=NEW.run_id AND ((e.execution_state='FINISHED') <> (r.status<>'RUNNING'))) THEN
   RAISE EXCEPTION 'Run/execution terminal state mismatch' USING ERRCODE='23514';
 END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER execution_consistency AFTER INSERT OR UPDATE ON run_executions
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION v2_run_consistency();
CREATE CONSTRAINT TRIGGER run_consistency AFTER UPDATE ON runs
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION v2_run_consistency();

CREATE FUNCTION v2_legacy_summary(target uuid) RETURNS void LANGUAGE sql AS $$
 INSERT INTO run_summaries(run_id,finalized_at,run_started_at,final_status,execution_mode,
 span_count,event_count,error_count,input_tokens,output_tokens,wall_duration_ms)
 SELECT r.run_id,r.ended_at,r.started_at,r.status,'LEGACY',
 (SELECT count(*) FROM spans s WHERE s.run_id=r.run_id),
 (SELECT count(*) FROM span_events e WHERE e.run_id=r.run_id),
 (SELECT count(*) FROM spans s WHERE s.run_id=r.run_id AND s.status='ERROR'),
 (SELECT coalesce(sum(input_tokens),0) FROM spans s WHERE s.run_id=r.run_id AND operation_type='LLM'),
 (SELECT coalesce(sum(output_tokens),0) FROM spans s WHERE s.run_id=r.run_id AND operation_type='LLM'),
 greatest(0,extract(epoch FROM r.ended_at-r.started_at)*1000)
 FROM runs r WHERE r.run_id=target AND r.status<>'RUNNING' AND r.ended_at IS NOT NULL
 AND NOT EXISTS(SELECT 1 FROM run_executions e WHERE e.run_id=r.run_id)
 ON CONFLICT(run_id) DO NOTHING;
$$;

CREATE VIEW v_run_facts AS
 SELECT r.*,e.version_id,coalesce(e.config->>'mode','LEGACY') AS execution_mode,
 e.execution_state,e.queued_at,e.execution_started_at,e.execution_ended_at,
 s.summary_seq,s.span_count,s.event_count,s.error_count,s.input_tokens,s.output_tokens,
 s.wall_duration_ms,s.queue_duration_ms,s.execution_duration_ms,s.logical_duration_ms
 FROM runs r LEFT JOIN run_executions e USING(run_id) LEFT JOIN run_summaries s USING(run_id);

CREATE MATERIALIZED VIEW mv_daily_metrics AS
 SELECT (s.run_started_at AT TIME ZONE 'UTC')::date AS day,s.execution_mode,e.version_id,
 count(*) FILTER(WHERE final_status='SUCCESS') AS success_runs,
 count(*) FILTER(WHERE final_status='FAILED') AS failed_runs,
 count(*) FILTER(WHERE final_status='CANCELLED') AS cancelled_runs,
 count(s.execution_duration_ms) AS duration_count,
 coalesce(sum(s.execution_duration_ms),0) AS duration_sum_ms,
 sum(input_tokens) AS input_tokens,sum(output_tokens) AS output_tokens,sum(span_count) AS span_count,
 max(summary_seq) AS watermark_max_seq,statement_timestamp() AS snapshot_at
 FROM run_summaries s LEFT JOIN run_executions e USING(run_id)
 GROUP BY 1,2,3;
CREATE UNIQUE INDEX daily_metrics_identity ON mv_daily_metrics(day,execution_mode,version_id) NULLS NOT DISTINCT;
