/**
 * Moving a record under another in the workbench tree (drag and drop), by whichever way its kind can
 * sit there: a reference field (the field is set to the new parent's key) or a hierarchy (the one
 * link to its parent is re-pointed in place -- a hierarchy keeps one parent per child, and a
 * re-point is a single write the database checks for loops, so a refused move changes nothing).
 */
import { placingEdges, type WorkbenchEdge, type WorkbenchSchema } from "../../api/workbench";
import {
  createRelationship,
  getEntity,
  listRelationships,
  updateEntity,
  updateRelationship,
  type Id,
} from "../../api/v1";

type Placed = { id: Id; key: string; entity_type_id: Id };

/** The way a record of `movedKind` can sit under one of `ontoKind`: a reference field first. */
export function moveEdge(schema: WorkbenchSchema, movedKind: Id, ontoKind: Id): WorkbenchEdge | null {
  const edges = placingEdges(schema, movedKind, ontoKind);
  return edges.find((e) => e.group_key.startsWith("ref:")) ?? edges.find((e) => e.group_key.startsWith("rel:")) ?? null;
}

/** What the confirmation says the move does. */
export function moveWords(edge: WorkbenchEdge, onto: Placed): string {
  return edge.group_key.startsWith("ref:") ? `${edge.field} = ${onto.key}` : `its ${edge.field} parent becomes ${onto.key}`;
}

export async function moveRecord(edge: WorkbenchEdge, moved: Placed, onto: Placed): Promise<void> {
  if (edge.group_key.startsWith("ref:")) {
    const fresh = await getEntity(moved.id);
    await updateEntity(moved.id, { attrs: { ...fresh.attrs, [edge.field]: onto.key }, updated_at: fresh.updated_at });
    return;
  }
  // A hierarchy: `from` is the parent, `to` the child.
  const current = await listRelationships({ relationshipTypeId: edge.relationship_type_id, toEntityId: moved.id, limit: 1 });
  const link = current.items[0];
  if (link) {
    await updateRelationship(link.id, { from_entity_id: onto.id, updated_at: link.updated_at });
  } else {
    await createRelationship({ relationship_type_id: edge.relationship_type_id, from_entity_id: onto.id, to_entity_id: moved.id });
  }
}
