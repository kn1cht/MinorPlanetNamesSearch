import { Env } from "../types";
import { d1CacheHeaders, jsonResponse } from "../db";

export const onRequestGet: PagesFunction<Env> = async (ctx) => {
  const cached = await caches.default.match(ctx.request);
  if (cached) return cached;

  const db = ctx.env.DB;

  const [
    totalRes,
    latestRes,
    orbitRes,
    citationRes,
    personRoleRes,
    genderRes,
    discovererRes,
    observatoryRes,
    neoRes,
    phaRes,
  ] = await db.batch([
    db.prepare("SELECT COUNT(*) AS c FROM minor_planets"),
    db.prepare("SELECT MAX(updated_at) AS latest FROM minor_planets"),
    db.prepare(
      "SELECT COALESCE(orbit_type, 'Unclassified') AS value, COUNT(*) AS count " +
      "FROM minor_planets GROUP BY 1 ORDER BY count DESC, 1"
    ),
    db.prepare(
      "SELECT value, COUNT(*) AS count FROM categories WHERE kind = 'citation' " +
      "GROUP BY 1 ORDER BY count DESC, 1"
    ),
    db.prepare(
      "SELECT value, COUNT(*) AS count FROM citation_facets WHERE kind = 'person_role' " +
      "GROUP BY 1 ORDER BY count DESC, 1"
    ),
    db.prepare(
      "SELECT value, COUNT(*) AS count FROM citation_facets WHERE kind = 'entity_gender' " +
      "GROUP BY 1 ORDER BY count DESC, 1"
    ),
    db.prepare(
      "SELECT value, COUNT(*) AS count FROM discovery_facets WHERE kind = 'discoverer' " +
      "GROUP BY 1 ORDER BY count DESC, 1 LIMIT 80"
    ),
    db.prepare(
      "SELECT value, COUNT(*) AS count FROM discovery_facets WHERE kind = 'observatory' " +
      "GROUP BY 1 ORDER BY count DESC, 1 LIMIT 80"
    ),
    db.prepare("SELECT COUNT(*) AS c FROM minor_planets WHERE is_neo = 1"),
    db.prepare("SELECT COUNT(*) AS c FROM minor_planets WHERE is_pha = 1"),
  ]);

  const response = jsonResponse({
    total: (totalRes.results[0] as { c: number })?.c ?? 0,
    latest_updated_at: (latestRes.results[0] as { latest: string | null })?.latest ?? null,
    orbit_types: orbitRes.results,
    citation_categories: citationRes.results,
    person_roles: personRoleRes.results,
    genders: genderRes.results,
    discoverers: discovererRes.results,
    observatories: observatoryRes.results,
    flags: [
      { value: "NEO", count: (neoRes.results[0] as { c: number })?.c ?? 0 },
      { value: "PHA", count: (phaRes.results[0] as { c: number })?.c ?? 0 },
    ],
  }, 200, d1CacheHeaders());
  ctx.waitUntil(caches.default.put(ctx.request, response.clone()));
  return response;
};
