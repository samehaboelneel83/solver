import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import DraftRecovery, { parseDraftBackup } from "./DraftRecovery";
import { clearDraft, readDraft, replayDraft, writeDraft } from "./draftStore";

const seed = () => writeDraft({ problemId: 82, base: "version-6", baseVersion: 2, ir: { variables: {}, extension: "current" } });
const file = (draft: ReturnType<typeof seed>) => ({ size: 500, text: async () => JSON.stringify({ format: "oaas-draft-backup-v1", draft }) });
afterEach(() => clearDraft(82));

it("rejects other problems and starting versions, preserving unknown IR fields", () => {
  const current = seed();
  expect(() => parseDraftBackup(JSON.stringify({ format: "oaas-draft-backup-v1", draft: { ...current, problemId: 83 } }), current)).toThrow(/same starting version/);
  expect(() => parseDraftBackup(JSON.stringify({ format: "oaas-draft-backup-v1", draft: { ...current, base: "scratch" } }), current)).toThrow();
  expect(parseDraftBackup(JSON.stringify({ format: "oaas-draft-backup-v1", draft: current }), current).ir.extension).toBe("current");
});

it("requires confirmation and makes restoring reversible", async () => {
  const current = seed();
  render(<DraftRecovery draft={current} disabled={false} />);
  await act(async () => fireEvent.change(screen.getByLabelText("Restore draft backup"), { target: { files: [file({ ...current, ir: { extension: "backup" } })] } }));
  expect(readDraft(82)?.ir.extension).toBe("current");
  fireEvent.click(screen.getByRole("button", { name: "Restore this backup" }));
  expect(readDraft(82)?.ir.extension).toBe("backup");
  expect(replayDraft(82, "undo")).toBe(true);
  expect(readDraft(82)?.ir.extension).toBe("current");
});

it("refuses to overwrite edits made after the backup preview", async () => {
  const current = seed();
  render(<DraftRecovery draft={current} disabled={false} />);
  await act(async () => fireEvent.change(screen.getByLabelText("Restore draft backup"), { target: { files: [file(current)] } }));
  writeDraft({ ...current, ir: { extension: "newer" } });
  fireEvent.click(screen.getByRole("button", { name: "Restore this backup" }));
  expect(screen.getByRole("status")).toHaveTextContent("draft changed");
  expect(readDraft(82)?.ir.extension).toBe("newer");
});
