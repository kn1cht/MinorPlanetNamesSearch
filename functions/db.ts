/**
 * Core query building and database helpers  Eported from mpnames/db.py
 */

import {
  Env,
  SEARCH_SORTS,
  NUMERIC_NULL_LAST_SORTS,
  QUERY_TARGETS,
  STOPWORDS,
  WORD_RE,
  type SearchSort,
} from "./types";

// ---------------------------------------------------------------------------
// Parameter helpers (mirror Python server.py helpers)
// ---------------------------------------------------------------------------

export function param(url: URL, key: string, def = ""): string {
  return url.searchParams.get(key) ?? def;
}

export function params(url: URL, key: string): string[] {
  return url.searchParams.getAll(key);
}

export function intParam(url: URL, key: string, def: number): number {
  const v = parseInt(url.searchParams.get(key) ?? "", 10);
  return isNaN(v) ? def : v;
}

// ---------------------------------------------------------------------------
// Query term helpers
// ---------------------------------------------------------------------------

function normalizeQueryTerms(q: string | string[]): string[] {
  const raw = Array.isArray(q) ? q : [q];
  const terms: string[] = [];
  for (const r of raw) {
    const t = r.replace(/\s+/g, " ").trim();
    if (t && !terms.includes(t)) terms.push(t);
  }
  return terms;
}

function splitQueryTerms(q: string | string[]): [string[], string[]] {
  const include: string[] = [];
  const exclude: string[] = [];
  for (const term of normalizeQueryTerms(q)) {
    if (term.startsWith("!")) {
      const neg = term.slice(1).trim();
      if (neg && !exclude.includes(neg)) exclude.push(neg);
    } else {
      include.push(term);
    }
  }
  return [include, exclude];
}

function normalizeQMode(mode: string): "and" | "or" {
  return mode.toLowerCase() === "or" ? "or" : "and";
}

function normalizeQTarget(target: string): string {
  const t = target.toLowerCase();
  return QUERY_TARGETS.has(t) ? t : "both";
}

export function representativeQuery(q: string | string[]): string {
  const [include] = splitQueryTerms(q);
  return include[0] ?? "";
}

function escapeLike(q: string): string {
  return q.replace(/\\/g, "\\\\").replace(/%/g, "\\%").replace(/_/g, "\\_");
}

function useShortTextSearch(q: string): boolean {
  return q.trim().length < 3;
}

function ftsQuery(q: string): string {
  const cleaned = q.replace(/"/g, " ").replace(/\s+/g, " ").trim();
  return `"${cleaned}"`;
}

function ftsQueryForTarget(q: string, qTarget: string): string {
  const base = ftsQuery(q);
  if (qTarget === "name") return `name_ascii:${base} OR name_display:${base}`;
  if (qTarget === "citation") return `citation_text:${base}`;
  return base;
}

function normalizePermidQuery(q: string): string {
  const cleaned = q.trim();
  if (cleaned.startsWith("(") && cleaned.endsWith(")")) {
    const inner = cleaned.slice(1, -1).trim();
    if (/^\d+$/.test(inner)) return inner;
  }
  return cleaned;
}

function normalizeFilterValues(
  value: string | string[],
  splitCommas = true
): string[] {
  const raw = Array.isArray(value) ? value : [value];
  const normalized: string[] = [];
  for (const r of raw) {
    const parts = splitCommas ? r.split(",") : [r];
    for (const p of parts) {
      const cleaned = p.trim();
      if (cleaned && !normalized.includes(cleaned)) normalized.push(cleaned);
    }
  }
  return normalized;
}

function placeholders(values: string[]): string {
  return values.map(() => "?").join(", ");
}

// ---------------------------------------------------------------------------
// Query clause builder
// ---------------------------------------------------------------------------

function queryClause(
  query: string,
  qTarget: string
): [string, (string | number)[]] {
  const likeQuery = `%${escapeLike(query)}%`;

  if (qTarget === "citation") {
    if (useShortTextSearch(query)) {
      return [
        "(COALESCE(mp.citation_text, '') LIKE ? ESCAPE '\\' COLLATE NOCASE)",
        [likeQuery],
      ];
    }
    return [
      "(" +
        "COALESCE(mp.citation_text, '') LIKE ? ESCAPE '\\' COLLATE NOCASE OR " +
        "mp.rowid IN (SELECT rowid FROM minor_planets_fts WHERE minor_planets_fts MATCH ?)" +
        ")",
      [likeQuery, ftsQueryForTarget(query, qTarget)],
    ];
  }

  if (qTarget === "name") {
    if (useShortTextSearch(query)) {
      return [
        "(" +
          "mp.permid LIKE ? ESCAPE '\\' OR " +
          "COALESCE(mp.packed_permid, '') LIKE ? ESCAPE '\\' COLLATE NOCASE OR " +
          "COALESCE(mp.iau_designation, '') LIKE ? ESCAPE '\\' COLLATE NOCASE OR " +
          "mp.name_ascii LIKE ? ESCAPE '\\' COLLATE NOCASE OR " +
          "mp.name_display LIKE ? ESCAPE '\\' COLLATE NOCASE" +
          ")",
        Array(5).fill(likeQuery),
      ];
    }
    return [
      "(" +
        "mp.permid LIKE ? ESCAPE '\\' OR " +
        "COALESCE(mp.packed_permid, '') LIKE ? ESCAPE '\\' COLLATE NOCASE OR " +
        "COALESCE(mp.iau_designation, '') LIKE ? ESCAPE '\\' COLLATE NOCASE OR " +
        "mp.rowid IN (SELECT rowid FROM minor_planets_fts WHERE minor_planets_fts MATCH ?)" +
        ")",
      [likeQuery, likeQuery, likeQuery, ftsQueryForTarget(query, qTarget)],
    ];
  }

  // both
  if (useShortTextSearch(query)) {
    return [
      "(" +
        "mp.permid LIKE ? ESCAPE '\\' OR " +
        "COALESCE(mp.packed_permid, '') LIKE ? ESCAPE '\\' COLLATE NOCASE OR " +
        "COALESCE(mp.iau_designation, '') LIKE ? ESCAPE '\\' COLLATE NOCASE OR " +
        "mp.name_ascii LIKE ? ESCAPE '\\' COLLATE NOCASE OR " +
        "mp.name_display LIKE ? ESCAPE '\\' COLLATE NOCASE OR " +
        "COALESCE(mp.citation_text, '') LIKE ? ESCAPE '\\' COLLATE NOCASE OR " +
        "COALESCE(mp.discovery_site, '') LIKE ? ESCAPE '\\' COLLATE NOCASE OR " +
        "COALESCE(mp.discoverer_text, '') LIKE ? ESCAPE '\\' COLLATE NOCASE" +
        ")",
      Array(8).fill(likeQuery),
    ];
  }
  return [
    "(" +
      "mp.permid LIKE ? ESCAPE '\\' OR " +
      "COALESCE(mp.packed_permid, '') LIKE ? ESCAPE '\\' COLLATE NOCASE OR " +
      "COALESCE(mp.iau_designation, '') LIKE ? ESCAPE '\\' COLLATE NOCASE OR " +
      "mp.rowid IN (SELECT rowid FROM minor_planets_fts WHERE minor_planets_fts MATCH ?)" +
      ")",
    [likeQuery, likeQuery, likeQuery, ftsQueryForTarget(query, qTarget)],
  ];
}

// ---------------------------------------------------------------------------
// Main filter builder
// ---------------------------------------------------------------------------

export interface FilterArgs {
  q: string[];
  qMode: string;
  qTarget: string;
  orbit: string[];
  citationCategory: string[];
  personRole: string[];
  gender: string[];
  discoverer: string[];
  observatory: string[];
  flag: string[];
}

export function buildFilters(args: FilterArgs): {
  where: string;
  params: (string | number)[];
  joins: string;
} {
  const clauses: string[] = [];
  const queryParams: (string | number)[] = [];
  const joinList: string[] = [];

  const normTarget = normalizeQTarget(args.qTarget);
  const [includeTerms, excludeTerms] = splitQueryTerms(args.q);

  if (includeTerms.length > 0) {
    const queryClauses: string[] = [];
    for (const term of includeTerms) {
      const [clause, ps] = queryClause(term, normTarget);
      queryClauses.push(clause);
      queryParams.push(...ps);
    }
    const joiner = normalizeQMode(args.qMode) === "or" ? " OR " : " AND ";
    clauses.push("(" + queryClauses.join(joiner) + ")");
  }
  for (const term of excludeTerms) {
    const [clause, ps] = queryClause(term, normTarget);
    clauses.push(`NOT ${clause}`);
    queryParams.push(...ps);
  }

  const orbitValues = normalizeFilterValues(args.orbit);
  if (orbitValues.length > 0) {
    const orbitClauses: string[] = [];
    const concrete = orbitValues.filter((v) => v !== "Unclassified");
    if (orbitValues.includes("Unclassified")) {
      orbitClauses.push("mp.orbit_type IS NULL");
    }
    if (concrete.length > 0) {
      orbitClauses.push(`mp.orbit_type IN (${placeholders(concrete)})`);
      queryParams.push(...concrete);
    }
    clauses.push("(" + orbitClauses.join(" OR ") + ")");
  }

  const citationValues = normalizeFilterValues(args.citationCategory);
  if (citationValues.length > 0) {
    joinList.push("JOIN categories c_filter ON c_filter.permid = mp.permid");
    clauses.push(
      `c_filter.kind = 'citation' AND c_filter.value IN (${placeholders(citationValues)})`
    );
    queryParams.push(...citationValues);
  }

  const personRoleValues = normalizeFilterValues(args.personRole);
  if (personRoleValues.length > 0) {
    joinList.push("JOIN citation_facets cf_role_filter ON cf_role_filter.permid = mp.permid");
    clauses.push(
      `cf_role_filter.kind = 'person_role' AND cf_role_filter.value IN (${placeholders(personRoleValues)})`
    );
    queryParams.push(...personRoleValues);
  }

  const genderValues = normalizeFilterValues(args.gender);
  if (genderValues.length > 0) {
    joinList.push("JOIN citation_facets cf_gender_filter ON cf_gender_filter.permid = mp.permid");
    clauses.push(
      `cf_gender_filter.kind = 'entity_gender' AND cf_gender_filter.value IN (${placeholders(genderValues)})`
    );
    queryParams.push(...genderValues);
  }

  const discovererValues = normalizeFilterValues(args.discoverer, false);
  if (discovererValues.length > 0) {
    joinList.push(
      "JOIN discovery_facets df_discoverer_filter ON df_discoverer_filter.permid = mp.permid"
    );
    clauses.push(
      `df_discoverer_filter.kind = 'discoverer' AND df_discoverer_filter.value IN (${placeholders(discovererValues)})`
    );
    queryParams.push(...discovererValues);
  }

  const observatoryValues = normalizeFilterValues(args.observatory, false);
  if (observatoryValues.length > 0) {
    joinList.push(
      "JOIN discovery_facets df_observatory_filter ON df_observatory_filter.permid = mp.permid"
    );
    clauses.push(
      `df_observatory_filter.kind = 'observatory' AND df_observatory_filter.value IN (${placeholders(observatoryValues)})`
    );
    queryParams.push(...observatoryValues);
  }

  const flagValues = normalizeFilterValues(args.flag);
  if (flagValues.length > 0) {
    const flagClauses: string[] = [];
    if (flagValues.includes("NEO")) flagClauses.push("mp.is_neo = 1");
    if (flagValues.includes("PHA")) flagClauses.push("mp.is_pha = 1");
    if (flagClauses.length > 0)
      clauses.push("(" + flagClauses.join(" OR ") + ")");
  }

  const where =
    clauses.length > 0 ? "WHERE " + clauses.join(" AND ") : "";
  const joins = joinList.join(" ");
  return { where, params: queryParams, joins };
}

// ---------------------------------------------------------------------------
// ORDER BY builder
// ---------------------------------------------------------------------------

export function buildOrderBy(
  sort: string,
  direction: string,
  q = ""
): { orderBy: string; params: (string | number)[] } {
  const sortKey = (SEARCH_SORTS[sort as SearchSort] ? sort : "number") as SearchSort;
  const dirKey = direction.toLowerCase() === "desc" ? "DESC" : "ASC";
  const expression = SEARCH_SORTS[sortKey];
  const clauses: string[] = [];
  const orderParams: (string | number)[] = [];

  const query = q.trim();
  if (query) {
    const permidQuery = normalizePermidQuery(query);
    const permidPrefixQuery = `${escapeLike(permidQuery)}%`;
    const permidContainsQuery = `%${escapeLike(permidQuery)}%`;
    const textPrefixQuery = `${escapeLike(query)}%`;
    const textContainsQuery = `%${escapeLike(query)}%`;
    clauses.push(`
      CASE
        WHEN mp.permid = ? THEN 0
        WHEN mp.name_ascii = ? COLLATE NOCASE OR mp.name_display = ? COLLATE NOCASE THEN 1
        WHEN mp.permid LIKE ? ESCAPE '\\'
          OR COALESCE(mp.packed_permid, '') LIKE ? ESCAPE '\\' COLLATE NOCASE
          OR COALESCE(mp.iau_designation, '') LIKE ? ESCAPE '\\' COLLATE NOCASE THEN 2
        WHEN mp.name_ascii LIKE ? ESCAPE '\\' COLLATE NOCASE
          OR mp.name_display LIKE ? ESCAPE '\\' COLLATE NOCASE THEN 3
        WHEN mp.permid LIKE ? ESCAPE '\\'
          OR COALESCE(mp.packed_permid, '') LIKE ? ESCAPE '\\' COLLATE NOCASE
          OR COALESCE(mp.iau_designation, '') LIKE ? ESCAPE '\\' COLLATE NOCASE THEN 4
        WHEN mp.name_ascii LIKE ? ESCAPE '\\' COLLATE NOCASE
          OR mp.name_display LIKE ? ESCAPE '\\' COLLATE NOCASE THEN 5
        WHEN COALESCE(mp.citation_text, '') LIKE ? ESCAPE '\\' COLLATE NOCASE THEN 6
        ELSE 7
      END ASC`);
    orderParams.push(
      permidQuery,
      query, query,
      permidPrefixQuery, textPrefixQuery, textPrefixQuery,
      textPrefixQuery, textPrefixQuery,
      permidContainsQuery, textContainsQuery, textContainsQuery,
      textContainsQuery, textContainsQuery,
      textContainsQuery
    );
  }

  if (NUMERIC_NULL_LAST_SORTS.has(sortKey)) {
    clauses.push(`${expression} IS NULL ASC`);
  }
  clauses.push(`${expression} ${dirKey}`);
  if (sortKey !== "number") {
    clauses.push("CAST(mp.permid AS INTEGER) ASC");
  }

  return { orderBy: "ORDER BY " + clauses.join(", "), params: orderParams };
}

// ---------------------------------------------------------------------------
// Citation snippet (mirror Python _make_citation_snippet)
// ---------------------------------------------------------------------------

const SNIPPET_HARD_MAX = 80;
const SNIPPET_CONTEXT = 90;

export function makeCitationSnippet(citation: string, q: string): string {
  if (!citation) return "";
  if (q) {
    const lowerText = citation.toLowerCase();
    const lowerQ = q.toLowerCase();
    const pos = lowerText.indexOf(lowerQ);
    if (pos !== -1) {
      const start = Math.max(0, pos - SNIPPET_CONTEXT);
      const end = Math.min(citation.length, pos + q.length + SNIPPET_CONTEXT);
      const prefix = start > 0 ? "..." : "";
      const suffix = end < citation.length ? "..." : "";
      return (
        prefix +
        citation.slice(start, pos) +
        "\x00" +
        citation.slice(pos, pos + q.length) +
        "\x01" +
        citation.slice(pos + q.length, end) +
        suffix
      );
    }
  }
  return citation.slice(0, SNIPPET_HARD_MAX) + (citation.length > SNIPPET_HARD_MAX ? "..." : "");
}

// ---------------------------------------------------------------------------
// Word cloud helper
// ---------------------------------------------------------------------------

export function extractWords(text: string, counter: Map<string, number>): void {
  const matches = text.matchAll(WORD_RE);
  for (const m of matches) {
    const normalized = m[0].replace(/^['-]+|['-]+$/g, "").toLowerCase();
    if (normalized.length < 3 || STOPWORDS.has(normalized)) continue;
    counter.set(normalized, (counter.get(normalized) ?? 0) + 1);
  }
}

// ---------------------------------------------------------------------------
// CORS / JSON response helpers
// ---------------------------------------------------------------------------

export function jsonResponse(
  data: unknown,
  status = 200,
  extraHeaders: Record<string, string> = {}
): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Access-Control-Allow-Origin": "*",
      ...extraHeaders,
    },
  });
}

/**
 * The data is public and is replaced as a complete D1 snapshot. A short edge
 * cache protects D1 from duplicate UI requests while bounding stale results
 * after a data update.
 */
export const D1_RESPONSE_CACHE_SECONDS = 300;

export function d1CacheHeaders(): Record<string, string> {
  return {
    "Cache-Control": `public, max-age=0, s-maxage=${D1_RESPONSE_CACHE_SECONDS}`,
  };
}

export function parseFilterArgs(url: URL): FilterArgs {
  return {
    q: params(url, "q"),
    qMode: param(url, "q_mode", "and"),
    qTarget: param(url, "q_target", "both"),
    orbit: params(url, "orbit"),
    citationCategory: params(url, "citation_category"),
    personRole: params(url, "person_role"),
    gender: params(url, "gender"),
    discoverer: params(url, "discoverer"),
    observatory: params(url, "observatory"),
    flag: params(url, "flag"),
  };
}
