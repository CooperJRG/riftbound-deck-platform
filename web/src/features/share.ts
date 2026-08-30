/**
 * Copying the address of the thing you are looking at.
 *
 * The router already makes every page addressable; this is the button that says so.
 * Worth its own control rather than leaving people to select the address bar, because
 * the interesting case is a deck -- whose link is long, carries the whole list, and is
 * the one nobody would think to copy by hand.
 */

import { store } from "../state/store";
import { exploreForState, routeForState } from "../state/routing";
import { absoluteUrl, pathFor, type Route } from "../ui/router";
import { h } from "../ui/dom";

/** Clipboard, with the pre-permissions fallback for a non-secure origin. */
export async function copyToClipboard(value: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    const fallback = document.createElement("textarea");
    fallback.value = value;
    fallback.style.position = "fixed";
    fallback.style.opacity = "0";
    document.body.appendChild(fallback);
    fallback.select();
    let ok = false;
    try {
      ok = document.execCommand("copy");
    } catch {
      ok = false;
    }
    fallback.remove();
    return ok;
  }
}

/** The link for a page, absolute, ready to paste somewhere else. */
export function shareUrl(route?: Route): string {
  return absoluteUrl(pathFor(route ?? routeForState(), exploreForState()));
}

async function copyShareLink(route: Route | undefined, what: string): Promise<void> {
  const url = shareUrl(route);
  const ok = await copyToClipboard(url);
  store.set({
    notice: ok
      ? `Link to ${what} copied. Anyone with it opens the same page.`
      : `Could not reach the clipboard. The link is ${url}`,
  });
}

/**
 * A "copy link" button for the current page.
 *
 * ``what`` finishes the sentence in the notice, so it reads as a description of what
 * the recipient will see rather than as a generic confirmation.
 */
export function shareButton(
  what: string,
  opts: { route?: Route; label?: string; className?: string } = {},
): HTMLElement {
  return h(
    "button",
    {
      class: opts.className ?? "quiet-button share-button",
      type: "button",
      title: "Copy a link to this page",
      on: { click: () => void copyShareLink(opts.route, what) },
    },
    opts.label ?? "Copy link",
  );
}
