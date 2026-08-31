export type Theme = "light" | "dark";

const STORAGE_KEY = "riftdesk-theme";

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

export function setTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')?.setAttribute(
    "content",
    theme === "dark" ? "#10141b" : "#f2f1ed",
  );
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // The theme still works for the current page when storage is unavailable.
  }
}

export function toggleTheme(): Theme {
  const next: Theme = currentTheme() === "light" ? "dark" : "light";
  setTheme(next);
  return next;
}
