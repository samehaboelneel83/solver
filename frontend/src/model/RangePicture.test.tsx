import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import RangePicture from "./RangePicture";

vi.mock("../api/v1", async () => {
  const actual = await vi.importActual<typeof import("../api/v1")>("../api/v1");
  return {
    ...actual,
    useParameterValues: () => ({ data: { index_types: [{ id: 6, name: "day" }], default_value: 2, cells: [{ entity_ids: [1], value: 10 }] } }),
    useEntitiesOfTypes: () => ({ items: [{ id: 1, key: "mon" }], isLoading: false, error: null, truncated: false }),
  };
});

describe("an uncertain parameter as ranges (queue R17d)", () => {
  it("draws each stored cell and the default from value x (1 - d) to value x (1 + d)", () => {
    render(<RangePicture parameterId={3} deviation={0.1} name="demand" />);
    expect(screen.getByRole("img", { name: "demand as ranges: 2 rows" })).toBeInTheDocument();
    expect(screen.getByText("mon: 10, from 9 to 11")).toBeInTheDocument();
    expect(screen.getByText("every other cell (the default): 2, from 1.8 to 2.2")).toBeInTheDocument();
  });
});
