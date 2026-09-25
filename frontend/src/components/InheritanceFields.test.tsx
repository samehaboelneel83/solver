import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { withInherited, type EntityType } from "../api/v1";
import InheritanceFields from "./InheritanceFields";

const type = (id: number, name: string, inherited_from: number | null = null, is_abstract = false) =>
  ({ id, domain_id: 1, name, role: "resource", colour: null, icon: null, attributes: [], updated_at: "", inherited_from, is_abstract }) as EntityType;

describe("entity-type inheritance in the forms (queue R18)", () => {
  it("never offers a type, or one of its descendants, as its own parent", () => {
    const types = [type(1, "vehicle", null, true), type(2, "truck", 1), type(3, "reefer", 2), type(4, "depot")];
    render(<InheritanceFields types={types} selfId={2} inheritedFrom={1} isAbstract={false}
                              onInheritedFrom={() => {}} onAbstract={() => {}} errors={{}} />);
    const offered = screen.getAllByRole("option").map((o) => o.textContent);
    expect(offered).toEqual(["Nothing -- a type of its own", "vehicle (abstract)", "depot"]);
  });

  it("reports the parent chosen and the abstract switch", () => {
    const onParent = vi.fn();
    const onAbstract = vi.fn();
    render(<InheritanceFields types={[type(1, "vehicle"), type(4, "depot")]} inheritedFrom={null} isAbstract={false}
                              onInheritedFrom={onParent} onAbstract={onAbstract} errors={{ inherited_from: "a cycle" }} />);
    fireEvent.change(screen.getByLabelText("Inherits from"), { target: { value: "1" } });
    expect(onParent).toHaveBeenCalledWith(1);
    fireEvent.change(screen.getByLabelText("Inherits from"), { target: { value: "" } });
    expect(onParent).toHaveBeenLastCalledWith(null);
    fireEvent.click(screen.getByRole("checkbox"));
    expect(onAbstract).toHaveBeenCalledWith(true);
    expect(screen.getByRole("alert")).toHaveTextContent("a cycle");
  });

  it("joins a type's own attributes and its ancestors', keeping the own ones apart", () => {
    const own = { id: 10, name: "refrigerated", entity_type_id: 2 };
    const inherited = { id: 11, name: "capacity", entity_type_id: 1 };
    const joined = withInherited({ ...type(2, "truck", 1), attributes: [own], inherited_attributes: [inherited] } as never);
    expect(joined.attributes.map((a) => a.name)).toEqual(["refrigerated", "capacity"]);
    expect(joined.own_attributes!.map((a) => a.name)).toEqual(["refrigerated"]);
    expect(withInherited(joined)).toBe(joined); // once only
  });
});
