from typing import Optional

from fastapi import APIRouter

from app.api.validation import field_error
from app.core.security import hash_password
from app.crud.factory import build_crud_router
from app.models.iam import Organization, Role, UserAccount, UserRole
from app.models.v1_domain import Domain
from app.models.v1_problem import Problem, Template
from app.schemas.generate import make_crud_schemas

router = APIRouter()

# --- iam ---

OrganizationCreate, OrganizationUpdate, OrganizationRead = make_crud_schemas(
    Organization, name="Organization", readonly={"id"}, server_default={"created_at", "updated_at"}
)
router.include_router(
    build_crud_router(
        model=Organization,
        create_schema=OrganizationCreate,
        update_schema=OrganizationUpdate,
        read_schema=OrganizationRead,
        schema_name="iam",
        table_name="organization",
    )
)

def hash_user_password(data: dict) -> dict:
    """Turn a write-only `password` into `hashed_password`. A raw hash in
    the payload is still dropped by `hidden=`, so it never reaches here."""
    if "password" not in data:
        return data
    password = data.pop("password")
    if password is None:
        return data
    if not isinstance(password, str) or password.strip() == "":
        raise field_error("password", "set a password", password)
    if len(password.encode("utf-8")) > 72:
        raise field_error("password", "must be at most 72 bytes (bcrypt's limit)", password)
    data["hashed_password"] = hash_password(password)
    return data


UserAccountCreate, UserAccountUpdate, UserAccountRead = make_crud_schemas(
    UserAccount,
    name="UserAccount",
    readonly={"id"},
    server_default={"created_at", "updated_at"},
    hidden={"hashed_password"},
    extra_create={"password": (str, ...)},
    extra_update={"password": (Optional[str], None)},
)
router.include_router(
    build_crud_router(
        model=UserAccount,
        create_schema=UserAccountCreate,
        update_schema=UserAccountUpdate,
        read_schema=UserAccountRead,
        schema_name="iam",
        table_name="user_account",
        prepare=hash_user_password,
        write_capability="iam.manage",
    )
)

RoleCreate, RoleUpdate, RoleRead = make_crud_schemas(
    Role, name="Role", readonly={"id"}, server_default={"updated_at"}
)
router.include_router(
    build_crud_router(
        model=Role,
        create_schema=RoleCreate,
        update_schema=RoleUpdate,
        read_schema=RoleRead,
        schema_name="iam",
        table_name="role",
        write_capability="iam.manage",
    )
)

UserRoleCreate, UserRoleUpdate, UserRoleRead = make_crud_schemas(
    UserRole, name="UserRole", readonly={"id"}, server_default={"updated_at"}
)
router.include_router(
    build_crud_router(
        model=UserRole,
        create_schema=UserRoleCreate,
        update_schema=UserRoleUpdate,
        read_schema=UserRoleRead,
        schema_name="iam",
        table_name="user_role",
        write_capability="iam.manage",
    )
)

# --- public (schema v1 flat tables) ---
#
# schema v1: the v0 `domain.*` and `problem.*` schemas (27 tables) were
# dropped by migration 0006_schema_v1_domain / 0007_schema_v1_problem_run.
# Of the 16 v1 tables, only these three flat, always-writable tables go
# through the generic factory:
#
# - `domain`, `template`, `problem` -- plain rows, no cross-row invariant
#   the generic factory can't already enforce (FK/unique/not-null, all
#   handled by translate_db_error).
#
# Every other v1 table is deliberately NOT registered here:
# - The eight DOMAIN tables (entity_type, attribute_def, entity,
#   relationship_type, relationship, parameter_def, parameter_value) need
#   the validation triggers' structured errors surfaced through a
#   purpose-built router, not the generic factory.
# - `scenario` needs cross-problem validation (Task 9) the generic factory
#   can't express.
# - `model_version`, `dataset`, `solution`, `constraint_result`
#   (IMMUTABLE_TABLES) are frozen by a DB trigger; `model_version` gets
#   Task 9's purpose-built read/create router, the other three no router
#   at all. None of the four may appear in TABLE_REGISTRY.

DomainCreate, DomainUpdate, DomainRead = make_crud_schemas(
    Domain, name="Domain", readonly={"id"}, server_default={"created_at", "updated_at"}
)
router.include_router(
    build_crud_router(
        model=Domain,
        create_schema=DomainCreate,
        update_schema=DomainUpdate,
        read_schema=DomainRead,
        schema_name="public",
        table_name="domain",
    )
)

TemplateCreate, TemplateUpdate, TemplateRead = make_crud_schemas(
    Template, name="Template", readonly={"id"}, server_default={"updated_at"}
)
router.include_router(
    build_crud_router(
        model=Template,
        create_schema=TemplateCreate,
        update_schema=TemplateUpdate,
        read_schema=TemplateRead,
        schema_name="public",
        table_name="template",
    )
)

ProblemCreate, ProblemUpdate, ProblemRead = make_crud_schemas(
    Problem, name="Problem", readonly={"id"}, server_default={"created_at", "updated_at"}
)
router.include_router(
    build_crud_router(
        model=Problem,
        create_schema=ProblemCreate,
        update_schema=ProblemUpdate,
        read_schema=ProblemRead,
        schema_name="public",
        table_name="problem",
    )
)
