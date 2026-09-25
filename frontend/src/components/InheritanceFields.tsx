import { useId } from "react";
import type { EntityType, Id } from "../api/v1";

/**
 * Where a type sits in its domain's family tree (queue R18): the type it inherits from -- its
 * attributes, and a place wherever that type is expected -- and whether it is abstract, holding
 * no entities of its own. A type's own descendants are not offered as its parent: that is a cycle.
 */
export default function InheritanceFields({
  types,
  selfId,
  inheritedFrom,
  isAbstract,
  onInheritedFrom,
  onAbstract,
  errors,
}: {
  types: EntityType[];
  selfId?: Id;
  inheritedFrom: Id | null;
  isAbstract: boolean;
  onInheritedFrom: (value: Id | null) => void;
  onAbstract: (value: boolean) => void;
  errors: { inherited_from?: string; is_abstract?: string };
}) {
  const id = useId();
  const descendants = new Set<Id>();
  if (selfId !== undefined) {
    let grew = true;
    descendants.add(selfId);
    while (grew) {
      grew = false;
      for (const t of types) {
        if (t.inherited_from != null && descendants.has(t.inherited_from) && !descendants.has(t.id)) {
          descendants.add(t.id);
          grew = true;
        }
      }
    }
  }
  const parents = types.filter((t) => !descendants.has(t.id));
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div>
        <label htmlFor={`${id}-parent`} className="block text-sm font-medium text-slate-700">
          Inherits from
        </label>
        <select
          id={`${id}-parent`}
          className="mt-1 block w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm"
          value={inheritedFrom ?? ""}
          aria-invalid={errors.inherited_from ? "true" : undefined}
          onChange={(event) => onInheritedFrom(event.target.value === "" ? null : (Number(event.target.value) as Id))}
        >
          <option value="">Nothing -- a type of its own</option>
          {parents.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
              {t.is_abstract ? " (abstract)" : ""}
            </option>
          ))}
        </select>
        <p className="mt-1 text-xs text-slate-500">
          Its entities get that type&apos;s attributes too, and count wherever that type is used -- a truck is a vehicle.
        </p>
        {errors.inherited_from && <p role="alert" className="mt-1 text-sm text-red-600">{errors.inherited_from}</p>}
      </div>
      <div>
        <span className="block text-sm font-medium text-slate-700">Abstract</span>
        <label className="mt-2 flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" checked={isAbstract} onChange={(event) => onAbstract(event.target.checked)} />
          Holds no entities of its own -- only the types that inherit from it do
        </label>
        {errors.is_abstract && <p role="alert" className="mt-1 text-sm text-red-600">{errors.is_abstract}</p>}
      </div>
    </div>
  );
}
