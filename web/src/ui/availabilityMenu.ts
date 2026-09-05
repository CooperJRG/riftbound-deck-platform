/** Reach the existing collection settings from the working surface. */
export function openAvailabilityMenu(): void {
  const menu = document.querySelector<HTMLDetailsElement>(".access-menu");
  if (!menu) return;
  menu.open = true;
  menu.querySelector<HTMLElement>(".mode-btn.is-active, summary")?.focus();
}
