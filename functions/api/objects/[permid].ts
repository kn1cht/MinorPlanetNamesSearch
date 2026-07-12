import { Env } from "../../types";
import { jsonResponse } from "../../db";

interface Params {
  permid: string;
}

export const onRequestGet: PagesFunction<Env, keyof Params> = async (ctx) => {
  const db = ctx.env.DB;
  const permid = decodeURIComponent(ctx.params.permid as string);

  const row = await db
    .prepare("SELECT * FROM minor_planets WHERE permid = ?")
    .bind(permid)
    .first<Record<string, unknown>>();

  if (!row) {
    return jsonResponse({ error: "not found" }, 404);
  }

  const { results: catRows } = await db
    .prepare(
      "SELECT kind, value, source, confidence FROM categories WHERE permid = ? ORDER BY kind, value"
    )
    .bind(permid)
    .all<{ kind: string; value: string; source: string; confidence: number }>();

  const data = { ...row };
  data["is_neo"] = Boolean(data["is_neo"]);
  data["is_one_km_neo"] = Boolean(data["is_one_km_neo"]);
  data["is_pha"] = Boolean(data["is_pha"]);
  data["categories"] = catRows;
  // Citation text omitted – user directed to official source
  delete data["citation_text"];
  delete data["citation_html"];

  return jsonResponse(data);
};
