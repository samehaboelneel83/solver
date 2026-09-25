/**
 * The look's two switches (queue R22): light, dark or the system's theme, and
 * left-to-right or right-to-left. Both are kept in localStorage and applied to
 * <html> before React renders (`applyStoredLook`, called from main.tsx), so a
 * dark page never flashes white on load.
 */

export type ThemeChoice = "light" | "dark" | "system";
export type Direction = "ltr" | "rtl";

const THEME_KEY = "solver_theme";
const DIR_KEY = "solver_dir";

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Private mode: the choice holds for this page, not the next.
  }
}

export function storedTheme(): ThemeChoice {
  const value = read(THEME_KEY);
  return value === "light" || value === "dark" ? value : "system";
}

export function storedDirection(): Direction {
  return read(DIR_KEY) === "rtl" ? "rtl" : "ltr";
}

function systemDark(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

/** Whether `choice` shows dark right now. */
export function isDark(choice: ThemeChoice): boolean {
  return choice === "dark" || (choice === "system" && systemDark());
}

export function applyTheme(choice: ThemeChoice) {
  write(THEME_KEY, choice);
  const root = document.documentElement;
  root.classList.toggle("dark", isDark(choice));
  root.style.colorScheme = isDark(choice) ? "dark" : "light";
}

export function applyDirection(direction: Direction) {
  write(DIR_KEY, direction);
  document.documentElement.dir = direction;
}

export function applyStoredLook() {
  applyTheme(storedTheme());
  applyDirection(storedDirection());
}
