-- Running facts are observable from committed journal records, not terminal-only
-- summaries. This is aggregate counting, not a second graph/state reducer.
CREATE OR REPLACE VIEW v_run_facts AS
 SELECT r.*,e.version_id,coalesce(e.config->>'mode','LEGACY') AS execution_mode,
 e.execution_state,e.queued_at,e.execution_started_at,e.execution_ended_at,
 s.summary_seq,
 coalesce(s.span_count,CASE WHEN e.run_id IS NOT NULL THEN
   (SELECT count(*)::integer FROM run_journal j WHERE j.run_id=r.run_id AND j.kind='span.started') ELSE
   (SELECT count(*)::integer FROM spans p WHERE p.run_id=r.run_id) END) AS span_count,
 coalesce(s.event_count,CASE WHEN e.run_id IS NOT NULL THEN
   (SELECT count(*)::integer FROM run_journal j WHERE j.run_id=r.run_id AND j.kind='span.event') ELSE
   (SELECT count(*)::integer FROM span_events p WHERE p.run_id=r.run_id) END) AS event_count,
 coalesce(s.error_count,CASE WHEN e.run_id IS NOT NULL THEN
   (SELECT count(*)::integer FROM run_journal j WHERE j.run_id=r.run_id AND j.kind='span.finished' AND j.payload->>'status'='ERROR') ELSE
   (SELECT count(*)::integer FROM spans p WHERE p.run_id=r.run_id AND p.status='ERROR') END) AS error_count,
 coalesce(s.input_tokens,CASE WHEN e.run_id IS NOT NULL THEN
   (SELECT coalesce(sum((j.payload->>'input_tokens')::bigint),0)::bigint FROM run_journal j WHERE j.run_id=r.run_id AND j.kind='span.finished') ELSE
   (SELECT coalesce(sum(p.input_tokens),0)::bigint FROM spans p WHERE p.run_id=r.run_id AND p.operation_type='LLM') END) AS input_tokens,
 coalesce(s.output_tokens,CASE WHEN e.run_id IS NOT NULL THEN
   (SELECT coalesce(sum((j.payload->>'output_tokens')::bigint),0)::bigint FROM run_journal j WHERE j.run_id=r.run_id AND j.kind='span.finished') ELSE
   (SELECT coalesce(sum(p.output_tokens),0)::bigint FROM spans p WHERE p.run_id=r.run_id AND p.operation_type='LLM') END) AS output_tokens,
 s.wall_duration_ms,s.queue_duration_ms,s.execution_duration_ms,s.logical_duration_ms
 FROM runs r LEFT JOIN run_executions e USING(run_id) LEFT JOIN run_summaries s USING(run_id);

CREATE FUNCTION v2_experiment_terminal_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.status IN ('SUCCESS','FAILED','CANCELLED') AND NEW.status<>OLD.status THEN
   RAISE EXCEPTION 'Experiment terminal state cannot be reversed' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER experiment_terminal_immutable BEFORE UPDATE ON experiment_runs
 FOR EACH ROW EXECUTE FUNCTION v2_experiment_terminal_immutable();
ALTER TABLE experiment_runs ADD CONSTRAINT registered_experiment_case CHECK(case_code IN
 ('INDEX_SELECTIVITY','JSONB_GIN','PAGINATION','AGGREGATION','MVCC_ISOLATION','QUEUE_CONTENTION'));
