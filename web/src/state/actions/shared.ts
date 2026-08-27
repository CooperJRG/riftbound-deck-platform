/**
 * The pieces every action group needs.
 *
 * Small on purpose: anything that lives here is something several unrelated features
 * depend on, and that is a cost, not a convenience.
 */

import { ApiError } from "../../api/client";
import { store } from "../store";

export function reportError(error: unknown): void {
  const message =
    error instanceof ApiError
      ? error.message
      : error instanceof Error
        ? error.message
        : String(error);
  store.set({ error: message });
}
