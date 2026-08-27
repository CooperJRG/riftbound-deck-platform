/**
 * Wire types, mirroring `server/riftbound/api/schemas/`.
 *
 * One module per area, matching the server package it mirrors, so a schema change
 * and its type land in files with the same name on both sides.
 */

export type * from "./core";
export type * from "./meta";
export type * from "./smart-decks";
export type * from "./card-meta";
