UPDATE iam.quota SET max_time_limit_s = NULL, updated_at = now() WHERE organization_id = '31af64a9-d09b-4c92-9d1c-cdd1fdf69b98';
SELECT o.name, q.tier, q.max_time_limit_s FROM iam.quota q JOIN iam.organization o ON o.id = q.organization_id WHERE o.name = 'Default Organization';
