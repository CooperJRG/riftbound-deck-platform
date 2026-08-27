/**
 * Every state transition, grouped by the part of the app it belongs to.
 *
 * Views import from here, so splitting the modules changed no call sites. The
 * groups are not arbitrary: each file is the set of actions that share a slice of
 * state, which is what makes a change to one of them easy to reason about.
 */

export * from "./shared";
export * from "./app";
export * from "./cards";
export * from "./deck";
export * from "./library";
export * from "./availability";
export * from "./explore";
export * from "./meta";
export * from "./wizard";
