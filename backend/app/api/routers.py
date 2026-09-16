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

from app.models.domain import (
    AttributeDefinition,
    Entity,
    EntityAttribute,
    EntityType,
    Relationship,
    RelationshipType,
)

# --- domain: group A (entity core + relationships) ---

EntityTypeCreate, EntityTypeUpdate, EntityTypeRead = make_crud_schemas(
    EntityType, name="EntityType", readonly={"id"}, server_default={"created_at"}
)
router.include_router(
    build_crud_router(
        model=EntityType,
        create_schema=EntityTypeCreate,
        update_schema=EntityTypeUpdate,
        read_schema=EntityTypeRead,
        schema_name="domain",
        table_name="entity_type",
    )
)

EntityCreate, EntityUpdate, EntityRead = make_crud_schemas(
    Entity, name="Entity", readonly={"id"}, server_default={"created_at", "updated_at"}
)
router.include_router(
    build_crud_router(
        model=Entity,
        create_schema=EntityCreate,
        update_schema=EntityUpdate,
        read_schema=EntityRead,
        schema_name="domain",
        table_name="entity",
    )
)

AttributeDefinitionCreate, AttributeDefinitionUpdate, AttributeDefinitionRead = make_crud_schemas(
    AttributeDefinition, name="AttributeDefinition", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=AttributeDefinition,
        create_schema=AttributeDefinitionCreate,
        update_schema=AttributeDefinitionUpdate,
        read_schema=AttributeDefinitionRead,
        schema_name="domain",
        table_name="attribute_definition",
    )
)

EntityAttributeCreate, EntityAttributeUpdate, EntityAttributeRead = make_crud_schemas(
    EntityAttribute, name="EntityAttribute", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=EntityAttribute,
        create_schema=EntityAttributeCreate,
        update_schema=EntityAttributeUpdate,
        read_schema=EntityAttributeRead,
        schema_name="domain",
        table_name="entity_attribute",
    )
)

RelationshipTypeCreate, RelationshipTypeUpdate, RelationshipTypeRead = make_crud_schemas(
    RelationshipType, name="RelationshipType", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=RelationshipType,
        create_schema=RelationshipTypeCreate,
        update_schema=RelationshipTypeUpdate,
        read_schema=RelationshipTypeRead,
        schema_name="domain",
        table_name="relationship_type",
    )
)

RelationshipCreate, RelationshipUpdate, RelationshipRead = make_crud_schemas(
    Relationship, name="Relationship", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=Relationship,
        create_schema=RelationshipCreate,
        update_schema=RelationshipUpdate,
        read_schema=RelationshipRead,
        schema_name="domain",
        table_name="relationship",
    )
)
