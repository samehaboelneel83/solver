import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DataTable, { isIdentifierColumn } from "./DataTable";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, apiFetch: vi.fn() };
});

import { apiFetch } from "../api/client";

const fields = [
  { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
  // label_field: true mirrors the backend's own metadata (backend/app/crud/labels.py's
  // DEFAULT_LABEL_COLUMNS) -- recordLabel (lib/labels.ts) is metadata-driven, not
  // hardcoded to `code`/`name`, so tests need to flag this explicitly, same as a real
  // table's schema would.
  { name: "code", type: "string" as const, required: true, writable: true, is_fk: false, fk_table: null, label_field: true },
];

const rows = [{ id: "1", code: "employee" }];

function renderTable(ui: React.ReactElement, initialEntry = "/") {
  const queryClient = new QueryClient();
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>{ui}</MemoryRouter>
    </QueryClientProvider>
  );
}

const baseProps = {
  schema: "domain",
  table: "entity_type",
  tableLabel: "Entity types",
  newHref: "/domain/entity_type/new",
};

describe("DataTable", () => {
  it("renders rows and pagination info", () => {
    renderTable(
      <DataTable
        {...baseProps}
        fields={fields}
        rows={rows}
        total={1}
        limit={20}
        offset={0}
        onPageChange={vi.fn()}
        onDelete={vi.fn()}
      />
    );

    // The record renders in both the table row and the small-screen card
    // markup (G-4) -- scope to the table for the row-content assertion.
    expect(within(screen.getByRole("table")).getByText("employee")).toBeInTheDocument();
    expect(screen.getByText("1-1 of 1")).toBeInTheDocument();
  });

  it("puts the row count text in a polite live region (H-9)", () => {
    renderTable(
      <DataTable
        {...baseProps}
        fields={fields}
        rows={rows}
        total={1}
        limit={20}
        offset={0}
        onPageChange={vi.fn()}
        onDelete={vi.fn()}
      />
    );

    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveTextContent("1-1 of 1");
  });

  it("calls onPageChange with the next offset", () => {
    const onPageChange = vi.fn();
    renderTable(
      <DataTable
        {...baseProps}
        fields={fields}
        rows={rows}
        total={50}
        limit={20}
        offset={0}
        onPageChange={onPageChange}
        onDelete={vi.fn()}
      />
    );

    fireEvent.click(screen.getByText("Next"));
    expect(onPageChange).toHaveBeenCalledWith(20);
  });

  describe("the first cell as a link (E-1/H-2)", () => {
    // A second, non-link column so "click elsewhere in the row" has
    // somewhere to click that isn't inside the <a>.
    const twoColumnFields = [
      { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
      { name: "code", type: "string" as const, required: true, writable: true, is_fk: false, fk_table: null },
      { name: "name", type: "string" as const, required: false, writable: true, is_fk: false, fk_table: null },
    ];
    const twoColumnRows = [{ id: "1", code: "employee", name: "Employee" }];

    it("renders the first visible cell as a link to the record", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      // Rendered in both the table row and the small-screen card markup
      // (G-4) -- scope to the table, which is what this test targets.
      const link = within(screen.getByRole("table")).getByRole("link", { name: "employee" });
      expect(link).toHaveAttribute("href", "/domain/entity_type/1");
    });

    // Defensive guard: the first cell's link/row-click target is built as a real
    // `<a href="…">` from `String(row.id)`, now rendered twice per row (table +
    // small-screen card). On master this id was only ever read inside an
    // onClick, so a missing id silently degraded to a no-op; unguarded here it
    // would instead render a live link to ".../undefined". Ahead of the next
    // project's move to composite primary keys, where a row may have no single
    // usable `id` at all.
    it("renders plain text instead of a link when the row has no usable id", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={[{ code: "employee" }]}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      const table = within(screen.getByRole("table"));
      expect(table.getByText("employee")).toBeInTheDocument();
      expect(table.queryByRole("link", { name: "employee" })).not.toBeInTheDocument();
    });

    it("a plain click on the link navigates once -- it does not also fire the row's onRowClick (fix round 2)", () => {
      const onRowClick = vi.fn();
      renderTable(
        <DataTable
          {...baseProps}
          fields={twoColumnFields}
          rows={twoColumnRows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
          onRowClick={onRowClick}
        />
      );

      fireEvent.click(within(screen.getByRole("table")).getByRole("link", { name: "employee" }));

      // The link's own navigation is the only navigation for this click --
      // the row handler must not also call onRowClick for the same click
      // (that used to push a second history entry for one click).
      expect(onRowClick).not.toHaveBeenCalled();
    });

    it("a ctrl-click on the link does not call onRowClick, so the current tab doesn't also navigate (fix round 2)", () => {
      const onRowClick = vi.fn();
      renderTable(
        <DataTable
          {...baseProps}
          fields={twoColumnFields}
          rows={twoColumnRows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
          onRowClick={onRowClick}
        />
      );

      fireEvent.click(within(screen.getByRole("table")).getByRole("link", { name: "employee" }), { ctrlKey: true });

      expect(onRowClick).not.toHaveBeenCalled();
    });

    it("a meta/shift/alt-click or a non-primary-button click on the link also does not call onRowClick", () => {
      const onRowClick = vi.fn();
      renderTable(
        <DataTable
          {...baseProps}
          fields={twoColumnFields}
          rows={twoColumnRows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
          onRowClick={onRowClick}
        />
      );

      const link = within(screen.getByRole("table")).getByRole("link", { name: "employee" });
      fireEvent.click(link, { metaKey: true });
      fireEvent.click(link, { shiftKey: true });
      fireEvent.click(link, { altKey: true });
      fireEvent.click(link, { button: 1 });

      expect(onRowClick).not.toHaveBeenCalled();
    });

    it("a click on a non-link cell still opens the record, as a convenience", () => {
      const onRowClick = vi.fn();
      renderTable(
        <DataTable
          {...baseProps}
          fields={twoColumnFields}
          rows={twoColumnRows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
          onRowClick={onRowClick}
        />
      );

      fireEvent.click(within(screen.getByRole("table")).getByText("Employee"));

      expect(onRowClick).toHaveBeenCalledWith("1");
    });
  });

  describe("row actions menu (G-3)", () => {
    afterEach(() => {
      vi.restoreAllMocks();
    });

    // The table now renders its own delete trigger *and* the small-screen
    // card renders an equivalent one (fix round 1 for G-4 -- below 768px the
    // table is `hidden`, and the card previously had no actions trigger at
    // all, leaving no way to delete a record on a narrow screen). Both are
    // always in the DOM, so these tests scope to the table's copy, which is
    // what they were written to exercise; the card's copy gets its own
    // dedicated test below.
    it("keeps Delete out of the tab sequence except through a >=32px menu trigger, and the confirm still names the record (D-6)", () => {
      const onDelete = vi.fn();
      vi.spyOn(window, "confirm").mockReturnValue(true);
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={onDelete}
        />
      );

      const table = within(screen.getByRole("table"));
      expect(screen.queryByText("Delete")).not.toBeInTheDocument();

      const trigger = table.getByTestId("row-actions");
      expect(trigger).toHaveAccessibleName("Actions for employee");
      const rect = trigger.className;
      expect(rect).toContain("h-8");
      expect(rect).toContain("w-8");

      fireEvent.click(trigger);
      // fix round 2: the menu itself now renders in a portal (outside the
      // table, to escape its overflow clipping -- see DataTable.tsx), so
      // it's queried unscoped rather than via `table`.
      const deleteItem = screen.getByRole("menuitem", { name: "Delete" });
      fireEvent.click(deleteItem);

      expect(window.confirm).toHaveBeenCalledWith('Delete "employee"? This cannot be undone.');
      expect(onDelete).toHaveBeenCalledWith("1", "employee");
    });

    it("does not trigger onRowClick when the actions menu is opened or Delete is chosen", () => {
      const onRowClick = vi.fn();
      const onDelete = vi.fn();
      vi.spyOn(window, "confirm").mockReturnValue(true);
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={onDelete}
          onRowClick={onRowClick}
        />
      );

      const table = within(screen.getByRole("table"));
      fireEvent.click(table.getByTestId("row-actions"));
      expect(onRowClick).not.toHaveBeenCalled();

      fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
      expect(onRowClick).not.toHaveBeenCalled();
      expect(onDelete).toHaveBeenCalledWith("1", "employee");
    });

    // D-6 fix round 2: DataTable used to have its own local recordLabel() hardcoded to
    // `code` then `name`, so any table labelled by something else (iam.user_account by
    // `username`, domain.entity_state by `state_value` -- see backend/app/crud/labels.py's
    // DEFAULT_LABEL_COLUMNS) fell straight through to the generic "this row" for every
    // single record. DataTable now calls the shared, metadata-driven recordLabel from
    // lib/labels.ts (already used elsewhere, e.g. the edit page's heading) so there is one
    // place that knows how to label a record, not two that can disagree.
    it("labels the record from the table's own label_field metadata, combining code and name when both are flagged (D-6)", () => {
      const onDelete = vi.fn();
      vi.spyOn(window, "confirm").mockReturnValue(true);
      const codeAndNameFields = [
        { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
        { name: "code", type: "string" as const, required: true, writable: true, is_fk: false, fk_table: null, label_field: true },
        { name: "name", type: "string" as const, required: false, writable: true, is_fk: false, fk_table: null, label_field: true },
      ];
      renderTable(
        <DataTable
          {...baseProps}
          fields={codeAndNameFields}
          rows={[{ id: "2", code: "ACME", name: "Acme Corp" }]}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={onDelete}
        />
      );
      fireEvent.click(within(screen.getByRole("table")).getByTestId("row-actions"));
      fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
      expect(window.confirm).toHaveBeenCalledWith('Delete "ACME — Acme Corp"? This cannot be undone.');
      expect(onDelete).toHaveBeenCalledWith("2", "ACME — Acme Corp");
    });

    it("labels the record from a non-code/name label_field column, e.g. `username` (D-6: this is exactly what the old hardcoded helper missed)", () => {
      const onDelete = vi.fn();
      vi.spyOn(window, "confirm").mockReturnValue(true);
      const usernameFields = [
        { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
        { name: "username", type: "string" as const, required: true, writable: true, is_fk: false, fk_table: null, label_field: true },
      ];
      renderTable(
        <DataTable
          {...baseProps}
          fields={usernameFields}
          rows={[{ id: "4", username: "jdoe" }]}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={onDelete}
        />
      );
      fireEvent.click(within(screen.getByRole("table")).getByTestId("row-actions"));
      fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
      expect(window.confirm).toHaveBeenCalledWith('Delete "jdoe"? This cannot be undone.');
      expect(onDelete).toHaveBeenCalledWith("4", "jdoe");
    });

    it("falls back to 'this row' when no field is flagged label_field, or the row has no value for the ones that are", () => {
      const onDelete = vi.fn();
      vi.spyOn(window, "confirm").mockReturnValue(true);
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={[{ id: "3" }]}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={onDelete}
        />
      );
      const trigger = within(screen.getByRole("table")).getByRole("button", { name: "Actions for this row" });
      fireEvent.click(trigger);
      fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
      expect(window.confirm).toHaveBeenCalledWith('Delete "this row"? This cannot be undone.');
      expect(onDelete).toHaveBeenCalledWith("3", "this row");
    });

    it("skips onDelete when the confirmation is cancelled", () => {
      const onDelete = vi.fn();
      vi.spyOn(window, "confirm").mockReturnValue(false);
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={onDelete}
        />
      );

      const table = within(screen.getByRole("table"));
      fireEvent.click(table.getByTestId("row-actions"));
      fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));

      expect(window.confirm).toHaveBeenCalled();
      expect(onDelete).not.toHaveBeenCalled();
    });

    it("closes the menu on an outside click", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      const table = within(screen.getByRole("table"));
      fireEvent.click(table.getByTestId("row-actions"));
      expect(screen.getByRole("menuitem", { name: "Delete" })).toBeInTheDocument();

      fireEvent.mouseDown(document.body);
      expect(screen.queryByRole("menuitem", { name: "Delete" })).not.toBeInTheDocument();
    });

    // T11: the menu is `position: fixed`, placed once from the trigger's rect,
    // so anything that moves the trigger afterwards strands it. `<main>` is the
    // app's scroll container; measured live, scrolling it 150px left the menu
    // pinned at its old coordinates while its row moved out from under it
    // (150px drift), and a 1280->900 resize stranded it 124px sideways. jsdom
    // has no layout, so these assert the dismissal contract rather than pixels.
    it("closes the menu when an ancestor scrolls, so it cannot strand at stale coordinates (T11)", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      const table = within(screen.getByRole("table"));
      fireEvent.click(table.getByTestId("row-actions"));
      expect(screen.getByRole("menuitem", { name: "Delete" })).toBeInTheDocument();

      // `scroll` does not bubble, so this only reaches the handler if it is
      // registered in the capture phase on window -- which is the fix.
      const main = document.createElement("main");
      document.body.appendChild(main);
      fireEvent.scroll(main);

      expect(screen.queryByRole("menuitem", { name: "Delete" })).not.toBeInTheDocument();
    });

    it("closes the menu on a window resize (T11)", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      const table = within(screen.getByRole("table"));
      fireEvent.click(table.getByTestId("row-actions"));
      expect(screen.getByRole("menuitem", { name: "Delete" })).toBeInTheDocument();

      fireEvent.resize(window);

      expect(screen.queryByRole("menuitem", { name: "Delete" })).not.toBeInTheDocument();
    });

    it("closes the menu on Escape and returns focus to the trigger (fix round 2)", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      const table = within(screen.getByRole("table"));
      const trigger = table.getByTestId("row-actions");
      fireEvent.click(trigger);
      expect(screen.getByRole("menuitem", { name: "Delete" })).toBeInTheDocument();

      fireEvent.keyDown(screen.getByRole("menuitem", { name: "Delete" }), { key: "Escape" });

      expect(screen.queryByRole("menuitem", { name: "Delete" })).not.toBeInTheDocument();
      expect(trigger).toHaveFocus();
    });

    it("also closes on Escape when it's pressed on the trigger itself, while the menu is open", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      const table = within(screen.getByRole("table"));
      const trigger = table.getByTestId("row-actions");
      fireEvent.click(trigger);
      expect(screen.getByRole("menuitem", { name: "Delete" })).toBeInTheDocument();

      fireEvent.keyDown(trigger, { key: "Escape" });

      expect(screen.queryByRole("menuitem", { name: "Delete" })).not.toBeInTheDocument();
      expect(trigger).toHaveFocus();
    });

    it("the small-screen card renders its own delete trigger, independent of the table's (fix round 1, G-4)", () => {
      const onDelete = vi.fn();
      vi.spyOn(window, "confirm").mockReturnValue(true);
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={onDelete}
        />
      );

      const card = within(screen.getByTestId("datatable-card"));
      const trigger = card.getByTestId("row-actions");
      expect(trigger).toHaveAccessibleName("Actions for employee");

      fireEvent.click(trigger);
      // Opening the card's menu doesn't also open the table's (independent
      // per-instance state, not a single table-wide "open row" ref) -- both
      // instances' menus portal to the same document.body (fix round 2), so
      // this is asserted by count rather than by DOM position: exactly one
      // "Delete" menu item exists, not two.
      expect(screen.getAllByRole("menuitem", { name: "Delete" })).toHaveLength(1);

      fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
      expect(window.confirm).toHaveBeenCalledWith('Delete "employee"? This cannot be undone.');
      expect(onDelete).toHaveBeenCalledWith("1", "employee");
    });

    // fix round 2: the menu used to be `absolute` inside the table's own
    // `overflow-x-auto` wrapper, which clipped it vertically for a row near
    // the bottom of the scrollable area -- CSS requires a non-`visible`
    // `overflow-x` to make `overflow-y` compute to `auto` too, even though
    // the wrapper only ever wanted horizontal scrolling. Confirmed live
    // with `elementFromPoint` (not a Playwright click, which auto-scrolls a
    // target into view and would hide this) that Delete was physically
    // unreachable there. These two tests exercise the actual escape
    // mechanism -- a portal at `position: fixed` -- rather than real
    // browser layout, which jsdom doesn't compute.
    it("renders the dropdown via a portal outside the table, at a fixed position, so the wrapper's overflow can't clip it (fix round 2, G-3)", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      fireEvent.click(within(screen.getByRole("table")).getByTestId("row-actions"));

      // The fixed-position portal root is now the role="region" landmark
      // wrapper (added to resolve an axe "region" best-practice finding --
      // see the comment in DataTable.tsx), one level outside the role="menu"
      // element itself; the escape-the-clipping-wrapper mechanics this test
      // covers are unchanged, just on that outer node now.
      const region = screen.getByRole("region", { name: "Row actions" });
      expect(region.parentElement).toBe(document.body);
      expect(region.style.position).toBe("fixed");

      const menu = screen.getByRole("menu");
      expect(menu.closest("table")).toBeNull();
      expect(menu.closest(".overflow-x-auto")).toBeNull();
    });

    it("flips the dropdown to open upward when there isn't room below the trigger (fix round 2, G-3)", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      const trigger = within(screen.getByRole("table")).getByTestId("row-actions");
      // Simulate a trigger sitting right at the bottom of a short viewport
      // -- the exact "last row of the scroll area" scenario that was
      // clipped before this fix.
      vi.spyOn(window, "innerHeight", "get").mockReturnValue(200);
      vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue({
        top: 190,
        bottom: 198,
        left: 10,
        right: 42,
        width: 32,
        height: 8,
        x: 10,
        y: 190,
        toJSON: () => {},
      } as DOMRect);

      fireEvent.click(trigger);

      // Positioning styles live on the role="region" portal root (see the
      // comment above and in DataTable.tsx) -- the role="menu" element inside
      // it no longer carries its own inline position.
      const region = screen.getByRole("region", { name: "Row actions" });
      // Opens upward -- above the trigger's own top edge -- instead of the
      // usual few pixels below its bottom edge.
      expect(parseFloat(region.style.top)).toBeLessThan(190);
    });
  });

  describe("sort affordance (E-2)", () => {
    it("exposes aria-sort and a caret on the active column, and an accessible name on sort buttons", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          orderBy="code"
          order="asc"
          onSort={vi.fn()}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      const codeHeader = screen.getByText("code").closest("th") as HTMLElement;
      expect(codeHeader).toHaveAttribute("aria-sort", "ascending");

      const sortButton = screen.getByRole("button", { name: "Sort by code" });
      expect(sortButton).toBeInTheDocument();
      expect(sortButton.className).toContain("h-6");
    });

    it("switches aria-sort to descending and flips the caret", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          orderBy="code"
          order="desc"
          onSort={vi.fn()}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      const codeHeader = screen.getByText("code").closest("th") as HTMLElement;
      expect(codeHeader).toHaveAttribute("aria-sort", "descending");
    });

    it("calls onSort with the column name when a sortable header is clicked", () => {
      const onSort = vi.fn();
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onSort={onSort}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      fireEvent.click(screen.getByRole("button", { name: "Sort by code" }));
      expect(onSort).toHaveBeenCalledWith("code");
    });

    it("renders a caret on a non-active sortable column too, hidden until hover/focus (fix round 2)", () => {
      const twoSortableFields = [
        { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
        { name: "code", type: "string" as const, required: true, writable: true, is_fk: false, fk_table: null },
        { name: "name", type: "string" as const, required: false, writable: true, is_fk: false, fk_table: null },
      ];
      renderTable(
        <DataTable
          {...baseProps}
          fields={twoSortableFields}
          rows={[{ id: "1", code: "employee", name: "Employee" }]}
          total={1}
          limit={20}
          offset={0}
          orderBy="code"
          order="asc"
          onSort={vi.fn()}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      // "code" is active: its caret is fully visible by default.
      const activeCaret = screen.getByRole("button", { name: "Sort by code" }).querySelector("span[aria-hidden]");
      expect(activeCaret).not.toHaveClass("opacity-0");

      // "name" is not active, but it still has a caret in the DOM -- just
      // invisible (opacity-0) until hovered/focused -- rather than no caret
      // at all until the column has already been clicked once.
      const nameButton = screen.getByRole("button", { name: "Sort by name" });
      const inactiveCaret = nameButton.querySelector("span[aria-hidden]") as HTMLElement;
      expect(inactiveCaret).toBeInTheDocument();
      expect(inactiveCaret).toHaveClass("opacity-0");
      expect(inactiveCaret.className).toContain("group-hover:opacity-100");
    });
  });

  describe("table semantics (H-9/H-12)", () => {
    it("has a visually-hidden caption naming the table, scope=col on every header, and an accessible name on the actions column", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      const caption = screen.getByText("Entity types", { selector: "caption" });
      expect(caption).toHaveClass("sr-only");

      const headers = screen.getAllByRole("columnheader");
      expect(headers.length).toBeGreaterThan(0);
      for (const header of headers) {
        expect(header).toHaveAttribute("scope", "col");
      }

      const actionsHeader = headers[headers.length - 1];
      expect(actionsHeader).toHaveTextContent("Actions");
    });
  });

  describe("identifier columns hidden behind a toggle (E-4)", () => {
    it("hides the id column by default and shows it after toggling, syncing ?ids=1 in the URL", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      // "id" column header isn't rendered at all by default.
      expect(screen.queryByText("id")).not.toBeInTheDocument();

      const toggle = screen.getByRole("button", { name: "Show identifiers" });
      // H-9: was text-only with no padding (84x16px, under the 24x24 Target Size minimum).
      expect(toggle.className).toMatch(/py-2/);
      fireEvent.click(toggle);

      expect(screen.getByText("id")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Hide identifiers" })).toBeInTheDocument();
    });

    it("reads the toggle's initial state from ?ids=1 in the URL", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />,
        "/?ids=1"
      );

      expect(screen.getByText("id")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Hide identifiers" })).toBeInTheDocument();
    });

    it("keeps a labelled foreign-key column visible on the default view, hiding only the raw `id` column, and reveals `id` via ?ids=1 (fix round 1)", async () => {
      (apiFetch as any).mockImplementation((path: string) => {
        if (path.includes("/options")) {
          return Promise.resolve([{ id: "org-1", label: "Default Organization" }]);
        }
        return Promise.reject(new Error(`unexpected path ${path}`));
      });

      const fieldsWithFk = [
        { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
        {
          name: "organization_id",
          type: "uuid" as const,
          required: true,
          writable: true,
          is_fk: true,
          fk_table: "iam.organization",
          label: "Organization",
        },
        { name: "code", type: "string" as const, required: true, writable: true, is_fk: false, fk_table: null, label: "Code" },
      ];
      const rowsWithFk = [{ id: "1", organization_id: "org-1", code: "employee" }];

      renderTable(
        <DataTable
          {...baseProps}
          fields={fieldsWithFk}
          rows={rowsWithFk}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      // The raw primary key is hidden by default...
      expect(screen.queryByText("id")).not.toBeInTheDocument();
      // ...but the labelled FK column is shown and resolves to its label,
      // not tucked away just because its name ends in `_id`.
      expect(screen.getByText("Organization")).toBeInTheDocument();
      await waitFor(() => {
        // Also rendered as the small-screen card's heading link (G-4) --
        // scope to the table, which is what this assertion targets.
        expect(within(screen.getByRole("table")).getByText("Default Organization")).toBeInTheDocument();
      });

      // Toggling "Show identifiers" reveals the id column too.
      fireEvent.click(screen.getByRole("button", { name: "Show identifiers" }));
      expect(screen.getByText("id")).toBeInTheDocument();
    });
  });

  describe("empty state (A-5)", () => {
    it("renders a named empty state with the New action instead of a bare header row", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={[]}
          total={0}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      expect(screen.getByText("No entity types yet")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "New" })).toHaveAttribute("href", "/domain/entity_type/new");
      expect(screen.queryByRole("table")).not.toBeInTheDocument();
    });
  });

  describe("human-readable column headers (B-1)", () => {
    const labeledFields = [
      { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
      {
        name: "organization_id",
        type: "uuid" as const,
        required: true,
        writable: true,
        is_fk: true,
        fk_table: "iam.organization",
        label: "Organization",
      },
      { name: "code", type: "string" as const, required: true, writable: true, is_fk: false, fk_table: null, label: "Code" },
    ];

    it("renders field labels as column headers instead of raw snake_case names", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={labeledFields}
          rows={[{ id: "1", code: "employee" }]}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      // organization_id is a labelled FK column, visible without toggling
      // identifiers (fix round 1) -- only the raw `id` column is hidden.
      expect(screen.getByText("Organization")).toBeInTheDocument();
      // Also rendered as the small-screen card's field label (G-4), since
      // "code" isn't the first (linked) column here -- scope to the table.
      expect(within(screen.getByRole("table")).getByText("Code")).toBeInTheDocument();
      expect(screen.queryByText("organization_id")).not.toBeInTheDocument();
    });

    it("falls back to the raw field name when a column has no label", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      expect(screen.getByText("code")).toBeInTheDocument();
    });
  });

  describe("foreign key columns", () => {
    beforeEach(() => {
      (apiFetch as any).mockReset();
    });

    it("renders the resolved label instead of the raw UUID", async () => {
      (apiFetch as any).mockImplementation((path: string) => {
        if (path.includes("/options")) {
          return Promise.resolve([{ id: "11111111-1111-1111-1111-111111111111", label: "Acme Corp" }]);
        }
        return Promise.reject(new Error(`unexpected path ${path}`));
      });

      const fkFields = [
        { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
        {
          name: "organization_id",
          type: "uuid" as const,
          required: true,
          writable: true,
          is_fk: true,
          fk_table: "iam.organization",
        },
      ];
      const fkRows = [{ id: "1", organization_id: "11111111-1111-1111-1111-111111111111" }];

      renderTable(
        <DataTable
          {...baseProps}
          fields={fkFields}
          rows={fkRows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
        // organization_id is a labelled FK column, so it's visible on the
        // default view (fix round 1) -- no need to toggle identifiers to
        // exercise the FK-label resolution behavior under test.
      );

      // Also rendered in the small-screen card markup (G-4) as the row's
      // heading link, since organization_id is the sole/first displayed
      // column here -- scope every query below to the table.
      const table = screen.getByRole("table");
      expect(within(table).getByText("11111111-1111-1111-1111-111111111111")).toBeInTheDocument();

      await waitFor(() => {
        expect(within(table).getByText("Acme Corp")).toBeInTheDocument();
      });

      const call = (apiFetch as any).mock.calls.find(([path]: [string]) => path.includes("/options"));
      expect(call[0]).toContain("/api/iam/organization/options");
      expect(call[0]).toContain("ids=11111111-1111-1111-1111-111111111111");

      // organization_id is now the first *visible* column (since `id` is
      // hidden by default), so its cell wraps the resolved label in the
      // row's link -- the raw id lives in `title` on the containing <td>.
      const cell = within(table).getByText("Acme Corp").closest("td");
      expect(cell).toHaveAttribute("title", "11111111-1111-1111-1111-111111111111");
    });

    it("does not throw when the number of FK tables changes between renders without a key change", async () => {
      (apiFetch as any).mockResolvedValue([]);

      const queryClient = new QueryClient();
      const zeroFkFields = [
        { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
      ];
      const twoFkFields = [
        { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
        {
          name: "organization_id",
          type: "uuid" as const,
          required: true,
          writable: true,
          is_fk: true,
          fk_table: "iam.organization",
        },
        {
          name: "role_type_id",
          type: "uuid" as const,
          required: true,
          writable: true,
          is_fk: true,
          fk_table: "domain.role_type",
        },
      ];
      const zeroFkRows = [{ id: "1" }];
      const twoFkRows = [
        {
          id: "1",
          organization_id: "11111111-1111-1111-1111-111111111111",
          role_type_id: "22222222-2222-2222-2222-222222222222",
        },
      ];

      const { rerender } = render(
        <QueryClientProvider client={queryClient}>
          <MemoryRouter initialEntries={["/?ids=1"]}>
            <DataTable
              {...baseProps}
              fields={zeroFkFields}
              rows={zeroFkRows}
              total={1}
              limit={20}
              offset={0}
              onPageChange={vi.fn()}
              onDelete={vi.fn()}
            />
          </MemoryRouter>
        </QueryClientProvider>
      );

      expect(() => {
        rerender(
          <QueryClientProvider client={queryClient}>
            <MemoryRouter initialEntries={["/?ids=1"]}>
              <DataTable
                {...baseProps}
                fields={twoFkFields}
                rows={twoFkRows}
                total={1}
                limit={20}
                offset={0}
                onPageChange={vi.fn()}
                onDelete={vi.fn()}
              />
            </MemoryRouter>
          </QueryClientProvider>
        );
      }).not.toThrow();

      // The FK ids render (falling back to the raw id, since the mock
      // resolves no labels) once the new queries settle. Also rendered in
      // the small-screen card markup (G-4) -- scope to the table.
      const table = screen.getByRole("table");
      await waitFor(() => {
        expect(within(table).getByText("11111111-1111-1111-1111-111111111111")).toBeInTheDocument();
        expect(within(table).getByText("22222222-2222-2222-2222-222222222222")).toBeInTheDocument();
      });
    });
  });

  describe("small-screen card layout (G-4)", () => {
    const twoColumnFields = [
      { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null },
      { name: "code", type: "string" as const, required: true, writable: true, is_fk: false, fk_table: null, label: "Code" },
      { name: "name", type: "string" as const, required: false, writable: true, is_fk: false, fk_table: null, label: "Name" },
    ];
    const twoColumnRows = [{ id: "1", code: "employee", name: "Employee" }];

    it("renders each row as a card with labelled field/value pairs, in a CSS-only responsive block", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={twoColumnFields}
          rows={twoColumnRows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      // A dedicated small-screen block, hidden at `md` and up via a plain
      // Tailwind class -- no JS viewport listener involved.
      const cards = screen.getByTestId("datatable-cards");
      expect(cards.className).toContain("md:hidden");

      const card = within(cards).getByTestId("datatable-card");
      // The first field is the record's link/heading...
      expect(within(card).getByRole("link", { name: "employee" })).toHaveAttribute(
        "href",
        "/domain/entity_type/1"
      );
      // ...and the remaining fields render as labelled field/value pairs.
      const nameRow = within(card).getByText("Name").closest("div");
      expect(nameRow).not.toBeNull();
      expect(within(nameRow as HTMLElement).getByText("Employee")).toBeInTheDocument();
    });
  });

  describe("schema v1 identifiers (Task 10)", () => {
    // Shapes the backend's meta layer actually reports for v1's generic
    // tables: `bigint` keys arrive as JSON numbers typed "integer", and a
    // foreign key to another v1 table is an "integer" too.
    const intId = { name: "id", type: "integer" as const, required: true, writable: false, is_fk: false, fk_table: null };
    const uuidId = { name: "id", type: "uuid" as const, required: true, writable: false, is_fk: false, fk_table: null };
    const domainFk = {
      name: "domain_id",
      type: "integer" as const,
      required: true,
      writable: true,
      is_fk: true,
      fk_table: "public.domain",
      label: "Domain",
    };
    const nameField = {
      name: "name",
      type: "string" as const,
      required: true,
      writable: true,
      is_fk: false,
      fk_table: null,
      label: "Name",
      label_field: true,
    };
    const problemFields = [intId, domainFk, nameField];

    describe("isIdentifierColumn", () => {
      it("hides an integer surrogate key named id", () => {
        expect(isIdentifierColumn(intId)).toBe(true);
      });

      it("hides a uuid surrogate key named id", () => {
        expect(isIdentifierColumn(uuidId)).toBe(true);
      });

      it("hides a uuid column that has no label to resolve (not a foreign key)", () => {
        expect(isIdentifierColumn({ ...uuidId, name: "token" })).toBe(true);
      });

      it("keeps an integer foreign key visible -- it resolves to a label", () => {
        expect(isIdentifierColumn(domainFk)).toBe(false);
      });

      it("keeps a uuid foreign key visible", () => {
        expect(
          isIdentifierColumn({ ...uuidId, name: "organization_id", is_fk: true, fk_table: "iam.organization" })
        ).toBe(false);
      });

      it("keeps an ordinary integer column visible", () => {
        expect(isIdentifierColumn({ ...intId, name: "sort_order", writable: true })).toBe(false);
      });

      it("keeps a key named id visible when it is itself a foreign key (a shared primary key resolves to a label)", () => {
        expect(isIdentifierColumn({ ...intId, is_fk: true, fk_table: "public.problem" })).toBe(false);
      });
    });

    it("hides the integer id column by default but keeps the integer foreign key column", async () => {
      (apiFetch as any).mockImplementation((path: string) => {
        if (path.includes("/options")) return Promise.resolve([{ id: "7", label: "Rostering" }]);
        return Promise.reject(new Error(`unexpected path ${path}`));
      });
      renderTable(
        <DataTable
          {...baseProps}
          schema="public"
          table="problem"
          fields={problemFields}
          rows={[{ id: 42, domain_id: 7, name: "week 38" }]}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      const table = within(screen.getByRole("table"));
      const headers = table.getAllByRole("columnheader").map((th) => th.textContent);
      expect(headers).toContain("Domain");
      expect(headers).toContain("Name");
      expect(headers).not.toContain("id");
      await waitFor(() => expect(table.getByText("Rostering")).toBeInTheDocument());
    });

    it("renders a row link built from a numeric id, in the table and the card", () => {
      const onDelete = vi.fn();
      vi.spyOn(window, "confirm").mockReturnValue(true);
      renderTable(
        <DataTable
          {...baseProps}
          schema="public"
          table="domain"
          fields={[intId, nameField]}
          rows={[{ id: 42, name: "rostering" }]}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={onDelete}
        />
      );

      const tableLink = within(screen.getByRole("table")).getByRole("link", { name: "rostering" });
      expect(tableLink).toHaveAttribute("href", "/public/domain/42");
      const card = screen.getByTestId("datatable-card");
      expect(within(card).getByRole("link", { name: "rostering" })).toHaveAttribute("href", "/public/domain/42");

      // Delete hands the caller the id as the string its URL needs.
      fireEvent.click(within(screen.getByRole("table")).getByTestId("row-actions"));
      fireEvent.click(screen.getByRole("menuitem", { name: "Delete" }));
      expect(onDelete).toHaveBeenCalledWith("42", "rostering");
      vi.restoreAllMocks();
    });

    it.each([
      ["no id key at all", { name: "rostering" }],
      ["a null id", { id: null, name: "rostering" }],
    ])("renders plain text, not a link, for a row with %s -- in the table and the card", (_label, row) => {
      renderTable(
        <DataTable
          {...baseProps}
          schema="public"
          table="domain"
          fields={[intId, nameField]}
          rows={[row]}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      expect(within(screen.getByRole("table")).getByText("rostering")).toBeInTheDocument();
      expect(screen.queryAllByRole("link", { name: "rostering" })).toHaveLength(0);
      // Guards the specific failure: a live link to ".../undefined" or ".../null".
      for (const link of screen.queryAllByRole("link")) {
        expect(link.getAttribute("href")).not.toMatch(/\/(undefined|null)$/);
      }
    });

    it("gives the row link an accessible name when the first visible cell is empty (axe link-name)", () => {
      const parentFk = {
        name: "parent_id",
        type: "uuid" as const,
        required: false,
        writable: true,
        is_fk: true,
        fk_table: "iam.organization",
        label: "Parent",
      };
      const codeField = { ...nameField, name: "code", label: "Code" };
      renderTable(
        <DataTable
          {...baseProps}
          schema="iam"
          table="organization"
          fields={[parentFk, codeField, uuidId]}
          rows={[{ parent_id: null, code: "default", id: "482f374a" }]}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );

      const tableLink = within(screen.getByRole("table")).getByRole("link", { name: "Open default" });
      expect(tableLink).toHaveAttribute("href", "/iam/organization/482f374a");
      // Something visible to click, too -- an aria-label alone leaves a
      // zero-width link that a sighted keyboard user tabs onto blind.
      expect(tableLink).toHaveTextContent("—");
      const card = screen.getByTestId("datatable-card");
      expect(within(card).getByRole("link", { name: "Open default" })).toHaveAttribute(
        "href",
        "/iam/organization/482f374a"
      );
      expect(within(card).getByRole("link", { name: "Open default" })).toHaveTextContent("—");
    });

    it("leaves a non-empty first cell's link named by its own content", () => {
      renderTable(
        <DataTable
          {...baseProps}
          fields={fields}
          rows={rows}
          total={1}
          limit={20}
          offset={0}
          onPageChange={vi.fn()}
          onDelete={vi.fn()}
        />
      );
      const link = within(screen.getByRole("table")).getByRole("link", { name: "employee" });
      expect(link).not.toHaveAttribute("aria-label");
    });
  });
});
