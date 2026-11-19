-- Run only against the physically separate *_lab/*_test experiment database.
DO $$ BEGIN
  IF current_database() !~ '(_lab|_test)$' THEN
    RAISE EXCEPTION 'Dedicated experiment database required';
  END IF;
  IF NOT EXISTS(SELECT FROM pg_roles WHERE rolname='observability_lab') THEN
    CREATE ROLE observability_lab NOLOGIN;
  END IF;
  EXECUTE format('REVOKE CONNECT,CREATE,TEMPORARY ON DATABASE %I FROM PUBLIC',current_database());
  EXECUTE format('GRANT CONNECT,CREATE,TEMPORARY ON DATABASE %I TO observability_lab',current_database());
END $$;
REVOKE CREATE ON SCHEMA public FROM PUBLIC,observability_lab;
GRANT USAGE ON SCHEMA public TO observability_lab;
-- Empty frozen templates support the unchanged v1 pg_temp experiment format.
GRANT SELECT ON public.spans TO observability_lab;
