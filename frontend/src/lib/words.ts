/**
 * One vocabulary (simplification plan, phase 4): the platform's terms and the
 * plain words Simple uses for them. Workspace and Data values are said at both
 * levels (benchmark, October 2026: Expert renamed them Domain and Parameters,
 * and testers lost their way); the record words still differ.
 */
import { useEditorLevel } from "../model/editorLevel";

export const WORDS = {
  Domain: ["Workspace", "Workspace"],
  domain: ["workspace", "workspace"],
  "All domains": ["All workspaces", "All workspaces"],
  "This domain": ["This workspace", "This workspace"],
  "Entity type": ["Record type", "Kind of record"],
  "New entity": ["New entity", "New record"],
  Parameters: ["Data values", "Data values"],
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
  const workspace = text
    .replace(/\bDomains\b/g, "Workspaces")
    .replace(/\bDomain\b/g, "Workspace")
    .replace(/\bdomains\b/g, "workspaces")
    .replace(/\bdomain\b/g, "workspace")
    .replace(/\bParameters\b/g, "Data values");
  if (!simple) return workspace.replace(/\bEntity types\b/g, "Record types").replace(/\bEntity type\b/g, "Record type");
  return workspace
    .replace(/\b(Entity|Record) types\b/g, "Kinds of record")
    .replace(/\b(Entity|Record) type\b/g, "Kind of record");
}
