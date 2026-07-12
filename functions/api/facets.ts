import { Env } from "../types";
import { jsonResponse, parseFilterArgs, buildFilters } from "../db";

export const onRequestGet: PagesFunction<Env> = async (ctx) => {
  const url = new URL(ctx.request.url);
  const db = ctx.env.DB;

  const filterArgs = parseFilterArgs(url);
  const { joins, where, params: filterParams } = buildFilters(filterArgs);

  const facets = await buildFacets(db, joins, where, filterParams);
  return jsonResponse(facets);
};

async function buildFacets(
  db: D1Database,
  joins: string,
  where: string,
  filterParams: (string | number)[]
) {
  // Orbit Types
  const orbitRows = await db
    .prepare(
      `SELECT COALESCE(mp.orbit_type, 'Unclassified') AS value, COUNT(DISTINCT mp.permid) AS count
       FROM minor_planets mp ${joins} ${where}
       GROUP BY 1 ORDER BY count DESC, 1`
    )
    .bind(...filterParams)
    .all<{ value: string; count: number }>();

  // Citation Categories
  const citationRows = await db
    .prepare(
      `SELECT c.value, COUNT(DISTINCT mp.permid) AS count
       FROM minor_planets mp ${joins}
       JOIN categories c ON mp.permid = c.permid AND c.kind = 'citation'
       ${where}
       GROUP BY 1 ORDER BY count DESC, 1`
    )
    .bind(...filterParams)
    .all<{ value: string; count: number }>();

  // Discoverers
  const discovererRows = await db
    .prepare(
      `SELECT df.value, COUNT(DISTINCT mp.permid) AS count
       FROM minor_planets mp ${joins}
       JOIN discovery_facets df ON mp.permid = df.permid AND df.kind = 'discoverer'
       ${where}
       GROUP BY 1 ORDER BY count DESC, 1 LIMIT 80`
    )
    .bind(...filterParams)
    .all<{ value: string; count: number }>();

  // Observatories
  const observatoryRows = await db
    .prepare(
      `SELECT df.value, COUNT(DISTINCT mp.permid) AS count
       FROM minor_planets mp ${joins}
       JOIN discovery_facets df ON mp.permid = df.permid AND df.kind = 'observatory'
       ${where}
       GROUP BY 1 ORDER BY count DESC, 1 LIMIT 80`
    )
    .bind(...filterParams)
    .all<{ value: string; count: number }>();

  // Flags
  const neoWhere = where ? `${where} AND mp.is_neo = 1` : "WHERE mp.is_neo = 1";
  const phaWhere = where ? `${where} AND mp.is_pha = 1` : "WHERE mp.is_pha = 1";
  
  const neoRow = await db
    .prepare(`SELECT COUNT(DISTINCT mp.permid) AS count FROM minor_planets mp ${joins} ${neoWhere}`)
    .bind(...filterParams)
    .first<{ count: number }>();
    
  const phaRow = await db
    .prepare(`SELECT COUNT(DISTINCT mp.permid) AS count FROM minor_planets mp ${joins} ${phaWhere}`)
    .bind(...filterParams)
    .first<{ count: number }>();

  return {
    orbit_types: orbitRows.results,
    citation_categories: citationRows.results,
    discoverers: discovererRows.results,
    observatories: observatoryRows.results,
    flags: [
      { value: "NEO", count: neoRow?.count ?? 0 },
      { value: "PHA", count: phaRow?.count ?? 0 },
    ],
  };
}
