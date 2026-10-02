import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { AttributeSample } from "./MapImport";

it("shows what the first features carry, not the importer's own fields", () => {
  render(<AttributeSample features={[
    { properties: { layer: "polygons", kind: "polygon", zone_code: "Z01", population: 5200 } },
    { properties: { layer: "polygons", kind: "polygon", zone_code: "Z02", population: 4100 } },
  ]} />);
  const table = screen.getByRole("table", { name: "What each feature carries" });
  expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["zone_code", "population"]);
  expect(within(table).getByText("4100")).toBeInTheDocument();
});

it("shows nothing for a drawing with no attributes", () => {
  const { container } = render(<AttributeSample features={[{ properties: { layer: "0", kind: "line" } }]} />);
  expect(container).toBeEmptyDOMElement();
});
