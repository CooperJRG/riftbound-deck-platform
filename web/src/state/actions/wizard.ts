/**
 * Smart Decks: one round of the wizard at a time.
 *
 * The answers are the expensive part of a session, so every round is sent as it is
 * given rather than batched at the end.
 */

import { api } from "../../api/client";
import type { SmartSession } from "../../api/types";
import { scrollToTop } from "../../ui/scroll";
import { store } from "../store";
import { reportError } from "./shared";
import { loadDeck } from "./library";
import { loadMeta } from "./meta";

/**
 * The answers for the round on screen.
 *
 * Seeded from the requirement rows, which default to "you have what this asks for".
 * That default is the whole ergonomic argument: the common answer is yes, so the
 * common answer should cost no clicks, and the player only touches the rows where
 * they are short.
 */
function seedAnswers(session: SmartSession | null): Map<string, number> {
  const answers = new Map<string, number>();
  const proposal = session?.proposal;
  if (!proposal) return answers;
  const rows = proposal.question ? proposal.question.cards : proposal.requirements;
  for (const row of rows) answers.set(row.cardId, row.have);
  return answers;
}

export async function openSmartDecks(options: { retry?: boolean } = {}): Promise<void> {
  store.set({ view: "find" });
  if (store.state.smartLegendsLoaded && store.state.smartLegends.length) return;

  // A retry keeps the error panel on screen and marks the button busy, rather than
  // swapping in a loading state. Against a local server the request finishes in
  // milliseconds, so a flash of "Loading..." followed by the identical error reads as
  // a button that did nothing at all -- which is how a working retry got reported as
  // broken.
  store.set(
    options.retry
      ? { smartLegendsRetrying: true }
      : { smartBusy: true, smartLegendsError: "" },
  );
  try {
    const [smartLegends, refresh] = await Promise.all([
      api.smartLegends(),
      // Best-effort: the picker is still usable without it.
      api.refreshStatus().catch(() => null),
    ]);
    store.set({
      smartLegends,
      refresh,
      smartBusy: false,
      smartLegendsRetrying: false,
      smartLegendsLoaded: true,
      smartLegendsError: "",
      smartLegendsAttempts: 0,
    });
  } catch (error) {
    // Record why rather than falling through to an empty list. An empty picker after
    // a failed request is not "no decks are loaded", and saying so sends somebody to
    // run a pipeline that was never the problem.
    const message = error instanceof Error ? error.message : String(error);
    store.set({
      smartBusy: false,
      smartLegendsRetrying: false,
      smartLegendsLoaded: true,
      smartLegendsError: message,
      smartLegendsAttempts: store.state.smartLegendsAttempts + 1,
    });
  }
}

export function retrySmartLegends(): Promise<void> {
  return openSmartDecks({ retry: true });
}

/**
 * Harvest now rather than waiting for the timer.
 *
 * The answer to "run the meta pipeline" for somebody looking at a web page who does
 * not want to go and find a terminal.
 */
export async function refreshMetaNow(): Promise<void> {
  store.set({ refreshBusy: true });
  try {
    const refresh = await api.refreshNow();
    const run = refresh.lastRun;
    store.set({
      refresh,
      refreshBusy: false,
      smartLegendsLoaded: false,
      notice: run?.ok
        ? `Meta updated: ${run.deckCount} decks.`
        : `Refresh did not complete. ${run?.message ?? ""}`.trim(),
    });
    // The snapshot changed underneath us, so anything derived from it is stale.
    await Promise.all([openSmartDecks(), loadMeta()]);
  } catch (error) {
    reportError(error);
    store.set({ refreshBusy: false });
  }
}

export function setSmartLegendQuery(query: string): void {
  store.set({ smartLegendQuery: query });
}

export async function startSmartSession(legendId: string): Promise<void> {
  store.set({ smartBusy: true, smartFinished: false });
  try {
    const session = await api.startSmartSession(legendId);
    store.set({ smartSession: session, smartAnswers: seedAnswers(session), smartBusy: false });
  } catch (error) {
    reportError(error);
    store.set({ smartBusy: false });
  }
}

/** Record one card's count for the round on screen. Nothing is sent until submit. */
export function setSmartAnswer(cardId: string, count: number): void {
  const answers = new Map(store.state.smartAnswers);
  answers.set(cardId, Math.max(0, count));
  store.set({ smartAnswers: answers });
}

export async function submitSmartRound(): Promise<void> {
  const { smartSession, smartAnswers } = store.state;
  const proposal = smartSession?.proposal;
  if (!smartSession || !proposal) return;

  const have: Record<string, number> = {};
  for (const [cardId, count] of smartAnswers) have[cardId] = count;

  const wasChecklist = Boolean(proposal.question);
  store.set({ smartBusy: true });
  try {
    const next = await api.answerSmartSession(
      smartSession.sessionId,
      proposal.question
        ? // A checklist must name every card it showed. Without that, a card left at
          // zero is indistinguishable from one never asked about.
          { have, asked: proposal.question.cards.map((row) => row.cardId) }
        : { deckId: proposal.deck?.deckId ?? "", have },
    );
    store.set({ smartSession: next, smartAnswers: seedAnswers(next), smartBusy: false });

    // The replacement round is the last question there is, so the next thing the player
    // sees is the deck itself -- shown, with what changed and why, and one more pass to
    // rule out anything they would rather not play.
    //
    // It used to jump straight to the builder here. That is a card-search workspace with
    // a deck panel down one side: a place to work on a deck, not a place to be shown
    // one, and arriving there after answering questions made it hard to tell what the
    // app had decided.
    //
    // Only after a checklist: a deck round is a review the player is still working
    // through, and jumping them out of it would take away the choice to keep looking.
    if (wasChecklist && (next.proposal?.chosen || next.proposal?.floor)) {
      store.set({ smartShowing: "finish" });
    }
  } catch (error) {
    reportError(error);
    store.set({ smartBusy: false });
  }
}

/**
 * Rule cards out by preference and rebuild around them.
 *
 * Deliberately not folded into the ownership answers. "I do not want to play this" is a
 * claim about a person; "I have none of these" is a claim about a collection. Recording
 * the first as the second would have the wizard tell somebody they cannot build a deck
 * they own every card for, and would write "does not own" into their collection on the
 * opt-in save.
 */
export async function declineSmartCards(cardIds: string[]): Promise<void> {
  const { smartSession } = store.state;
  if (!smartSession) return;
  store.set({ smartBusy: true });
  try {
    const next = await api.declineSmartCards(smartSession.sessionId, cardIds);
    store.set({ smartSession: next, smartAnswers: seedAnswers(next), smartBusy: false });
  } catch (error) {
    reportError(error);
    store.set({ smartBusy: false });
  }
}


/** Take one of the offered decks into the library and open it in the builder. */
export async function acceptSmartDeck(which: "floor" | "conservative" | "free"): Promise<void> {
  const { smartSession } = store.state;
  if (!smartSession) return;
  store.set({ smartBusy: true });
  try {
    const finished = await api.acceptSmartDeck(smartSession.sessionId, which);
    store.set({
      smartSession: finished,
      smartFinished: true,
      smartBusy: false,
      savedDecks: await api.listDecks(),
      notice: "Saved to your decks.",
    });
    await loadDeck(finished.savedDeckId);
    // Open it. The deck was already loaded into the builder's state here, but the view
    // stayed on the wizard, so the player was left looking at a summary of a deck the
    // app had already put somewhere else.
    //
    // Set directly rather than through `setView`: app.ts already imports this module, and
    // for "build" that function only scrolls and sets the view, so the cycle would buy
    // nothing.
    scrollToTop();
    store.set({ view: "build" });
  } catch (error) {
    reportError(error);
    store.set({ smartBusy: false });
  }
}

/**
 * Opt-in write-back of what the session learned.
 *
 * Only ever called from an explicit button. "I don't have this, for this deck, right
 * now" is not the same claim as "I do not own this card", and someone answering
 * quickly to get a deck should not have a permanent fact recorded on their behalf.
 */
export async function saveSmartCollection(): Promise<void> {
  const { smartSession } = store.state;
  if (!smartSession) return;
  store.set({ smartBusy: true });
  try {
    const result = await api.saveSmartCollection(smartSession.sessionId);
    const skipped = result.skippedLowerBounds
      ? ` ${result.skippedLowerBounds} left alone, because "I have them all" is not a count.`
      : "";
    store.set({
      smartBusy: false,
      availability: await api.availability(),
      notice: `Saved ${result.copiesWritten} copies of ${result.cardsWritten} cards to your collection.${skipped}`,
    });
  } catch (error) {
    reportError(error);
    store.set({ smartBusy: false });
  }
}

export function closeSmartSession(): void {
  store.set({
    smartSession: null,
    smartAnswers: new Map(),
    smartFinished: false,
    smartShowing: "rounds",
  });
}
