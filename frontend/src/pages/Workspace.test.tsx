import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it } from "vitest";
import Workspace from "./Workspace";

function Where() {
  return <p data-testid="path">{`${useLocation().pathname}${useLocation().search}`}</p>;
}

describe("Workspace (OAAS N06)", () => {
  it("redirects to Runs with the guided tab, keeping query params", () => {
    render(
      <MemoryRouter initialEntries={["/workspace?problem=1&run=9"]}>
        <Routes>
          <Route path="/workspace" element={<Workspace />} />
          <Route path="/runs" element={<Where />} />
        </Routes>
      </MemoryRouter>
    );
    expect(screen.getByTestId("path")).toHaveTextContent("/runs?problem=1&run=9&tab=guided");
  });
});
