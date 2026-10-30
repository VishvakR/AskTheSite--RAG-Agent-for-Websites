export type Theme = "light" | "dark" | "system";

const KEY = "askthesite.theme";

export function storedTheme(): Theme {
  try {
    const value = localStorage.getItem(KEY);
    if (value === "light" || value === "dark" || value === "system") return value;
  } catch {
    /* private mode / storage disabled */
  }
  return "system";
}

export function applyTheme(theme: Theme): void {
  const prefersDark =
    window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  const dark = theme === "dark" || (theme === "system" && prefersDark);
  document.documentElement.classList.toggle("dark", dark);
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* ignore */
  }
}
