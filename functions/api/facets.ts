import { Env } from "../types";
import {
  d1CacheHeaders,
  jsonResponse,
  parseFilterArgs,
  buildFilters,
  rateLimitResponse,
  type FilterArgs,
} from "../db";

export const onRequestGet: PagesFunction<Env> = async (ctx) => {
  const cached = await caches.default.match(ctx.request);
  if (cached) return cached;

  const limited = await rateLimitResponse(
    ctx.request,
    "facets",
    12,
    60
  );
  if (limited) return limited;

  const url = new URL(ctx.request.url);
  const db = ctx.env.DB;

  const filterArgs = parseFilterArgs(url);
  const { joins, where } = buildFilters(filterArgs);

  // The unfiltered facet counts are calculated during ingest and stored with
  // the initial-view snapshot.  Serving that one row avoids an eight-query
  // aggregate batch for cache misses caused by a direct or cross-region call.
  const facets = (!joins && !where ? await baseFacetsSnapshot(db) : null)
    ?? await buildFacets(db, filterArgs);
  const response = jsonResponse(facets, 200, d1CacheHeaders());
  ctx.waitUntil(caches.default.put(ctx.request, response.clone()));
  return response;
};

type FacetValue = { value: string; count: number };

type FacetPayload = {
  orbit_types: FacetValue[];
  citation_categories: FacetValue[];
  person_roles: FacetValue[];
  genders: FacetValue[];
  discoverers: FacetValue[];
  observatories: FacetValue[];
  flags: FacetValue[];
};

async function baseFacetsSnapshot(db: D1Database): Promise<FacetPayload | null> {
  try {
    const snapshot = await db.prepare(
      "SELECT payload_json FROM dataset_stats WHERE cache_key = 'base'"
    ).first<{ payload_json: string }>();
    if (!snapshot) return null;
    return parseFacetPayload(JSON.parse(snapshot.payload_json));
  } catch (error) {
    // An older import can briefly lack dataset_stats.  Preserve the dynamic
    // query fallback until the next completed snapshot is available.
    console.warn("base facet snapshot unavailable; calculating facets", error);
    return null;
  }
}

function parseFacetPayload(value: unknown): FacetPayload | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const payload = value as Record<string, unknown>;
  const orbitTypes = facetValues(payload.orbit_types);
  const citationCategories = facetValues(payload.citation_categories);
  const personRoles = facetValues(payload.person_roles);
  const genders = facetValues(payload.genders);
  const discoverers = facetValues(payload.discoverers);
  const observatories = facetValues(payload.observatories);
  const flags = facetValues(payload.flags);

  if (!orbitTypes || !citationCategories || !personRoles || !genders
    || !discoverers || !observatories || !flags) return null;

  return {
    orbit_types: orbitTypes,
    citation_categories: citationCategories,
    person_roles: personRoles,
    genders,
    discoverers,
    observatories,
    flags,
  };
}

function facetValues(value: unknown): FacetValue[] | null {
  if (!Array.isArray(value)) return null;
  if (!value.every((item) => item && typeof item === "object"
    && typeof (item as FacetValue).value === "string"
    && typeof (item as FacetValue).count === "number")) return null;
  return value as FacetValue[];
}

async function buildFacets(
  db: D1Database,
  filterArgs: FilterArgs,
) {
  // A facet is evaluated against every *other* facet group.  Its own
  // selections are left out so choices within that group are alternatives
  // (OR), while filters from different groups remain cumulative (AND).
  const orbit = facetContext(filterArgs, "orbit");
  const citationCategory = facetContext(filterArgs, "citationCategory");
  const personRole = facetContext(filterArgs, "personRole");
  const gender = facetContext(filterArgs, "gender");
  const discoverer = facetContext(filterArgs, "discoverer");
  const observatory = facetContext(filterArgs, "observatory");
  const flag = facetContext(filterArgs, "flag");

  // Execute all queries in a single round-trip to D1
  const [
    orbitRes,
    citationRes,
    personRoleRes,
    genderRes,
    discovererRes,
    observatoryRes,
    neoRes,
    phaRes,
  ] = await db.batch([
    db.prepare(
      `SELECT COALESCE(mp.orbit_type, 'Unclassified') AS value, COUNT(DISTINCT mp.permid) AS count
       FROM minor_planets mp ${orbit.joins} ${orbit.where}
       GROUP BY 1 ORDER BY count DESC, 1`
    ).bind(...orbit.params),

    db.prepare(
      `SELECT c.value, COUNT(DISTINCT mp.permid) AS count
       FROM minor_planets mp ${citationCategory.joins}
       JOIN categories c ON mp.permid = c.permid AND c.kind = 'citation'
       ${citationCategory.where}
       GROUP BY 1 ORDER BY count DESC, 1`
    ).bind(...citationCategory.params),

    db.prepare(
      `SELECT cf.value, COUNT(DISTINCT mp.permid) AS count
       FROM minor_planets mp ${personRole.joins}
       JOIN citation_facets cf ON mp.permid = cf.permid AND cf.kind = 'person_role'
       ${personRole.where}
       GROUP BY 1 ORDER BY count DESC, 1`
    ).bind(...personRole.params),

    db.prepare(
      `SELECT cf.value, COUNT(DISTINCT mp.permid) AS count
       FROM minor_planets mp ${gender.joins}
       JOIN citation_facets cf ON mp.permid = cf.permid AND cf.kind = 'entity_gender'
       ${gender.where}
       GROUP BY 1 ORDER BY count DESC, 1`
    ).bind(...gender.params),

    db.prepare(
      `SELECT df.value, COUNT(DISTINCT mp.permid) AS count
       FROM minor_planets mp ${discoverer.joins}
       JOIN discovery_facets df ON mp.permid = df.permid AND df.kind = 'discoverer'
       ${discoverer.where}
       GROUP BY 1 ORDER BY count DESC, 1 LIMIT 80`
    ).bind(...discoverer.params),

    db.prepare(
      `SELECT df.value, COUNT(DISTINCT mp.permid) AS count
       FROM minor_planets mp ${observatory.joins}
       JOIN discovery_facets df ON mp.permid = df.permid AND df.kind = 'observatory'
       ${observatory.where}
       GROUP BY 1 ORDER BY count DESC, 1 LIMIT 80`
    ).bind(...observatory.params),

    db.prepare(
      `SELECT COUNT(DISTINCT mp.permid) AS count
       FROM minor_planets mp ${flag.joins} ${withCondition(flag.where, "mp.is_neo = 1")}`
    ).bind(...flag.params),

    db.prepare(
      `SELECT COUNT(DISTINCT mp.permid) AS count
       FROM minor_planets mp ${flag.joins} ${withCondition(flag.where, "mp.is_pha = 1")}`
    ).bind(...flag.params),
  ]);

  return {
    orbit_types: orbitRes.results as { value: string; count: number }[],
    citation_categories: citationRes.results as { value: string; count: number }[],
    person_roles: personRoleRes.results as { value: string; count: number }[],
    genders: genderRes.results as { value: string; count: number }[],
    discoverers: discovererRes.results as { value: string; count: number }[],
    observatories: observatoryRes.results as { value: string; count: number }[],
    flags: [
      { value: "NEO", count: (neoRes.results[0] as { count: number })?.count ?? 0 },
      { value: "PHA", count: (phaRes.results[0] as { count: number })?.count ?? 0 },
    ],
  };
}

type FacetGroup = "orbit" | "citationCategory" | "personRole" | "gender"
  | "discoverer" | "observatory" | "flag";

function facetContext(args: FilterArgs, omittedGroup: FacetGroup) {
  const context: FilterArgs = {
    ...args,
    orbit: omittedGroup === "orbit" ? [] : args.orbit,
    citationCategory: omittedGroup === "citationCategory" ? [] : args.citationCategory,
    personRole: omittedGroup === "personRole" ? [] : args.personRole,
    gender: omittedGroup === "gender" ? [] : args.gender,
    discoverer: omittedGroup === "discoverer" ? [] : args.discoverer,
    observatory: omittedGroup === "observatory" ? [] : args.observatory,
    flag: omittedGroup === "flag" ? [] : args.flag,
  };
  return buildFilters(context);
}

function withCondition(where: string, condition: string) {
  return where ? `${where} AND ${condition}` : `WHERE ${condition}`;
}
