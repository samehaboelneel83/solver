import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { RelationshipType } from "../api/v1";
import RelationshipPicture from "./RelationshipPicture";

const cells = [
  { id: 1, entity_type_id: 9, key: "a", label: null, attrs: { place: { type: "Point", coordinates: [0, 0] } } },
  { id: 2, entity_type_id: 9, key: "b", label: null, attrs: { place: { type: "Point", coordinates: [1, 0] } } },
];
vi.mock("../api/v1", async () => {
  const actual = await vi.importActual<typeof import("../api/v1")>("../api/v1");
  return {
    ...actual,
    useRelationships: () => ({ isLoading: false, data: { total: 1, items: [{ from_entity_id: 1, to_entity_id: 2 }] } }),
    useEntities: () => ({ isLoading: false, data: { items: cells, total: 2 } }),
    useEntityTypes: () => ({ data: { items: [{ id: 9, name: "cell" }] } }),
  };
});

describe("a relationship type's links as a picture (queue R17c)", () => {
  it("draws who is linked to whom, and the links on a map when both ends have places", () => {
    const type = { id: 4, domain_id: 1, name: "adjacent", from_type_id: 9, to_type_id: 9 } as unknown as RelationshipType;
    render(<QueryClientProvider client={new QueryClient()}><RelationshipPicture type={type} /></QueryClientProvider>);
    expect(screen.getByText("1 links")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Map" }));
    expect(screen.getByRole("img", { name: /and 1 lines$/ })).toBeInTheDocument();
  });
});
