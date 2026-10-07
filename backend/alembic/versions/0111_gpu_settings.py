"""0111: opt-in remote GPU solving, configured in Application Settings."""
import json
from alembic import op
import sqlalchemy as sa

revision = "0111"
down_revision = "0110"
branch_labels = depends_on = None
KEYS = [
    ("gpu.enabled", "boolean", False, "Enable GPU service; select cuopt-remote in solve.solver to use it"),
    ("gpu.endpoint", "string", "", "GPU bridge URL on the private network (platform only)"),
    ("gpu.cpu_fallback", "boolean", True, "Use HiGHS if GPU is busy, unavailable, or returns an invalid solution"),
    ("gpu.memory_mb", "number", 4096, "Minimum free GPU memory for admission (MB); not an allocation limit"),
]
def upgrade():
    for key, kind, default, description in KEYS:
        op.execute(sa.text("INSERT INTO setting_key(key,value_type,default_value,description) VALUES (:k,:t,CAST(:v AS jsonb),:d)").bindparams(k=key,t=kind,v=json.dumps(default),d=description))
def downgrade():
    op.execute("DELETE FROM setting_key WHERE key LIKE 'gpu.%'")
