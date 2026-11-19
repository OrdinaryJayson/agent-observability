-- Explicit deployment step as database owner; deliberately not a migration.
-- Execute in the business/test database. NOLOGIN roles are groups; grant them
-- to separate deployment-managed login roles without putting passwords here.
DO $$ BEGIN
  IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='observability_app') THEN
    CREATE ROLE observability_app NOLOGIN;
  END IF;
  IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='observability_lab') THEN
    CREATE ROLE observability_lab NOLOGIN;
  END IF;
  EXECUTE format('REVOKE CONNECT,CREATE,TEMPORARY ON DATABASE %I FROM PUBLIC',current_database());
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO observability_app',current_database());
END $$;
REVOKE CREATE ON SCHEMA public FROM PUBLIC,observability_app,observability_lab;
GRANT USAGE ON SCHEMA public TO observability_app;
GRANT SELECT ON agents,tasks,runs,spans,span_events,workflows,workflow_versions,
  run_executions,run_journal,span_links,run_summaries,analysis_reports,request_keys,
  dataset_manifests,experiment_runs,experiment_trials,experiment_samples,audit_log,
  v_run_facts,mv_daily_metrics TO observability_app;
GRANT INSERT ON agents,tasks,runs,spans,span_events,workflows,workflow_versions,
  run_executions,run_journal,span_links,run_summaries,analysis_reports,request_keys,
  dataset_manifests,experiment_runs,experiment_trials,experiment_samples,audit_log TO observability_app;
GRANT UPDATE ON agents,tasks,runs,workflows,run_executions,dataset_manifests,
  experiment_runs,experiment_trials TO observability_app;
GRANT USAGE ON SEQUENCE spans_span_pk_seq,run_summaries_summary_seq_seq,audit_log_audit_id_seq TO observability_app;
REVOKE ALL ON FUNCTION v2_legacy_summary(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION v2_legacy_summary(uuid) TO observability_app;

-- PG16 concurrent refresh requires owner rights. Expose one fixed operation,
-- not arbitrary SQL; its caller still holds the refresh advisory lock/budget.
CREATE OR REPLACE FUNCTION public.v2_refresh_metrics() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
  REFRESH MATERIALIZED VIEW CONCURRENTLY public.mv_daily_metrics;
END $$;
REVOKE ALL ON FUNCTION public.v2_refresh_metrics() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.v2_refresh_metrics() TO observability_app;
