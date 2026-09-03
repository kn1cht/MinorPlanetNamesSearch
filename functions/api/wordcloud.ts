import { Env } from "../types";
import { jsonResponse } from "../db";

/** Keyword-frequency analysis is intentionally disabled on the public site. */
export const onRequestGet: PagesFunction<Env> = async () => {
  return jsonResponse(
    { error: "Word cloud is disabled on the public site." },
    410,
    { "Cache-Control": "public, max-age=86400" }
  );
};
