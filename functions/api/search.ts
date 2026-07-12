import { Env } from "../types";
import {
  jsonResponse,
  param,
  params,
  intParam,
  parseFilterArgs,
  buildFilters,
  buildOrderBy,
  makeCitationSnippet,
  representativeQuery,
} from "../db";

export const onRequestGet: PagesFunction<Env> = async (ctx) => {
  const url = new URL(ctx.request.url);
  const db = ctx.env.DB;

  const filterArgs = parseFilterArgs(url);
  const sort = param(url, "sort", "alpha");
  const direction = param(url, "direction", "asc");
  let limit = intParam(url, "limit", 50);
  let offset = intParam(url, "offset", 0);
  limit = Math.max(1, Math.min(limit, 200));
  offset = Math.max(0, offset);

  const { where, params: filterParams, joins } = buildFilters(filterArgs);
  const repQ = representativeQuery(filterArgs.q);
  const { orderBy, params: orderParams } = buildOrderBy(sort, direction, repQ);

  // Execute count and items queries concurrently
  const [countRes, itemsRes] = await db.batch([
    db.prepare(
      `SELECT COUNT(DISTINCT mp.permid) AS total FROM minor_planets mp ${joins} ${where}`
    ).bind(...filterParams),
    db.prepare(
      `SELECT DISTINCT
         mp.permid, mp.name_ascii, mp.name_display, mp.iau_designation,
         mp.citation_text, mp.discovery_date, mp.discovery_site,
         mp.discoverer_text, mp.orbit_type, mp.is_neo, mp.is_pha,
         mp.absolute_magnitude_h, mp.semimajor_axis, mp.eccentricity, mp.inclination
       FROM minor_planets mp
       ${joins} ${where} ${orderBy}
       LIMIT ? OFFSET ?`
    ).bind(...filterParams, ...orderParams, limit, offset),
  ]);

  const total = (countRes.results[0] as { total: number })?.total ?? 0;
  const rows = itemsRes.results as Record<string, unknown>[];

  // Build items with explicit typing
  const items: Array<Record<string, unknown> & { citation_categories: string[] }> = rows.map((row) => {
    const citation = (row["citation_text"] as string) ?? "";
    return {
      ...row,
      is_neo: Boolean(row["is_neo"]),
      is_pha: Boolean(row["is_pha"]),
      citation_snippet: makeCitationSnippet(citation, repQ),
      citation_text: undefined,
      citation_categories: [] as string[],
    };
  });

  // Attach citation categories
  if (items.length > 0) {
    const permids = items.map((i) => i.permid as string);
    const placeholders = permids.map(() => "?").join(", ");
    const { results: catRows } = await db
      .prepare(
        `SELECT permid, value FROM categories WHERE kind = 'citation' AND permid IN (${placeholders}) ORDER BY value`
      )
      .bind(...permids)
      .all<{ permid: string; value: string }>();
    const byPermid: Record<string, string[]> = {};
    for (const r of catRows) {
      if (!byPermid[r.permid]) byPermid[r.permid] = [];
      byPermid[r.permid].push(r.value);
    }
    for (const item of items) {
      item.citation_categories = byPermid[item.permid as string] ?? [];
    }
  }

  return jsonResponse({
    items,
    limit,
    offset,
    total,
  });
};
