from fastapi import APIRouter

from app.crud.factory import build_crud_router
from app.models.iam import Organization, Role, UserAccount, UserRole
from app.schemas.generate import make_crud_schemas

router = APIRouter()

# --- iam ---

OrganizationCreate, OrganizationUpdate, OrganizationRead = make_crud_schemas(
    Organization, name="Organization", readonly={"id"}, server_default={"created_at"}
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

UserAccountCreate, UserAccountUpdate, UserAccountRead = make_crud_schemas(
    UserAccount, name="UserAccount", readonly={"id"}, server_default={"created_at"}
)
router.include_router(
    build_crud_router(
        model=UserAccount,
        create_schema=UserAccountCreate,
        update_schema=UserAccountUpdate,
        read_schema=UserAccountRead,
        schema_name="iam",
        table_name="user_account",
    )
)

RoleCreate, RoleUpdate, RoleRead = make_crud_schemas(Role, name="Role", readonly={"id"})
router.include_router(
    build_crud_router(
        model=Role,
        create_schema=RoleCreate,
        update_schema=RoleUpdate,
        read_schema=RoleRead,
        schema_name="iam",
        table_name="role",
    )
)

UserRoleCreate, UserRoleUpdate, UserRoleRead = make_crud_schemas(UserRole, name="UserRole", readonly={"id"})
router.include_router(
    build_crud_router(
        model=UserRole,
        create_schema=UserRoleCreate,
        update_schema=UserRoleUpdate,
        read_schema=UserRoleRead,
        schema_name="iam",
        table_name="user_role",
    )
)
