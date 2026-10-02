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
  "Entity type": ["Record type", "Kind of record"],
  "New entity": ["New entity", "New record"],
  Parameters: ["Parameters", "Data values"],
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

/** A heading or breadcrumb written in the platform's terms, said in Simple's words: one name for one
 * thing on every screen (user trial: "Domains › Records" beside "Workspace: Giza heatwave"). */
export function plainText(text: string, simple: boolean): string {
  if (!simple) return text.replace(/\bEntity types\b/g, "Record types").replace(/\bEntity type\b/g, "Record type");
  return text
    .replace(/\bDomains\b/g, "Workspaces")
    .replace(/\bDomain\b/g, "Workspace")
    .replace(/\bdomains\b/g, "workspaces")
    .replace(/\bdomain\b/g, "workspace")
    .replace(/\b(Entity|Record) types\b/g, "Kinds of record")
    .replace(/\b(Entity|Record) type\b/g, "Kind of record");
}
