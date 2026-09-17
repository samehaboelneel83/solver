from typing import Any

from pydantic import BaseModel

# These schemas define the same contract as frontend/src/types/graph.ts and must
# be kept in sync by hand -- there is no code generation between them in this phase.


class GraphNode(BaseModel):
    id: str
    type: str
    label: str
    parent: str | None = None
    attributes: dict[str, Any] = {}


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str
    label: str
    attributes: dict[str, Any] = {}


class EntityTypeOption(BaseModel):
    id: str
    code: str
    name: str
    is_abstract: bool


class RelationshipTypeOption(BaseModel):
    id: str
    code: str
    name: str
    is_directed: bool
    source_entity_type: str | None = None
    target_entity_type: str | None = None


class HierarchyOption(BaseModel):
    id: str
    code: str
    name: str


class AttributeDefinitionOption(BaseModel):
    id: str
    entity_type_id: str
    code: str
    name: str
    data_type: str


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    entity_types: list[EntityTypeOption]
    relationship_types: list[RelationshipTypeOption]
    hierarchies: list[HierarchyOption]
    attribute_definitions: list[AttributeDefinitionOption]
