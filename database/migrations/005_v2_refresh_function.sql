-- Keep normal app credentials free of MV ownership / general DDL rights.
CREATE FUNCTION public.v2_refresh_metrics() RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public AS $$
BEGIN
  REFRESH MATERIALIZED VIEW CONCURRENTLY public.mv_daily_metrics;
END $$;
REVOKE ALL ON FUNCTION public.v2_refresh_metrics() FROM PUBLIC;
