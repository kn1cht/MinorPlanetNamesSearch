import { Env } from "../types";
import { jsonResponse } from "../db";

export const onRequestGet: PagesFunction<Env> = async (ctx) => {
  const db = ctx.env.DB;

  const total = (
    await db.prepare("SELECT COUNT(*) AS c FROM minor_planets").first<{ c: number }>()
  )?.c ?? 0;

  const latest = (
    await db.prepare("SELECT MAX(updated_at) AS latest FROM minor_planets").first<{ latest: string | null }>()
  )?.latest ?? null;

  const orbitRows = await db
    .prepare(
      "SELECT COALESCE(orbit_type, 'Unclassified') AS value, COUNT(*) AS count " +
      "FROM minor_planets GROUP BY 1 ORDER BY count DESC, 1"
    )
    .all<{ value: string; count: number }>();

  const citationRows = await db
    .prepare(
      "SELECT value, COUNT(*) AS count FROM categories WHERE kind = 'citation' " +
      "GROUP BY 1 ORDER BY count DESC, 1"
    )
    .all<{ value: string; count: number }>();

  const discovererRows = await db
    .prepare(
      "SELECT value, COUNT(*) AS count FROM discovery_facets WHERE kind = 'discoverer' " +
      "GROUP BY 1 ORDER BY count DESC, 1 LIMIT 80"
    )
    .all<{ value: string; count: number }>();

  const observatoryRows = await db
    .prepare(
      "SELECT value, COUNT(*) AS count FROM discovery_facets WHERE kind = 'observatory' " +
      "GROUP BY 1 ORDER BY count DESC, 1 LIMIT 80"
    )
    .all<{ value: string; count: number }>();

  const neoCount = (
    await db.prepare("SELECT COUNT(*) AS c FROM minor_planets WHERE is_neo = 1").first<{ c: number }>()
  )?.c ?? 0;
  const phaCount = (
    await db.prepare("SELECT COUNT(*) AS c FROM minor_planets WHERE is_pha = 1").first<{ c: number }>()
  )?.c ?? 0;

  return jsonResponse({
    total,
    latest_updated_at: latest,
    orbit_types: orbitRows.results,
    citation_categories: citationRows.results,
    discoverers: discovererRows.results,
    observatories: observatoryRows.results,
    flags: [
      { value: "NEO", count: neoCount },
      { value: "PHA", count: phaCount },
    ],
  });
};
