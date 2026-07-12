import { Env } from "../types";
import {
  jsonResponse,
  parseFilterArgs,
  buildFilters,
  extractWords,
} from "../db";

export const onRequestGet: PagesFunction<Env> = async (ctx) => {
  const url = new URL(ctx.request.url);
  const db = ctx.env.DB;
  const filterArgs = parseFilterArgs(url);
  const maxWords = parseInt(url.searchParams.get("max_words") ?? "80", 10);

  const { where, params: filterParams, joins } = buildFilters(filterArgs);

  const { results: rows } = await db
    .prepare(
      `SELECT DISTINCT mp.citation_text
       FROM minor_planets mp ${joins} ${where}`
    )
    .bind(...filterParams)
    .all<{ citation_text: string | null }>();

  const counter = new Map<string, number>();
  for (const row of rows) {
    if (row.citation_text) extractWords(row.citation_text, counter);
  }

  const sorted = [...counter.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, maxWords)
    .map(([word, count]) => ({ word, count }));

  return jsonResponse({ words: sorted });
};
