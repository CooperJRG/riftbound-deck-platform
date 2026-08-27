/**
 * Scroll position across navigation.
 *
 * Every view lives in the DOM at once and is toggled with `hidden`, so the page never
 * actually navigates and nothing resets the scroll position for us. Opening a legend
 * from the bottom of the tier wall therefore landed the reader halfway down a page they
 * had never seen the top of — the new content rendered above where they were standing.
 *
 * Two details, both learned the hard way:
 *
 * **There are two scrollers, depending on width.** `.panel` carries `overflow-y: auto`,
 * so on desktop the scroll lives on the `<main>` element and `window.scrollY` is always
 * 0; below 900px that rule flips to `overflow: visible` and the document scrolls
 * instead. Scrolling only the window worked on a phone and did nothing on a laptop.
 *
 * **The jump is instant, never smooth.** A smooth scroll is an animation that runs over
 * the following frames, and the very next thing navigation does is replace the panel's
 * contents — which cancels it, leaving the reader wherever the animation had got to.
 * Measured: a smooth reset from 2,574px settled at 2,552px instead of 0. An instant jump
 * lands before the re-render and survives it, and it is what a real page navigation does
 * anyway.
 */

/** Jump to the top of whichever element is actually scrolling. */
export function scrollToTop(): void {
  if (typeof document === "undefined") return;

  const reset = (target: Element | Window): void => {
    try {
      target.scrollTo({ top: 0, left: 0, behavior: "auto" });
    } catch {
      // Older engines reject the options object; the positional form always works.
      target.scrollTo(0, 0);
    }
  };

  if (typeof window !== "undefined") reset(window);

  // Whichever panel is holding the scroll. Resetting them all is cheaper than working
  // out which view is visible, and a hidden panel sitting at its own top is the state
  // we want it in the next time it is shown anyway.
  document.querySelectorAll(".panel").forEach((panel) => {
    if (panel.scrollTop > 0) reset(panel);
  });
}
