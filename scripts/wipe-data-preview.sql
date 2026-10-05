-- What scripts/wipe-data.cmd would delete: one row per table, with its row count. Changes nothing.
-- A table this installation does not have (camp_solve after migration 0106) is left out.
SELECT 'TO DELETE' AS what, t AS "table",
       (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %s', t), false, true, '')))[1]::text::bigint AS rows
  FROM unnest(ARRAY['iam.audit_event','iam.rate_bucket','iam.usage_month','public.approved_plan','public.attribute_def','public.camp_solve','public.constraint_result','public.dataset','public.domain','public.entity','public.entity_change','public.entity_type','public.gis_dataset','public.gis_feature','public.gis_layer','public.gis_upload','public.graph_layout','public.import_load','public.import_validation','public.ingestion_job','public.integration_connection','public.model_draft','public.model_publication','public.model_version','public.parameter_def','public.parameter_value','public.pareto_point','public.predictor','public.predictor_training','public.problem','public.relationship','public.relationship_type','public.run','public.run_alternative','public.run_event','public.scenario','public.solution','public.solution_amount_chunk','public.suite_case','public.suite_gate_override','public.suite_nightly','public.template']) AS t
 WHERE to_regclass(t) IS NOT NULL
UNION ALL
SELECT 'TO DELETE', 'public.setting (domain/problem-scoped)', count(*) FROM public.setting WHERE scope::text NOT IN ('platform', 'organization')
ORDER BY 2;
SELECT 'KEPT' AS what, 'user accounts' AS "table", count(*) AS rows FROM iam.user_account
 UNION ALL SELECT 'KEPT', 'organizations', count(*) FROM iam.organization
 UNION ALL SELECT 'KEPT', 'roles', count(*) FROM iam.role
 UNION ALL SELECT 'KEPT', 'API keys', count(*) FROM iam.api_key
 UNION ALL SELECT 'KEPT', 'platform settings', count(*) FROM public.setting WHERE scope::text IN ('platform', 'organization');
