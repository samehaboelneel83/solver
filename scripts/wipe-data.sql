-- Deletes every piece of business data, keeping user accounts, organizations, roles, permissions,
-- API keys, SSO/SCIM set-up, licences and platform settings. Run by scripts/wipe-data.cmd.
-- One transaction: it all goes, or (on any error) nothing does. Tables this installation does not
-- have (camp_solve after migration 0106) are skipped, so it works before and after an upgrade.
\set ON_ERROR_STOP on
BEGIN;
-- The audit log is append-only for the application; this is the owner, deliberately clearing it.
SELECT set_config('app.audit_prune', '1', true);
DO $$
DECLARE
  present text;
BEGIN
  SELECT string_agg(t, ', ') INTO present
    FROM unnest(ARRAY['iam.audit_event','iam.rate_bucket','iam.usage_month','public.approved_plan','public.attribute_def','public.camp_solve','public.constraint_result','public.dataset','public.domain','public.entity','public.entity_change','public.entity_type','public.gis_dataset','public.gis_feature','public.gis_layer','public.gis_upload','public.graph_layout','public.import_load','public.import_validation','public.ingestion_job','public.integration_connection','public.model_draft','public.model_publication','public.model_version','public.parameter_def','public.parameter_value','public.pareto_point','public.predictor','public.predictor_training','public.problem','public.relationship','public.relationship_type','public.run','public.run_alternative','public.run_event','public.scenario','public.solution','public.solution_amount_chunk','public.suite_case','public.suite_gate_override','public.suite_nightly','public.template']) AS t
   WHERE to_regclass(t) IS NOT NULL;
  EXECUTE 'TRUNCATE TABLE ' || present || ' RESTART IDENTITY';
END
$$;
-- Settings tied to a domain or a problem went with them; platform settings stay.
DELETE FROM public.setting WHERE scope::text NOT IN ('platform', 'organization');
COMMIT;
-- Start a fresh write-ahead log segment, so the next archived WAL no longer carries the old data.
CHECKPOINT;
SELECT pg_switch_wal();
