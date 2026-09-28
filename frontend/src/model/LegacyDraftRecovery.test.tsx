import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { setToken } from "../api/client";
import LegacyDraftRecovery from "./LegacyDraftRecovery";
import { clearDraft, readDraft } from "./draftStore";

const tokenFor = (sub: string) => `header.${btoa(JSON.stringify({ sub }))}.signature`;
const legacy = () => localStorage.setItem("solver_model_draft_91", JSON.stringify({ problemId: 91, base: "scratch", ir: { sets: ["secret-set"] }, editedAt: "2026-09-01T10:00:00.000Z" }));
afterEach(() => { clearDraft(91); localStorage.clear(); });

it("shows nothing without a legacy draft", () => {
  setToken(tokenFor("alice"));
  const { container } = render(<LegacyDraftRecovery problemId={91} />);
  expect(container).toBeEmptyDOMElement();
});

it("requires an attestation, never shows contents, and keeps the original", () => {
  legacy();
  setToken(tokenFor("alice"));
  render(<LegacyDraftRecovery problemId={91} />);
  expect(screen.queryByText(/secret-set/)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Recover the older draft into my account" }));
  const confirm = screen.getByRole("button", { name: "Recover this draft" });
  expect(confirm).toBeDisabled();
  fireEvent.click(screen.getByLabelText("I wrote this draft in this browser."));
  fireEvent.click(confirm);
  expect(screen.getByText(/Recovered as your unpublished draft/)).toBeInTheDocument();
  expect(screen.getByText(/You recovered the older browser draft/)).toBeInTheDocument();
  expect(readDraft(91)?.ir.sets).toEqual(["secret-set"]);
  expect(localStorage.getItem("solver_model_draft_91")).not.toBeNull();
});

it("tells another account the draft was recovered, without offering it", () => {
  legacy();
  setToken(tokenFor("alice"));
  const alice = render(<LegacyDraftRecovery problemId={91} />);
  fireEvent.click(screen.getByRole("button", { name: "Recover the older draft into my account" }));
  fireEvent.click(screen.getByLabelText("I wrote this draft in this browser."));
  fireEvent.click(screen.getByRole("button", { name: "Recover this draft" }));
  alice.unmount();
  setToken(tokenFor("bob"));
  render(<LegacyDraftRecovery problemId={91} />);
  expect(screen.getByText(/recovered by another account/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Recover/ })).toBeNull();
});

it("asks a signed-out visitor to sign in instead of offering recovery", () => {
  legacy();
  setToken(null);
  render(<LegacyDraftRecovery problemId={91} />);
  expect(screen.getByText(/Sign in with the account that wrote it/)).toBeInTheDocument();
  expect(screen.queryByRole("button")).toBeNull();
});
