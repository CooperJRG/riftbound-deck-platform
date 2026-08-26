/**
 * DOM construction helpers.
 *
 * Everything the UI renders goes through `h()`, which sets `textContent` and never
 * parses markup. v2 built its UI by concatenating strings into `innerHTML` at 67
 * sites, guarded by hand-rolled `esc()` / `escAttr()` helpers that had to be
 * remembered every time. Here escaping is structural: there is no code path that
 * interprets a card name or a rules message as HTML.
 */

type Falsy = null | undefined | false;
export type Child = Node | string | number | Falsy;

interface Attributes {
  class?: string;
  title?: string;
  id?: string;
  type?: string;
  value?: string;
  placeholder?: string;
  disabled?: boolean;
  checked?: boolean;
  selected?: boolean;
  href?: string;
  /** Link target — used for third-party sources, always with rel="noopener". */
  target?: "_blank" | "_self";
  rel?: string;
  src?: string;
  alt?: string;
  loading?: "lazy" | "eager";
  role?: string;
  style?: string;
  /** `data-*` attributes. */
  data?: Record<string, string>;
  /** `aria-*` attributes. */
  aria?: Record<string, string>;
  /** Event handlers, e.g. `{ click: () => ... }`. */
  on?: Partial<{
    [K in keyof HTMLElementEventMap]: (event: HTMLElementEventMap[K]) => void;
  }>;
}

export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Attributes = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  const { data, aria, on, ...plain } = attrs;

  for (const [key, value] of Object.entries(plain)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") element.className = String(value);
    else if (value === true) element.setAttribute(key, "");
    else element.setAttribute(key, String(value));
  }
  for (const [key, value] of Object.entries(data ?? {})) {
    element.dataset[key] = value;
  }
  for (const [key, value] of Object.entries(aria ?? {})) {
    element.setAttribute(`aria-${key}`, value);
  }
  for (const [event, handler] of Object.entries(on ?? {})) {
    element.addEventListener(event, handler as EventListener);
  }

  append(element, children);
  return element;
}

export function append(parent: Node, children: Child[]): void {
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    parent.appendChild(
      child instanceof Node ? child : document.createTextNode(String(child)),
    );
  }
}

/** Replace an element's children. */
export function replace(parent: Element, ...children: Child[]): void {
  parent.replaceChildren();
  append(parent, children);
}

export function fragment(...children: Child[]): DocumentFragment {
  const frag = document.createDocumentFragment();
  append(frag, children);
  return frag;
}

export function query<T extends Element = HTMLElement>(selector: string): T {
  const found = document.querySelector<T>(selector);
  if (!found) throw new Error(`Expected an element matching ${selector}`);
  return found;
}

/** Debounce, for search-as-you-type. */
export function debounce<A extends unknown[]>(
  fn: (...args: A) => void,
  ms: number,
): (...args: A) => void {
  let timer: number | undefined;
  return (...args: A) => {
    if (timer !== undefined) window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), ms);
  };
}
