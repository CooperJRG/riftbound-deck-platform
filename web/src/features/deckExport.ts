/** A calm hand-off from the visual builder to the plain-text deck ecosystem. */

import { api, type DeckTextExport } from "../api/client";
import { store } from "../state/store";
import { h, replace } from "../ui/dom";

let dialog: HTMLDialogElement | null = null;

function closeExport(): void {
  if (dialog?.open) dialog.close();
}

async function copyText(value: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    const fallback = document.createElement("textarea");
    fallback.value = value;
    fallback.style.position = "fixed";
    fallback.style.opacity = "0";
    document.body.appendChild(fallback);
    fallback.select();
    document.execCommand("copy");
    fallback.remove();
  }
  store.set({ notice: "Deck list copied to the clipboard." });
}

function download(result: DeckTextExport): void {
  const url = URL.createObjectURL(new Blob([result.text], { type: "text/plain;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = result.filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  store.set({ notice: `Exported ${result.filename}.` });
}

function resultView(result: DeckTextExport): HTMLElement[] {
  return [
    h(
      "header",
      { class: "export-head" },
      h("div", {}, h("p", { class: "eyebrow" }, "Ready to share"), h("h2", { id: "deck-export-title" }, "Export deck")),
      h("button", { class: "dialog-x", type: "button", aria: { label: "Close export" }, on: { click: closeExport } }, "×"),
    ),
    h("p", { class: "export-lede" }, "One card entry per line, grouped by deck zone. Copy it into another tool or keep the text file."),
    h("pre", { class: "export-text" }, result.text.trimEnd()),
    h(
      "div",
      { class: "export-actions" },
      h("button", { class: "quiet-button", type: "button", on: { click: () => void copyText(result.text) } }, "Copy list"),
      h("button", { class: "primary", type: "button", on: { click: () => download(result) } }, "Download .txt"),
    ),
  ];
}

function ensureDialog(): HTMLDialogElement {
  if (dialog) return dialog;
  dialog = h("dialog", { class: "export-dialog", aria: { labelledby: "deck-export-title" } }) as HTMLDialogElement;
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) closeExport();
  });
  document.body.appendChild(dialog);
  return dialog;
}

export async function openDeckExport(): Promise<void> {
  const node = ensureDialog();
  replace(
    node,
    h("div", { class: "dialog-loading" }, h("span", { class: "eyebrow" }, "Preparing your list"), h("strong", {}, "Formatting every zone…")),
  );
  if (!node.open) node.showModal();
  try {
    const result = await api.exportDeck(store.state.deck);
    replace(node, ...resultView(result));
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    replace(
      node,
      h("div", { class: "dialog-loading" }, h("strong", {}, "Couldn’t export this deck."), h("p", {}, message), h("button", { class: "quiet-button", type: "button", on: { click: closeExport } }, "Close")),
    );
  }
}
