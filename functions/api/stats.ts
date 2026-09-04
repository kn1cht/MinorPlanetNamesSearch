import { Env } from "../types";
import { d1CacheHeaders, jsonResponse } from "../db";

export const onRequestGet: PagesFunction<Env> = async (ctx) => {
  // Stats has no request parameters.  Use one canonical cache key so a
  // harmless query string cannot force a cache miss and rerun aggregations.
  const cacheKey = new Request(new URL("/api/stats", ctx.request.url).toString());
  const cached = await caches.default.match(cacheKey);
  if (cached) return cached;

  const db = ctx.env.DB;

  let payload: Record<string, unknown> | null = null;
  try {
    const snapshot = await db.prepare(
      "SELECT payload_json FROM dataset_stats WHERE cache_key = 'base'"
    ).first<{ payload_json: string }>();
    if (snapshot) {
      const parsed: unknown = JSON.parse(snapshot.payload_json);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        payload = parsed as Record<string, unknown>;
      }
    }
  } catch (error) {
    // During a rolling deploy, an older D1 import may not yet have the
    // materialized table.  Preserve service until the accompanying reimport.
    console.warn("dataset_stats snapshot unavailable; calculating stats", error);
  }

  if (!payload) payload = await buildStats(db);

  const response = jsonResponse(payload, 200, d1CacheHeaders());
  ctx.waitUntil(caches.default.put(cacheKey, response.clone()));
  return response;
};

async function buildStats(db: D1Database): Promise<Record<string, unknown>> {

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

  return {
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
  };
}
