/**
 * Build script: copies web/ -> dist/ for Cloudflare Pages deployment.
 * functions/ is handled natively by Cloudflare Pages.
 */
import { cpSync, mkdirSync, rmSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");

const src = join(root, "web");
const dest = join(root, "dist");

console.log("🔨 Building...");
rmSync(dest, { recursive: true, force: true });
mkdirSync(dest, { recursive: true });

cpSync(src, dest, { recursive: true });
console.log(`✅ Copied web/ -> dist/`);
