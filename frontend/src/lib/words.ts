/**
 * One vocabulary (simplification plan, phase 4): the platform's terms and the
 * plain words Simple uses for them. Expert keeps the terms the docs, the API
 * and the model editor use; Simple says what a planner would.
 */
import { useEditorLevel } from "../model/editorLevel";

export const WORDS = {
  Domain: ["Domain", "Workspace"],
  domain: ["domain", "workspace"],
  "All domains": ["All domains", "All workspaces"],
  "This domain": ["This domain", "This workspace"],
  "Entity type": ["Entity type", "Kind of record"],
  "New entity": ["New entity", "New record"],
  Parameters: ["Parameters", "Data values"],
  Objective: ["Objective", "Goal"],
} as const;

export type Term = keyof typeof WORDS;

export function word(term: Term, simple: boolean): string {
  return WORDS[term][simple ? 1 : 0];
}

/** `w("Domain")` -- the term, or its plain word in Simple. */
export function useWords(): (term: Term) => string {
  const [level] = useEditorLevel();
  return (term) => word(term, level === "simple");
}
