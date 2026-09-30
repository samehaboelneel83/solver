/** The words for a binding's conditions ("team is north"), and what each attribute type can be compared with. */
import type { IrFilter } from "./terms";

export const OP_WORDS: Record<string, string> = {
  "=": "is",
  "!=": "is not",
  "<": "is below",
  "<=": "is at most",
  ">": "is above",
  ">=": "is at least",
  in: "is one of",
  notIn: "is not one of",
};

const ORDERED_TYPES = ["integer", "number", "date", "time"];
export const NUMBER_TYPES = ["integer", "number"];

/** The comparisons an attribute of this type can be tested with. */
export function opsFor(dataType: string | undefined): string[] {
  if (dataType === "boolean") return ["=", "!="];
  if (dataType && ORDERED_TYPES.includes(dataType)) return ["=", "!=", "<", "<=", ">", ">=", "in", "notIn"];
  return ["=", "!=", "in", "notIn"];
}

export const isList = (op: string) => op === "in" || op === "notIn";

/** A starting value that fits the attribute and the comparison. */
export function defaultValue(dataType: string | undefined, op: string): unknown {
  if (isList(op)) return [];
  if (dataType === "boolean") return true;
  if (dataType && NUMBER_TYPES.includes(dataType)) return 0;
  return "";
}

/** A value read back as words: "north", "2", "yes", "north, south". */
export function valueWords(value: unknown): string {
  if (Array.isArray(value)) return value.map(valueWords).join(", ");
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (value !== null && typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** One condition in words: "team is north". */
export function filterWords(filter: IrFilter): string {
  return `${filter.attr} ${OP_WORDS[filter.op] ?? filter.op} ${valueWords(filter.value)}`;
}
