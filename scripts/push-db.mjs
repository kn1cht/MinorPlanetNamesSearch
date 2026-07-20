/**
 * Data push script: exports local SQLite DB to SQL and imports to Cloudflare D1.
 *
 * Usage:
 *   node scripts/push-db.mjs           # import to REMOTE D1 (production)
 *   node scripts/push-db.mjs --local   # import to LOCAL D1 (dev)
 *   node scripts/push-db.mjs --db <path>
 */
import { spawnSync } from "child_process";
import { existsSync, writeFileSync, unlinkSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = join(__dirname, "..");
const pythonExecutable = process.env.MPNAMES_PYTHON
  || process.env.PYTHON
  || (process.platform === "win32" && existsSync(join(root, ".venv", "Scripts", "python.exe"))
    ? join(root, ".venv", "Scripts", "python.exe")
    : "python");
const wranglerEntrypoint = join(root, "node_modules", "wrangler", "bin", "wrangler.js");

// Parse args
const args = process.argv.slice(2);
const dbArg = args.indexOf("--db");
const isLocal = args.includes("--local");
const remoteFlag = isLocal ? "" : "--remote";
const dbPath = dbArg !== -1 ? args[dbArg + 1] : join(root, "data", "mpnames.sqlite3");

if (!existsSync(dbPath)) {
  console.error(`❌ Database not found: ${dbPath}`);
  console.error("   Run 'python -m mpnames fetch' first to generate it.");
  process.exit(1);
}

const target = isLocal ? "[LOCAL]" : "[REMOTE/PRODUCTION]";
console.log(`\n🗄  Source DB : ${dbPath}`);
console.log(`🚀 Target D1 : mpnames-db ${target}\n`);

// Dump SQLite -> SQL file (UTF-8)
const dumpFile = join(root, ".push-dump.sql");
console.log(`📦 Dumping SQLite -> SQL...`);

const pyResult = spawnSync(
  pythonExecutable,
  [join(root, "scripts", "dump.py"), dbPath, dumpFile],
  { encoding: "utf8" }
);

if (pyResult.status !== 0) {
  console.error("❌ Python dump failed:", pyResult.stderr || pyResult.stdout);
  process.exit(1);
}

console.log(`✅ Dumped to ${dumpFile}`);

// Count lines for progress
let totalLines = 0;
{
  const countResult = spawnSync(pythonExecutable, ["-c",
    `f=open(r'${dumpFile}', encoding='utf-8'); print(sum(1 for _ in f))`
  ], { encoding: "utf8" });
  totalLines = parseInt(countResult.stdout.trim(), 10) || 0;
}
console.log(`   ${totalLines.toLocaleString()} lines of SQL`);

// Execute via wrangler (it handles chunking internally for large files)
console.log(`\n⏳ Executing on D1... (this may take a few minutes for large databases)\n`);
const result = spawnSync(
  process.execPath,
  [wranglerEntrypoint, "d1", "execute", "mpnames-db", remoteFlag, `--file=${dumpFile}`].filter(Boolean),
  { stdio: "inherit", cwd: root }
);

if (result.status !== 0) {
  console.error("\n❌ Import failed.");
  process.exit(1);
}

// Cleanup dump file
try { unlinkSync(dumpFile); } catch {}

console.log("\n✅ Database pushed successfully!");
console.log(isLocal
  ? "   Run 'npm run dev' to start local preview."
  : "   Run 'npm run deploy' to deploy the application.");
