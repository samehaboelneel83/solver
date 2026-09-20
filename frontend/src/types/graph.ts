// These types define the same contract as backend/app/graph/schemas.py and must
// be kept in sync by hand -- there is no code generation between them in this phase.
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
  /** Task 14b: `entity_type.colour`, a lowercase `#rrggbb`, or null when
   * the type has none -- in which case the canvas draws a deterministic
   * fallback keyed by `id` (see `lib/colour.ts`). This is the one field of
   * this contract Task 7 could not map, because the column did not exist
   * then; the user has since asked for behaviour that needs it. */
  colour: string | null;
};

export type RelationshipTypeOption = {
  id: string;
  code: string;
  name: string;
  is_directed: boolean;
  source_entity_type: string | null;
  target_entity_type: string | null;
  /** Task 14b: `relationship_type.colour`, same rules as above. */
  colour: string | null;
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
