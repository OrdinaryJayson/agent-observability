-- Bounded keyset batches; migration and checksum record remain atomic.
DO $$
DECLARE cursor_id uuid := NULL; item uuid; batch_count integer;
BEGIN
 LOOP
  batch_count := 0;
  FOR item IN SELECT run_id FROM runs
    WHERE status <> 'RUNNING' AND (cursor_id IS NULL OR run_id > cursor_id)
    ORDER BY run_id LIMIT 500
  LOOP
   PERFORM v2_legacy_summary(item);
   cursor_id := item;
   batch_count := batch_count+1;
  END LOOP;
  EXIT WHEN batch_count=0;
 END LOOP;
END $$;
REFRESH MATERIALIZED VIEW mv_daily_metrics;
