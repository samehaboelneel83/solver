import { describe, expect, it } from "vitest";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { render, screen } from "@testing-library/react";
import AliasRedirect from "./AliasRedirect";

function Where() {
  return <p data-testid="path">{`${useLocation().pathname}${useLocation().search}${useLocation().hash}`}</p>;
}

describe("AliasRedirect", () => {
  it("keeps query and hash when resolving a compatibility alias", () => {
    render(
      <MemoryRouter initialEntries={["/home?tab=recent#top"]}>
        <Routes>
          <Route path="/home" element={<AliasRedirect to="/" />} />
          <Route path="/" element={<Where />} />
        </Routes>
      </MemoryRouter>
    );
    expect(screen.getByTestId("path")).toHaveTextContent("/?tab=recent#top");
  });
});
