/**
 * One row of the review screen: `Need 3 - You have [0][1][2][3]`.
 *
 * The interaction the whole feature turns on. Being short one copy of a three-of is the
 * normal case, not an edge case, so it is the default affordance rather than something
 * to discover; and because the common answer is yes, the common answer costs no clicks.
 */

import type { RequirementRow } from "../../api/types";
import { setSmartAnswer } from "../../state/actions";
import { h } from "../../ui/dom";

/** "1 card", not "1 cards". Small, and the wizard is asking for effort while it speaks. */
export function plural(count: number, one: string, many = ""): string {
  const word = count === 1 ? one : many || `${one}s`;
  return `${count} ${word}`;
}

export function cardThumb(row: RequirementRow): HTMLElement {
  const art = row.imageUrl
    ? h("img", { src: row.imageUrl, alt: `${row.name} card`, loading: "lazy" })
    : h("div", { class: "tile-art-empty" }, row.name.slice(0, 1));
  return h("div", { class: "decision-card-art" }, art);
}

/**
 * `Need 3 - You have [0][1][2][3]`.
 *
 * Discrete buttons rather than a number input: the range is tiny, every value is one
 * click away, and there is no way to type something that is not a legal answer.
 * Twelve-rune rows fall back to a stepper, because thirteen buttons is not a row.
 */
function counter(row: RequirementRow, value: number): HTMLElement {
  const choose = (next: number) => setSmartAnswer(row.cardId, next);

  if (row.needed > 4) {
    return h(
      "div",
      { class: "req-counter req-counter-wide" },
      h(
        "button",
        {
          class: "step",
          type: "button",
          disabled: value <= 0,
          aria: { label: `One fewer ${row.name}` },
          on: { click: () => choose(value - 1) },
        },
        "-",
      ),
      h("span", { class: "req-count" }, `${value} / ${row.needed}`),
      h(
        "button",
        {
          class: "step",
          type: "button",
          disabled: value >= row.needed,
          aria: { label: `One more ${row.name}` },
          on: { click: () => choose(value + 1) },
        },
        "+",
      ),
    );
  }

  const options: HTMLElement[] = [];
  for (let n = 0; n <= row.needed; n += 1) {
    options.push(
      h(
        "button",
        {
          class: `req-pip${n === value ? " is-selected" : ""}`,
          type: "button",
          aria: {
            label: `${n} of ${row.name}`,
            pressed: String(n === value),
          },
          on: { click: () => choose(n) },
        },
        String(n),
      ),
    );
  }
  return h("div", { class: "req-counter" }, ...options);
}

export /**
 * The state a row is in, which is not the same question as "is the number below the
 * requirement".
 *
 * One visual state used to cover three situations and mislead in all of them. A
 * checklist row defaults to zero, so an untouched screen rendered every card as a
 * warning: twelve problems reported before the player had done anything. A card they
 * had already told us they lack came back in the same alarm colour as a question, which
 * reads as nagging -- or worse, as the wizard not having listened.
 *
 * So: `awaiting` is a question, `gap` is a settled fact we will work around, and `ready`
 * is confirmation. Only one of the three is the player's problem, and none of them is
 * an error.
 */
type RowState = "awaiting" | "gap" | "ready";

export function rowState(row: RequirementRow, value: number): RowState {
  // "Answered" includes this round, not just previous ones. `row.have` is the value the
  // server seeded the control with, so any other value is the player having moved it --
  // and a card they have just set to zero must not keep asking "how many do you have?".
  const answered = row.known || value !== row.have;
  if (!answered && value < row.needed) return "awaiting";
  return value < row.needed ? "gap" : "ready";
}

function rowNote(row: RequirementRow, state: RowState, value: number): string {
  if (state === "awaiting") return "How many do you have?";
  if (state === "gap") {
    // Say what happens next. A shortfall with no consequence attached reads as a
    // failure the player is expected to fix before they may continue.
    return value === 0
      ? "You do not have this — we will build around it"
      : `You have ${value} of ${row.needed} — we will build around the rest`;
  }
  return row.known ? "You have these" : "Assuming you have these";
}

export function requirementRow(row: RequirementRow, value: number): HTMLElement {
  const state = rowState(row, value);
  // A card they have actually claimed is settled, and should look it. Still adjustable
  // -- people miscount, and people buy singles -- but it must not read as another
  // question, which is what an undifferentiated row does when there are twenty of them.
  const claimed = state === "ready" && (row.known || value !== row.have);
  return h(
    "li",
    { class: `decision-card is-${state}${claimed ? " is-claimed" : ""}` },
    cardThumb(row),
    h(
      "div",
      { class: "req-body" },
      h("span", { class: "req-name" }, row.name),
      h(
        "span",
        { class: "req-meta" },
        row.needed === 1 ? "Need 1" : `Need ${row.needed}`,
        row.rarity ? ` · ${row.rarity}` : "",
      ),
      h("span", { class: `req-note is-${state}` }, rowNote(row, state, value)),
    ),
    counter(row, value),
  );
}

export /**
 * The deck, grouped so the round reads as one object rather than a quiz.
 *
 * Within each zone the cards we are actually asking about come first. A card the player
 * has already settled stays visible -- they may have miscounted, or bought singles since
 * -- but it does not compete for attention with a question, and it never repeats the
 * question it already answered.
 */
function requirementList(rows: RequirementRow[], answers: Map<string, number>): HTMLElement {
  const groups: { zone: RequirementRow["zone"]; title: string; note: string }[] = [
    { zone: "legend", title: "Identity", note: "Legend and deck identity" },
    { zone: "main", title: "Main deck", note: "The complete game plan" },
    { zone: "runes", title: "Runes", note: "Resource base" },
    { zone: "battlefields", title: "Battlefields", note: "Field package" },
    { zone: "ask", title: "Possible swaps", note: "Cards that can change the build" },
  ];

  const valueOf = (row: RequirementRow) => answers.get(row.cardId) ?? row.have;
  const rank: Record<RowState, number> = { awaiting: 0, gap: 1, ready: 2 };

  return h(
    "div",
    { class: "decision-map" },
    ...groups.map((group) => {
      const members = rows.filter((row) => row.zone === group.zone);
      if (!members.length) return null;

      const ordered = [...members].sort(
        (a, b) => rank[rowState(a, valueOf(a))] - rank[rowState(b, valueOf(b))],
      );
      const asking = members.filter(
        (row) => rowState(row, valueOf(row)) === "awaiting",
      ).length;
      const gaps = members.filter((row) => rowState(row, valueOf(row)) === "gap").length;
      const copies = members.reduce((sum, row) => sum + row.needed, 0);

      // Say what this section wants from the player, rather than only how big it is.
      // "All set" would overstate an untouched deck round: nothing has been confirmed,
      // we are assuming, and the player needs to know they are being asked for
      // exceptions rather than congratulated.
      const anyKnown = members.some((row) => row.known);
      const summary = asking
        ? `${asking} to answer`
        : gaps
          ? `${gaps} we will build around`
          : anyKnown
            ? "All set"
            : "Mark anything you lack";

      return h(
        "section",
        { class: `decision-zone decision-zone-${group.zone}` },
        h(
          "header",
          {},
          h("div", {}, h("h4", {}, group.title), h("p", {}, group.note)),
          h(
            "span",
            { class: asking ? "zone-status is-asking" : "zone-status" },
            summary,
            h("small", {}, `${plural(members.length, "card")} · ${plural(copies, "copy", "copies")}`),
          ),
        ),
        h(
          "ul",
          { class: "req-list decision-grid" },
          ...ordered.map((row) => requirementRow(row, valueOf(row))),
        ),
      );
    }),
  );
}
