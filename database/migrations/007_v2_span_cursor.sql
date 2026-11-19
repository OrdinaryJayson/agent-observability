-- One workload-driven composite index for stable global span keyset search.
-- It avoids sorting/scanning every older span on deep pages; optional filters
-- still use the existing selective indexes where the optimizer finds it useful.
CREATE INDEX spans_cursor ON spans(start_time DESC,span_pk DESC);
