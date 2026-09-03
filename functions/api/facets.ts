import { Env } from "../types";
import { d1CacheHeaders, jsonResponse, parseFilterArgs, buildFilters } from "../db";

export const onRequestGet: PagesFunction<Env> = async (ctx) => {
  const cached = await caches.default.match(ctx.request);
  if (cached) return cached;

  const url = new URL(ctx.request.url);
  const db = ctx.env.DB;

  const filterArgs = parseFilterArgs(url);
  const { joins, where, params: filterParams } = buildFilters(filterArgs);

  const facets = await buildFacets(db, joins, where, filterParams);
  const response = jsonResponse(facets, 200, d1CacheHeaders());
  ctx.waitUntil(caches.default.put(ctx.request, response.clone()));
  return response;
};

async function buildFacets(
  db: D1Database,
  joins: string,
  where: string,
  filterParams: (string | number)[]
) {
  const neoWhere = where ? `${where} AND mp.is_neo = 1` : "WHERE mp.is_neo = 1";
  const phaWhere = where ? `${where} AND mp.is_pha = 1` : "WHERE mp.is_pha = 1";

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
       FROM minor_planets mp ${joins} ${where}
       GROUP BY 1 ORDER BY count DESC, 1`
    ).bind(...filterParams),

    db.prepare(
      `SELECT c.value, COUNT(DISTINCT mp.permid) AS count
       FROM minor_planets mp ${joins}
       JOIN categories c ON mp.permid = c.permid AND c.kind = 'citation'
       ${where}
       GROUP BY 1 ORDER BY count DESC, 1`
    ).bind(...filterParams),

    db.prepare(
      `SELECT cf.value, COUNT(DISTINCT mp.permid) AS count
       FROM minor_planets mp ${joins}
       JOIN citation_facets cf ON mp.permid = cf.permid AND cf.kind = 'person_role'
       ${where}
       GROUP BY 1 ORDER BY count DESC, 1`
    ).bind(...filterParams),

    db.prepare(
      `SELECT cf.value, COUNT(DISTINCT mp.permid) AS count
       FROM minor_planets mp ${joins}
       JOIN citation_facets cf ON mp.permid = cf.permid AND cf.kind = 'entity_gender'
       ${where}
       GROUP BY 1 ORDER BY count DESC, 1`
    ).bind(...filterParams),

    db.prepare(
      `SELECT df.value, COUNT(DISTINCT mp.permid) AS count
       FROM minor_planets mp ${joins}
       JOIN discovery_facets df ON mp.permid = df.permid AND df.kind = 'discoverer'
       ${where}
       GROUP BY 1 ORDER BY count DESC, 1 LIMIT 80`
    ).bind(...filterParams),

    db.prepare(
      `SELECT df.value, COUNT(DISTINCT mp.permid) AS count
       FROM minor_planets mp ${joins}
       JOIN discovery_facets df ON mp.permid = df.permid AND df.kind = 'observatory'
       ${where}
       GROUP BY 1 ORDER BY count DESC, 1 LIMIT 80`
    ).bind(...filterParams),

    db.prepare(`SELECT COUNT(DISTINCT mp.permid) AS count FROM minor_planets mp ${joins} ${neoWhere}`)
      .bind(...filterParams),

    db.prepare(`SELECT COUNT(DISTINCT mp.permid) AS count FROM minor_planets mp ${joins} ${phaWhere}`)
      .bind(...filterParams),
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
