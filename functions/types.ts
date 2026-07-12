/** Shared types for the Cloudflare Pages Functions API */

export interface Env {
  DB: D1Database;
}

export type SearchSort =
  | "alpha"
  | "number"
  | "absolute_magnitude"
  | "semimajor_axis"
  | "eccentricity"
  | "inclination";

export const SEARCH_SORTS: Record<SearchSort, string> = {
  alpha: "mp.name_ascii COLLATE NOCASE",
  number: "CAST(mp.permid AS INTEGER)",
  absolute_magnitude: "mp.absolute_magnitude_h",
  semimajor_axis: "mp.semimajor_axis",
  eccentricity: "mp.eccentricity",
  inclination: "mp.inclination",
};

export const NUMERIC_NULL_LAST_SORTS = new Set([
  "absolute_magnitude",
  "semimajor_axis",
  "eccentricity",
  "inclination",
]);

export const QUERY_TARGETS = new Set(["both", "name", "citation"]);

export const STOPWORDS = new Set([
  "about", "after", "also", "among", "and", "are", "asteroid",
  "astronomer", "been", "being", "born", "city", "for", "from",
  "has", "his", "honor", "honored", "honours", "into", "its",
  "minor", "named", "planet", "professor", "she", "the", "their",
  "this", "was", "were", "who", "with",
]);

export const WORD_RE = /[A-Za-z][A-Za-z'-]{2,}/g;
