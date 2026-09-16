export type GraphNode = {
  id: string;
  type: string;
  label: string;
  parent: string | null;
  attributes: Record<string, unknown>;
};

export type GraphEdge = {
  id: string;
  source: string;
  target: string;
  type: string;
  label: string;
  attributes: Record<string, unknown>;
};

export type EntityTypeOption = {
  id: string;
  code: string;
  name: string;
  is_abstract: boolean;
};

export type RelationshipTypeOption = {
  id: string;
  code: string;
  name: string;
  is_directed: boolean;
  source_entity_type: string | null;
  target_entity_type: string | null;
};

export type HierarchyOption = {
  id: string;
  code: string;
  name: string;
};

export type AttributeDefinitionOption = {
  id: string;
  entity_type_id: string;
  code: string;
  name: string;
  data_type: string;
};

export type GraphResponse = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  entity_types: EntityTypeOption[];
  relationship_types: RelationshipTypeOption[];
  hierarchies: HierarchyOption[];
  attribute_definitions: AttributeDefinitionOption[];
};
