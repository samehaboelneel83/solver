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


from app.models.domain import (
    EntityRole,
    EntityState,
    Hierarchy,
    HierarchyNode,
    RoleType,
    StateType,
)

# --- domain: group B (hierarchy, roles, states) ---

HierarchyCreate, HierarchyUpdate, HierarchyRead = make_crud_schemas(
    Hierarchy, name="Hierarchy", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=Hierarchy,
        create_schema=HierarchyCreate,
        update_schema=HierarchyUpdate,
        read_schema=HierarchyRead,
        schema_name="domain",
        table_name="hierarchy",
    )
)

HierarchyNodeCreate, HierarchyNodeUpdate, HierarchyNodeRead = make_crud_schemas(
    HierarchyNode, name="HierarchyNode", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=HierarchyNode,
        create_schema=HierarchyNodeCreate,
        update_schema=HierarchyNodeUpdate,
        read_schema=HierarchyNodeRead,
        schema_name="domain",
        table_name="hierarchy_node",
    )
)

RoleTypeCreate, RoleTypeUpdate, RoleTypeRead = make_crud_schemas(
    RoleType, name="RoleType", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=RoleType,
        create_schema=RoleTypeCreate,
        update_schema=RoleTypeUpdate,
        read_schema=RoleTypeRead,
        schema_name="domain",
        table_name="role_type",
    )
)

EntityRoleCreate, EntityRoleUpdate, EntityRoleRead = make_crud_schemas(
    EntityRole, name="EntityRole", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=EntityRole,
        create_schema=EntityRoleCreate,
        update_schema=EntityRoleUpdate,
        read_schema=EntityRoleRead,
        schema_name="domain",
        table_name="entity_role",
    )
)

StateTypeCreate, StateTypeUpdate, StateTypeRead = make_crud_schemas(
    StateType, name="StateType", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=StateType,
        create_schema=StateTypeCreate,
        update_schema=StateTypeUpdate,
        read_schema=StateTypeRead,
        schema_name="domain",
        table_name="state_type",
    )
)

EntityStateCreate, EntityStateUpdate, EntityStateRead = make_crud_schemas(
    EntityState, name="EntityState", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=EntityState,
        create_schema=EntityStateCreate,
        update_schema=EntityStateUpdate,
        read_schema=EntityStateRead,
        schema_name="domain",
        table_name="entity_state",
    )
)


from app.models.domain import Event, EventType, Resource, ResourceType, TimeCalendar, TimePeriod

# --- domain: group C (events, resources, time) ---

EventTypeCreate, EventTypeUpdate, EventTypeRead = make_crud_schemas(
    EventType, name="EventType", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=EventType,
        create_schema=EventTypeCreate,
        update_schema=EventTypeUpdate,
        read_schema=EventTypeRead,
        schema_name="domain",
        table_name="event_type",
    )
)

EventCreate, EventUpdate, EventRead = make_crud_schemas(Event, name="Event", readonly={"id"})
router.include_router(
    build_crud_router(
        model=Event,
        create_schema=EventCreate,
        update_schema=EventUpdate,
        read_schema=EventRead,
        schema_name="domain",
        table_name="event",
    )
)

ResourceTypeCreate, ResourceTypeUpdate, ResourceTypeRead = make_crud_schemas(
    ResourceType, name="ResourceType", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=ResourceType,
        create_schema=ResourceTypeCreate,
        update_schema=ResourceTypeUpdate,
        read_schema=ResourceTypeRead,
        schema_name="domain",
        table_name="resource_type",
    )
)

ResourceCreate, ResourceUpdate, ResourceRead = make_crud_schemas(
    Resource, name="Resource", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=Resource,
        create_schema=ResourceCreate,
        update_schema=ResourceUpdate,
        read_schema=ResourceRead,
        schema_name="domain",
        table_name="resource",
    )
)

TimeCalendarCreate, TimeCalendarUpdate, TimeCalendarRead = make_crud_schemas(
    TimeCalendar, name="TimeCalendar", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=TimeCalendar,
        create_schema=TimeCalendarCreate,
        update_schema=TimeCalendarUpdate,
        read_schema=TimeCalendarRead,
        schema_name="domain",
        table_name="time_calendar",
    )
)

TimePeriodCreate, TimePeriodUpdate, TimePeriodRead = make_crud_schemas(
    TimePeriod, name="TimePeriod", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=TimePeriod,
        create_schema=TimePeriodCreate,
        update_schema=TimePeriodUpdate,
        read_schema=TimePeriodRead,
        schema_name="domain",
        table_name="time_period",
    )
)


from app.models.problem import Problem, Scenario, VariableDefinition, VariableDimension

# --- problem: group A (problem, scenario, variables) ---

ProblemCreate, ProblemUpdate, ProblemRead = make_crud_schemas(
    Problem, name="Problem", readonly={"id"}, server_default={"created_at"}
)
router.include_router(
    build_crud_router(
        model=Problem,
        create_schema=ProblemCreate,
        update_schema=ProblemUpdate,
        read_schema=ProblemRead,
        schema_name="problem",
        table_name="problem",
    )
)

ScenarioCreate, ScenarioUpdate, ScenarioRead = make_crud_schemas(
    Scenario, name="Scenario", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=Scenario,
        create_schema=ScenarioCreate,
        update_schema=ScenarioUpdate,
        read_schema=ScenarioRead,
        schema_name="problem",
        table_name="scenario",
    )
)

VariableDefinitionCreate, VariableDefinitionUpdate, VariableDefinitionRead = make_crud_schemas(
    VariableDefinition, name="VariableDefinition", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=VariableDefinition,
        create_schema=VariableDefinitionCreate,
        update_schema=VariableDefinitionUpdate,
        read_schema=VariableDefinitionRead,
        schema_name="problem",
        table_name="variable_definition",
    )
)

VariableDimensionCreate, VariableDimensionUpdate, VariableDimensionRead = make_crud_schemas(
    VariableDimension, name="VariableDimension", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=VariableDimension,
        create_schema=VariableDimensionCreate,
        update_schema=VariableDimensionUpdate,
        read_schema=VariableDimensionRead,
        schema_name="problem",
        table_name="variable_dimension",
    )
)

from app.models.problem import (
    ConstraintDefinition,
    ConstraintScope,
    Objective,
    ObjectiveComponent,
    Parameter,
)

# --- problem: group B (constraints, objectives, parameters) ---

ConstraintDefinitionCreate, ConstraintDefinitionUpdate, ConstraintDefinitionRead = make_crud_schemas(
    ConstraintDefinition, name="ConstraintDefinition", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=ConstraintDefinition,
        create_schema=ConstraintDefinitionCreate,
        update_schema=ConstraintDefinitionUpdate,
        read_schema=ConstraintDefinitionRead,
        schema_name="problem",
        table_name="constraint_definition",
    )
)

ConstraintScopeCreate, ConstraintScopeUpdate, ConstraintScopeRead = make_crud_schemas(
    ConstraintScope, name="ConstraintScope", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=ConstraintScope,
        create_schema=ConstraintScopeCreate,
        update_schema=ConstraintScopeUpdate,
        read_schema=ConstraintScopeRead,
        schema_name="problem",
        table_name="constraint_scope",
    )
)

ObjectiveCreate, ObjectiveUpdate, ObjectiveRead = make_crud_schemas(
    Objective, name="Objective", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=Objective,
        create_schema=ObjectiveCreate,
        update_schema=ObjectiveUpdate,
        read_schema=ObjectiveRead,
        schema_name="problem",
        table_name="objective",
    )
)

ObjectiveComponentCreate, ObjectiveComponentUpdate, ObjectiveComponentRead = make_crud_schemas(
    ObjectiveComponent, name="ObjectiveComponent", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=ObjectiveComponent,
        create_schema=ObjectiveComponentCreate,
        update_schema=ObjectiveComponentUpdate,
        read_schema=ObjectiveComponentRead,
        schema_name="problem",
        table_name="objective_component",
    )
)

ParameterCreate, ParameterUpdate, ParameterRead = make_crud_schemas(
    Parameter, name="Parameter", readonly={"id"}
)
router.include_router(
    build_crud_router(
        model=Parameter,
        create_schema=ParameterCreate,
        update_schema=ParameterUpdate,
        read_schema=ParameterRead,
        schema_name="problem",
        table_name="parameter",
    )
)
